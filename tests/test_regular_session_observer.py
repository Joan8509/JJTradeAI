"""Passive evidence must never turn stale, incomplete or future data into readiness."""
from contextlib import closing
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bollinger_tick_stream import TickRepository
from scripts.observe_regular_session import (observe, add_stability,
                                             original_notice_evidence, observation_gate_valid)
from tests.test_bollinger_tick_stream import seed, CANDLE, trade


class RegularSessionObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'market.db'
        seed(self.database)
        self.repo = TickRepository(self.database)
        self.now = CANDLE+timedelta(minutes=2)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE bollinger_phone_notifications(event_key TEXT PRIMARY KEY,state TEXT)')
            db.executemany('INSERT INTO bollinger_phone_notifications VALUES(?,?)',
                           [(str(n), 'ENVIO_NO_CONFIRMADO' if n < 16 else 'ENVIADO') for n in range(154)])

    def flush(self, source=None, reason='READY_NO_EXIT'):
        stamp = source or self.now-timedelta(milliseconds=200)
        received = self.now-timedelta(milliseconds=100)
        payload = dict(source_timestamp=stamp.isoformat(), received_at=received.isoformat(),
                       checked_at=self.now.isoformat(), reason=reason)
        audit = [(received.isoformat(), 'AAPL', stamp.isoformat(), reason,
                  json.dumps(trade(100, stamp)))]
        self.repo.flush({'AAPL': payload}, audit, state='CONECTADO', feed='iex',
                        symbols=['AAPL'], now=self.now)

    def test_read_only_snapshot_has_latency_and_persisted_trade_and_official_references(self):
        self.flush()
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        result = observe(self.database, self.now)
        after = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        info = result['symbols']['AAPL']
        self.assertEqual(info['fresh_eligible_trades_60s'], 1)
        self.assertAlmostEqual(info['latency_ms']['max'], 100)
        self.assertAlmostEqual(info['latest_processing_delay_ms'], 100)
        self.assertTrue(info['history_references_present'])
        self.assertTrue(info['fresh_geometry_now'])
        self.assertEqual(info['last_trade_persisted_by'], self.now.isoformat())
        self.assertNotIn('message_json', json.dumps(result))
        self.assertNotIn('event_key', json.dumps(result))

    def test_missing_period_blocks_references_even_with_plentiful_older_rows(self):
        self.flush(reason='WAITING_FOR_OPEN_OR_HISTORY')
        missing = CANDLE.replace(day=12, hour=18, minute=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp>=? AND timestamp<?',
                       (missing.isoformat(), (missing+timedelta(minutes=15)).isoformat()))
        info = observe(self.database, self.now)['symbols']['AAPL']
        self.assertIn(missing.isoformat(), info['missing_15m_periods'])
        self.assertFalse(info['history_references_present'])
        self.assertEqual(info['fresh_eligible_trades_60s'], 1)
        self.assertFalse(info['fresh_geometry_now'])

    def test_future_or_stale_source_never_proves_freshness_even_if_reason_is_ready(self):
        for stamp in (self.now+timedelta(seconds=1), self.now-timedelta(seconds=4)):
            with self.subTest(stamp=stamp):
                with closing(sqlite3.connect(self.database)) as db, db:
                    db.execute('DELETE FROM bollinger_tick_audit')
                self.flush(source=stamp)
                info = observe(self.database, self.now)['symbols']['AAPL']
                self.assertEqual(info['fresh_eligible_trades_60s'], 0)
                self.assertFalse(info['fresh_geometry_now'])

    def test_production_clock_after_snapshot_avoids_false_future_heartbeat(self):
        self.flush()
        started = self.now-timedelta(milliseconds=10)
        checked = self.now+timedelta(milliseconds=10)
        observed = observe(self.database, started, clock=lambda: checked)
        self.assertAlmostEqual(observed['runtime']['heartbeat_age_seconds'], .01)
        self.repo.flush({}, [], state='CONECTADO', feed='iex', symbols=['AAPL'],
                        now=checked+timedelta(seconds=1))
        actual_future = observe(self.database, started, clock=lambda: checked)
        self.assertLess(actual_future['runtime']['heartbeat_age_seconds'], 0)

    def test_preopen_and_weekend_do_not_use_another_sessions_readiness(self):
        self.flush()
        preopen = observe(self.database, CANDLE.replace(hour=13, minute=25))
        weekend = observe(self.database, CANDLE.replace(day=17))
        self.assertEqual(preopen['status'], 'BEFORE_REGULAR_SESSION')
        self.assertEqual(weekend['status'], 'NO_OFFICIAL_SESSION')
        self.assertFalse(preopen['market_open'])
        self.assertEqual(preopen['symbols'], {})

    def sample(self, seconds=0, **changes):
        result = {'utc': (self.now+timedelta(seconds=seconds)).isoformat(),
                  'session_date': self.now.date().isoformat(), 'market_open': True,
                  'dedup_originals_unchanged': True, 'observation_available': True,
                  'runtime': {'state': 'CONECTADO', 'feed': 'iex', 'heartbeat_age_seconds': .1},
                  'symbols': {'AAPL': {'fresh_eligible_trades_60s': 1,
                                       'history_references_present': True, 'fresh_geometry_now': True}}}
        result.update(changes)
        return result

    def test_stability_requires_120s_and_never_activates_radar(self):
        state = add_stability(self.sample(), {})
        state = add_stability(self.sample(60), state)
        self.assertFalse(state['symbols']['AAPL']['reception_stable_120s'])
        state = add_stability(self.sample(120), state)
        self.assertTrue(state['symbols']['AAPL']['review_candidate_now'])
        self.assertFalse(state['radar_activation_supported'])
        self.assertEqual(state['messages_sent'], 0)
        self.assertFalse(state['orders_supported'])

    def test_unavailable_observation_schedule_gap_and_changed_dedup_reset_stability(self):
        first = add_stability(self.sample(), {})
        unavailable = add_stability(self.sample(60, observation_available=False, symbols={}), first)
        self.assertEqual(add_stability(self.sample(120), unavailable)['symbols']['AAPL']['reception_observed_seconds'], 0)
        self.assertEqual(add_stability(self.sample(120), first)['symbols']['AAPL']['reception_observed_seconds'], 0)
        altered = add_stability(self.sample(60, dedup_originals_unchanged=False), first)
        self.assertIsNone(altered['symbols']['AAPL']['reception_observed_since'])

    def test_new_notices_preserve_originals_but_changed_or_missing_originals_fail(self):
        with closing(sqlite3.connect(self.database)) as db:
            rows = db.execute('SELECT * FROM bollinger_phone_notifications ORDER BY event_key').fetchall()
        expected = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        baseline = Path(self.temp.name)/'originals.json'
        baseline.write_text(json.dumps({'format': 1, 'row_hashes': [
            hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest() for row in rows]}))
        extra = ('new_signal', 'ENVIADO')
        with patch('scripts.observe_regular_session.ORIGINAL_DIGEST', expected):
            evidence = original_notice_evidence(sorted(rows+[extra]), baseline)
            self.assertTrue(evidence['unchanged'])
            self.assertEqual(evidence['count'], 154)
            self.assertFalse(original_notice_evidence(rows[1:]+[extra], baseline)['unchanged'])
            changed = [(rows[0][0], 'ALTERED')]+rows[1:]+[extra]
            self.assertFalse(original_notice_evidence(changed, baseline)['unchanged'])
            self.assertFalse(original_notice_evidence(rows+[extra], baseline.with_suffix('.absent'))['unchanged'])

    def test_observation_accepts_authorized_radar_without_enabling_orders(self):
        self.assertTrue(observation_gate_valid({'enabled_roles': ['collector'], 'orders_enabled': False}))
        self.assertTrue(observation_gate_valid({'enabled_roles': ['collector', 'radar'], 'orders_enabled': False}))
        for roles, orders in ((['radar'], False), (['collector', 'orders'], False),
                              (['collector', 'radar'], True), (['collector', 'collector'], False)):
            self.assertFalse(observation_gate_valid({'enabled_roles': roles, 'orders_enabled': orders}))


if __name__ == '__main__':
    unittest.main()
