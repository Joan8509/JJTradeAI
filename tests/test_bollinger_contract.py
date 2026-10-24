"""Protection regressions on isolated databases; never contact market or Telegram."""
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from bollinger_phone_worker import _minute_signal, _recent_minute_source, tick
from bollinger_tick_stream import TickGeometry, TickRepository
from live_market import MarketBar
from telegram_alerts import TelegramError
from tests.test_bollinger_tick_stream import CANDLE, seed, trade


class BollingerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'isolated.db'
        self.store, _ = seed(self.database)
        self.now = CANDLE+timedelta(minutes=1, seconds=2)

    def bar(self, stamp=CANDLE, opening=100., price=104.):
        self.store.upsert_bar(MarketBar('AAPL', stamp, opening, max(opening, price),
                                       min(opening, price), price, 100), provider='ALPACA', feed='iex')

    def fallback(self):
        return _minute_signal(self.database, self.store, 'AAPL', self.now, True)

    def test_complete_minute_references_keep_both_directions(self):
        for price, side in ((104., 'SUPERIOR'), (96., 'INFERIOR')):
            with self.subTest(side=side):
                self.bar(price=price)
                result = self.fallback()
                self.assertIsNotNone(result)
                self.assertEqual(result[4]['side'], side)
                self.assertEqual(result[4]['candle'], CANDLE.isoformat())

    def test_connected_stream_with_stale_or_future_heartbeat_cannot_fall_back_to_bars(self):
        from bollinger_tick_stream import TickRepository
        repo = TickRepository(self.database)
        for heartbeat in (self.now-timedelta(seconds=4), self.now+timedelta(seconds=1)):
            with self.subTest(heartbeat=heartbeat):
                repo.flush({}, [], state='CONECTADO', feed='iex', symbols=['AAPL'], now=heartbeat)
                with patch('bollinger_phone_worker._minute_signal', side_effect=AssertionError('unsafe fallback')), \
                     patch('bollinger_phone_worker.enabled', return_value=False):
                    result = tick(self.database, as_of=self.now, support_worker=Mock())
                self.assertEqual(result['sent'], 0)
                self.assertEqual(result['price_mode'], 'TRADES')

    def test_heartbeat_advanced_during_snapshot_is_compared_with_post_read_clock(self):
        from datetime import datetime
        from bollinger_tick_stream import TickRepository
        start = self.now
        later = start+timedelta(seconds=1)
        source = start+timedelta(milliseconds=500)
        signal = {'side': 'SUPERIOR', 'price': 104., 'candle': CANDLE.isoformat()}
        payload = {'symbol': 'AAPL', 'provider': 'ALPACA', 'feed': 'iex',
                   'source_timestamp': source.isoformat(), 'received_at': source.isoformat(),
                   'checked_at': source.isoformat(), 'opening': 100., 'signal': signal}
        TickRepository(self.database).flush({'AAPL': payload}, [], state='CONECTADO',
            feed='iex', symbols=['AAPL'], now=source)
        sender = Mock(return_value={'message_id': 1})
        with patch('bollinger_phone_worker.datetime', wraps=datetime) as clock, \
             patch('bollinger_phone_worker.enabled', return_value=True), \
             patch('bollinger_phone_worker.connection', return_value={'chat_id': 'fixture'}), \
             patch('manual_trade_links.signal_link', return_value=None), \
             patch('bollinger_phone_worker._minute_signal', side_effect=AssertionError('unsafe fallback')):
            clock.now.side_effect = [start]+[later]*12
            self.assertEqual(tick(self.database, sender=sender, support_worker=Mock())['sent'], 1)
        sender.assert_called_once()

    def test_source_seeks_preserve_legacy_selection_across_providers_and_feeds(self):
        # Test the old query's actual result on an isolated multi-source DB,
        # including other symbols, future minutes and unavailable time ranges.
        with closing(sqlite3.connect(self.database)) as db, db:
            for provider, feed, symbol, offset in (
                ('ALPACA', 'iex', 'AAPL', 0), ('ALPACA', 'sip', 'AAPL', 1),
                ('OTHER', 'fixture', 'AAPL', -1), ('OTHER', 'fixture', 'SPY', 1),
                ('TIED', 'fixture', 'AAPL', 1),
                ('FUTURE', 'fixture', 'AAPL', 100), ('OLD', 'fixture', 'AAPL', -100),
            ):
                stamp = (CANDLE+timedelta(minutes=offset)).isoformat()
                db.execute('INSERT OR REPLACE INTO minute_bars '
                           '(provider,feed,symbol,timestamp,open,high,low,close,volume,received_at) '
                           'VALUES(?,?,?,?,100,104,100,104,100,?)', (provider, feed, symbol, stamp, stamp))
        for symbol in ('AAPL', 'SPY', 'ABSENT'):
            for offset in (1, 2, 6):
                with self.subTest(symbol=symbol, offset=offset):
                    now = CANDLE+timedelta(minutes=offset)
                    with closing(sqlite3.connect(self.database)) as db:
                        previous = db.execute('SELECT provider,feed,MAX(timestamp) FROM minute_bars '
                            'WHERE symbol=? AND timestamp>=? AND timestamp<=? GROUP BY provider,feed '
                            'ORDER BY MAX(timestamp) DESC LIMIT 1',
                            (symbol, (now-timedelta(minutes=3)).isoformat(), (now-timedelta(minutes=1)).isoformat())).fetchone()
                    self.assertEqual(_recent_minute_source(self.database, symbol, now), previous)

    def test_minute_missing_period_blocks_until_official_recovery(self):
        self.bar()
        missing = CANDLE.replace(day=12, hour=18, minute=15)
        original = self.store.load_frame(symbol='AAPL', provider='ALPACA', feed='iex',
                                         start=missing, end=missing+timedelta(minutes=14))
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp>=? AND timestamp<?',
                       (missing.isoformat(), (missing+timedelta(minutes=15)).isoformat()))
        self.assertIsNone(self.fallback())
        self.store.upsert_frame(original, symbol='AAPL', provider='ALPACA', feed='iex', only_missing=True)
        result = self.fallback()
        self.assertEqual(result[4]['side'], 'SUPERIOR')
        self.assertEqual(result[2], CANDLE)
        # Recovery supplies reference bars, never historical signal evaluation.
        with closing(sqlite3.connect(self.database)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='bollinger_phone_notifications'").fetchone())

    def test_locked_storage_fails_closed_and_recovers_after_unlock(self):
        self.bar()
        with closing(sqlite3.connect(self.database)) as writer:
            writer.execute('BEGIN EXCLUSIVE')
            try:
                self.assertIsNone(_recent_minute_source(self.database, 'AAPL', self.now))
            finally:
                writer.rollback()
        self.assertEqual(_recent_minute_source(self.database, 'AAPL', self.now), ('ALPACA', 'iex', CANDLE.isoformat()))

    def test_minute_missing_previous_close_and_missing_calendar_fail_closed(self):
        self.bar()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp=?', ((CANDLE-timedelta(minutes=1)).isoformat(),))
        self.assertIsNone(self.fallback())
        seed(self.database)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM market_sessions WHERE session_date<?', (CANDLE.date().isoformat(),))
        self.assertIsNone(self.fallback())

    def test_minute_later_opening_cannot_replace_missing_first_official_minute(self):
        self.bar(stamp=CANDLE+timedelta(minutes=1), opening=100., price=104.)
        self.now = CANDLE+timedelta(minutes=2, seconds=2)
        self.assertIsNone(self.fallback())
        self.bar()
        self.assertEqual(self.fallback()[4]['side'], 'SUPERIOR')

    def geometry(self):
        self.now = CANDLE+timedelta(seconds=1)
        geometry = TickGeometry(self.database, 'iex', now=lambda: self.now)
        geometry.status('CONECTADO', CANDLE-timedelta(seconds=1))
        geometry.observe(trade(100., self.now, 1), self.now)
        self.now += timedelta(seconds=1)
        snapshot, reason = geometry.observe(trade(104., self.now, 2), self.now)
        self.assertEqual(reason, 'EXIT')
        return geometry, snapshot

    def test_cancellation_quarantines_an_existing_exit(self):
        geometry, _ = self.geometry()
        self.assertEqual(geometry.observe({'T': 'x', 'S': 'AAPL', 'i': 2}, self.now)[1],
                         'CORRECTION_QUARANTINE')
        self.now += timedelta(seconds=1)
        snapshot, reason = geometry.observe(trade(105., self.now, 3), self.now)
        self.assertEqual(reason, 'CORRECTION_QUARANTINE')
        self.assertIsNone(snapshot['signal'])

    def test_exact_three_seconds_allowed_but_one_microsecond_older_rejected(self):
        geometry, _ = self.geometry()
        source = self.now
        self.now += timedelta(seconds=3)
        self.assertEqual(geometry.observe(trade(104., source, 3), source)[1], 'EXIT')
        self.now += timedelta(microseconds=1)
        self.assertEqual(geometry.observe(trade(104., source, 4), source)[1], 'DISCONNECTED_OR_STALE')
        self.assertEqual(geometry.observe(trade(104., self.now+timedelta(microseconds=1), 5), self.now)[1],
                         'DISCONNECTED_OR_STALE')

    def test_disconnect_stale_heartbeat_and_future_price_at_send_never_send(self):
        _, snapshot = self.geometry()
        repo = TickRepository(self.database)
        for case in ('disconnect', 'stale_heartbeat', 'future_price'):
            with self.subTest(case=case):
                repo.flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex', symbols=['AAPL'], now=self.now)
                support = Mock()
                def invalidate(*args):
                    changed = dict(snapshot)
                    if case == 'future_price':
                        changed['source_timestamp'] = (self.now+timedelta(microseconds=1)).isoformat()
                    repo.flush({'AAPL': changed}, [], state='DETENIDO' if case == 'disconnect' else 'CONECTADO',
                               feed='iex', symbols=['AAPL'],
                               now=self.now-timedelta(seconds=4) if case == 'stale_heartbeat' else self.now)
                support.submit.side_effect = invalidate
                sender = Mock()
                with patch('bollinger_phone_worker.enabled', return_value=True), \
                     patch('bollinger_phone_worker.connection', return_value={'chat_id': 'test'}):
                    self.assertEqual(tick(self.database, as_of=self.now, sender=sender, support_worker=support)['sent'], 0)
                sender.assert_not_called()

    def test_uncertain_delivery_survives_repository_restart_and_utc_et_alias(self):
        _, snapshot = self.geometry()
        TickRepository(self.database).flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex',
                                           symbols=['AAPL'], now=self.now)
        sender = Mock(side_effect=TelegramError('Synthetic unconfirmed delivery'))
        with patch('bollinger_phone_worker.enabled', return_value=True), \
             patch('bollinger_phone_worker.connection', return_value={'chat_id': 'test'}), \
             patch('manual_trade_links.signal_link', return_value=None):
            self.assertEqual(tick(self.database, as_of=self.now, sender=sender, support_worker=Mock())['sent'], 0)
            with closing(sqlite3.connect(self.database)) as db:
                before = db.execute('SELECT * FROM bollinger_phone_notifications').fetchall()
                original = db.execute('SELECT * FROM bollinger_live_events').fetchall()
            self.assertEqual(before[0][1], 'ENVIO_NO_CONFIRMADO')
            snapshot = json.loads(json.dumps(snapshot))
            snapshot['signal']['candle'] = '2026-10-13T10:00:00-04:00'
            TickRepository(self.database).flush({'AAPL': snapshot}, [], state='CONECTADO', feed='iex',
                                               symbols=['AAPL'], now=self.now)
            self.assertEqual(tick(self.database, as_of=self.now, sender=sender, support_worker=Mock())['sent'], 0)
        sender.assert_called_once()
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM bollinger_phone_notifications').fetchall(), before)
            self.assertEqual(db.execute('SELECT * FROM bollinger_live_events').fetchall(), original)
