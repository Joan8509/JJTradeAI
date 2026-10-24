"""Extended references preserve geometry, guards and regular-only notices."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from bollinger_reference_scope import (REGULAR, EXTENDED, active_reference_scope,
                                     required_periods)
from bollinger_tick_stream import TickGeometry, TickRepository
from bollinger_phone_worker import (bands_at_open, detect_values,
                                   _aggregate_reference_minutes, _minute_reference_ready, tick)
from bollinger_reference_recovery import missing_reference_windows
from indexed_bollinger_preview import preview_for_bar
from live_market import MarketBar
from market_calendar import MarketSession, MarketSessionRepository
from market_store import MarketBarStore
from tests.test_bollinger_tick_stream import seed, CANDLE, trade

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
OPEN = datetime(2026, 10, 20, 13, 30, tzinfo=UTC)
ROWS = [(OPEN.isoformat(), OPEN.replace(hour=20, minute=0).isoformat())]


class PeriodScopeTests(unittest.TestCase):
    def test_twenty_premarket_references_at_regular_open(self):
        periods = required_periods(ROWS, OPEN, scope=EXTENDED)
        self.assertEqual(len(periods), 20)
        self.assertEqual(periods[0][0].astimezone(NY).strftime('%H:%M'), '04:30')
        self.assertEqual(periods[-1], (OPEN-timedelta(minutes=15), OPEN))

    def test_weekend_and_holiday_not_generated(self):
        friday = datetime(2026, 10, 16, 13, 30, tzinfo=UTC)
        monday = friday+timedelta(days=3)
        rows = [(d.isoformat(), d.replace(hour=20, minute=0).isoformat()) for d in (friday, monday)]
        periods = required_periods(rows, monday.replace(hour=8, minute=0), scope=EXTENDED)
        self.assertEqual(periods[-1][1], friday.replace(day=17, hour=0, minute=0))
        self.assertEqual({a.astimezone(NY).date() for a, b in periods}, {friday.date()})

    def test_dst_changes_utc_but_preserves_local_window(self):
        opened = datetime(2026, 11, 2, 14, 30, tzinfo=UTC)
        periods = required_periods([(opened.isoformat(), opened.replace(hour=21, minute=0).isoformat())], opened, scope=EXTENDED)
        self.assertEqual(periods[0][0].astimezone(NY).strftime('%H:%M'), '04:30')
        self.assertEqual(periods[-1][1], opened)

    def test_partial_future_period_is_never_a_closed_reference(self):
        periods = required_periods(ROWS, OPEN+timedelta(minutes=7), scope=EXTENDED)
        self.assertEqual(periods[-1][1], OPEN)

    def test_half_day_extended_window_requires_verified_schedule(self):
        half = [(OPEN.isoformat(), OPEN.replace(hour=17, minute=0).isoformat())]
        self.assertEqual(required_periods(half, OPEN, scope=EXTENDED), [])
        self.assertTrue(required_periods(half, OPEN.replace(hour=17, minute=0), count=10))

    def test_config_cannot_activate_unverified_scope(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'policy.json'
            with patch('bollinger_reference_scope.POLICY_PATH', p):
                self.assertEqual(active_reference_scope(), REGULAR)
                p.write_text(json.dumps(dict(active_scope=EXTENDED, activation_state='PENDING_COVERAGE')))
                with self.assertRaisesRegex(ValueError, 'NOT_VERIFIED'):
                    active_reference_scope()
                p.write_text(json.dumps(dict(active_scope=EXTENDED, activation_state='VERIFIED')))
                self.assertEqual(active_reference_scope(), EXTENDED)


class ExtendedGeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'market.db'
        MarketSessionRepository(self.db).upsert([MarketSession(OPEN.date(), OPEN, OPEN.replace(hour=20, minute=0))])
        self.store = MarketBarStore(self.db)
        self.prior = [99. if i % 2 == 0 else 101. for i in range(19)]+[100.]
        rows = [dict(date=OPEN-timedelta(minutes=300)+timedelta(minutes=i*15+m),
                     open=p, high=p, low=p, close=p, volume=100)
                for i, p in enumerate(self.prior) for m in range(15)]
        self.store.upsert_frame(pd.DataFrame(rows), symbol='AAPL', provider='ALPACA', feed='iex')
        self.now = OPEN+timedelta(seconds=1)
        self.geometry = TickGeometry(self.db, 'iex', now=lambda: self.now, reference_scope=EXTENDED)
        self.geometry.status('CONECTADO', OPEN-timedelta(seconds=1))

    def observe(self, price, second, identity):
        self.now = OPEN+timedelta(seconds=second)
        return self.geometry.observe(trade(price, self.now, identity), self.now)

    def test_upper_lower_formula_unchanged_and_retraction_stays_visible(self):
        for price, side in ((104., 'SUPERIOR'), (96., 'INFERIOR')):
            self.geometry.status('CONECTADO', OPEN-timedelta(seconds=1))
            self.observe(100., 1, int(price)*10)
            result, reason = self.observe(price, 2, int(price)*10+1)
            self.assertEqual(reason, 'EXIT')
            previous_upper, previous_lower = bands_at_open(self.prior[:-1], self.prior[-1])
            upper, lower = bands_at_open(self.prior[1:], price)
            opening_upper, opening_lower = bands_at_open(self.prior[1:], 100.)
            expected = detect_values(self.prior[-1], previous_upper, previous_lower, sum(self.prior)/20,
                price, upper, lower, (sum(self.prior[1:])+price)/20,
                opening=100., opening_upper=opening_upper, opening_lower=opening_lower)
            self.assertEqual(result['signal']['side'], expected)
            self.assertEqual(expected, side)
            self.assertEqual(result['reference_scope'], EXTENDED)
            self.assertIsNone(self.observe(100., 3, int(price)*10+2)[0]['signal'])

    def test_opening_outside_still_cannot_signal(self):
        self.observe(104., 1, 1)
        self.assertIsNone(self.observe(106., 2, 2)[0]['signal'])

    def test_premarket_and_postmarket_trades_cannot_signal(self):
        for stamp in (OPEN-timedelta(minutes=1), OPEN.replace(hour=20, minute=1)):
            self.now = stamp
            self.assertEqual(self.geometry.observe(trade(104., stamp), stamp)[1], 'OUTSIDE_SESSION')

    def test_missing_period_never_substitutes_older_or_regular_reference(self):
        missing = OPEN-timedelta(minutes=75)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp>=? AND timestamp<?',
                       (missing.isoformat(), (missing+timedelta(minutes=15)).isoformat()))
        result, reason = self.observe(100., 1, 1)
        self.assertEqual(reason, 'WAITING_FOR_OPEN_OR_HISTORY')
        self.assertEqual(missing_reference_windows(self.db, 'AAPL', 'iex', OPEN, reference_scope=EXTENDED),
                         [(missing, missing+timedelta(minutes=15))])

    def test_exact_previous_final_minute_still_required(self):
        minute = OPEN-timedelta(minutes=1)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp=?', (minute.isoformat(),))
        self.assertEqual(self.observe(100., 1, 1)[1], 'WAITING_FOR_OPEN_OR_HISTORY')
        self.assertEqual(missing_reference_windows(self.db, 'AAPL', 'iex', OPEN, reference_scope=EXTENDED), [(minute, OPEN)])

    def test_minute_fallback_and_preview_use_same_extended_closes(self):
        bar = MarketBar('AAPL', OPEN, 100, 104, 100, 104, 100)
        self.store.upsert_bar(bar, provider='ALPACA', feed='iex')
        bars = self.store.load_frame(symbol='AAPL', provider='ALPACA', feed='iex')
        aggregated = _aggregate_reference_minutes(bars, EXTENDED)
        self.assertTrue(_minute_reference_ready(self.db, bars, aggregated, reference_scope=EXTENDED))
        preview = preview_for_bar(self.db, bar, feed='iex', reference_scope=EXTENDED)
        upper, lower = bands_at_open(self.prior[1:], 104.)
        self.assertAlmostEqual(preview['bollinger_upper'], upper)
        self.assertAlmostEqual(preview['bollinger_lower'], lower)
        self.assertFalse(preview['can_operate'])

    def test_stale_and_correction_guards_unchanged(self):
        self.now = OPEN+timedelta(seconds=5)
        self.assertEqual(self.geometry.observe(trade(100., OPEN), self.now)[1], 'DISCONNECTED_OR_STALE')
        self.geometry.observe(dict(T='c', S='AAPL'), self.now)
        self.assertEqual(self.observe(100., 6, 2)[1], 'CORRECTION_QUARANTINE')

    def test_regular_default_does_not_silently_use_extended_history(self):
        geometry = TickGeometry(self.db, 'iex', now=lambda: self.now, reference_scope=REGULAR)
        geometry.status('CONECTADO', OPEN-timedelta(seconds=1))
        self.assertEqual(geometry.observe(trade(100., self.now), self.now)[1], 'WAITING_FOR_OPEN_OR_HISTORY')

    def test_radar_cannot_send_snapshot_from_another_reference_scope(self):
        self.observe(100., 1, 1)
        snapshot, _ = self.observe(104., 2, 2)
        repository = TickRepository(self.db)
        repository.flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex', symbols=['AAPL'], now=self.now)
        sender = Mock()
        with patch('bollinger_reference_scope.active_reference_scope', return_value=REGULAR), \
             patch('bollinger_phone_worker.enabled', return_value=True), \
             patch('bollinger_phone_worker.connection', return_value={'chat_id': 'fixture'}):
            result = tick(self.db, as_of=self.now, sender=sender, support_worker=Mock())
        self.assertEqual(result['sent'], 0)
        sender.assert_not_called()

    def test_missing_calendar_is_not_reported_as_no_gaps(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM market_sessions')
        with self.assertRaisesRegex(ValueError, 'CALENDAR_UNAVAILABLE'):
            missing_reference_windows(self.db, 'AAPL', 'iex', OPEN, reference_scope=EXTENDED)

    def test_same_scope_notice_can_send_and_dedup_still_prevents_replay(self):
        self.observe(100., 1, 1)
        snapshot, _ = self.observe(104., 2, 2)
        repository = TickRepository(self.db)
        repository.flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex', symbols=['AAPL'], now=self.now)
        sender = Mock(return_value={'message_id': 1})
        with patch('bollinger_reference_scope.active_reference_scope', return_value=EXTENDED), \
             patch('bollinger_phone_worker.enabled', return_value=True), \
             patch('bollinger_phone_worker.connection', return_value={'chat_id': 'fixture'}), \
             patch('manual_trade_links.signal_link', return_value=None):
            self.assertEqual(tick(self.db, as_of=self.now, sender=sender, support_worker=Mock())['sent'], 1)
            self.assertEqual(tick(self.db, as_of=self.now, sender=sender, support_worker=Mock())['sent'], 0)
        sender.assert_called_once()

    def test_scope_switch_during_support_prevents_send(self):
        self.observe(100., 1, 1)
        snapshot, _ = self.observe(104., 2, 2)
        repository = TickRepository(self.db)
        repository.flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex', symbols=['AAPL'], now=self.now)
        support = Mock()
        def switch(*args):
            snapshot['reference_scope'] = REGULAR
            repository.flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex', symbols=['AAPL'], now=self.now)
        support.submit.side_effect = switch
        sender = Mock()
        with patch('bollinger_reference_scope.active_reference_scope', return_value=EXTENDED), \
             patch('bollinger_phone_worker.enabled', return_value=True), \
             patch('bollinger_phone_worker.connection', return_value={'chat_id': 'fixture'}):
            self.assertEqual(tick(self.db, as_of=self.now, sender=sender, support_worker=support)['sent'], 0)
        sender.assert_not_called()

    def test_readonly_coverage_report_distinguishes_complete_and_missing(self):
        from scripts.check_bollinger_reference_scope import coverage
        before = self.db.read_bytes()
        self.assertEqual(coverage(self.db, 'AAPL', 'iex', OPEN, EXTENDED)['status'], 'COMPLETE')
        self.assertEqual(coverage(self.db, 'AAPL', 'iex', OPEN, REGULAR)['status'], 'CALENDAR_UNAVAILABLE')
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
