"""Render the actual dashboard on isolated data; no services, APIs or notices."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from streamlit.testing.v1 import AppTest
from bollinger_dashboard_data import read_snapshot


def dashboard_page(database, status, fixed_now):
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import patch
    import app
    health = {'state': 'DATOS_APTOS_OBSERVADOS', 'sample_count': 1,
              'future_count': 0, 'max_future_ms': 0}
    now = datetime.fromisoformat(fixed_now)
    with patch.object(app, 'DEFAULT_MARKET_DATABASE', Path(database)), \
         patch.object(app, '_render_scanner_controls'), \
         patch.object(app, 'read_instance_status', return_value={'active': True}), \
         patch.object(app, 'load_watchlist', return_value={'symbols': ['AAPL', 'QQQ']}), \
         patch('bollinger_phone_worker.STATUS_PATH', Path(status)), \
         patch('radar_health.fast_feed_health', return_value=health), \
         patch.object(app, 'datetime', wraps=datetime) as clock, \
         patch('socket.socket.connect', side_effect=AssertionError('No network in UI test')):
        clock.now.return_value = now
        app.render_bollinger_dashboard()


class BollingerDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.database = self.directory/'isolated.db'
        self.status = self.directory/'radar.json'
        self.now = datetime(2026, 10, 16, 19, 1, 2, tzinfo=timezone.utc)
        self.version = 'v4_apertura_dentro_sin_veto_previo'
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('CREATE TABLE market_sessions(session_date TEXT PRIMARY KEY,opens_at TEXT,closes_at TEXT);'
                'CREATE TABLE bollinger_radar_state(symbol TEXT PRIMARY KEY,payload_json TEXT);'
                'CREATE TABLE bollinger_live_events(detected_at TEXT,payload_json TEXT);')
            db.execute('INSERT INTO market_sessions VALUES(?,?,?)',
                       ('2026-10-16', '2026-10-16T13:30:00+00:00', '2026-10-16T20:00:00+00:00'))
        self.status.write_text(json.dumps({'state': 'VIGILANDO', 'heartbeat': self.now.isoformat(),
                                           'telegram_readiness': 'LISTO_LOCAL'}))

    def seed(self, *, side='SUPERIOR', age=1, signal=True, reason='EXIT', context=False):
        stamp = self.now-timedelta(seconds=age)
        candidate = {'side': side, 'price': 104.25, 'candle': '2026-10-16T19:00:00+00:00'}
        state = {'symbol': 'AAPL', 'provider': 'ALPACA', 'feed': 'iex', 'version': self.version,
                 'source_kind': 'TRADE', 'source_timestamp': stamp.isoformat(),
                 'data_reason': reason, 'signal': candidate if signal else None}
        event = {**candidate, 'symbol': 'AAPL', 'provider': 'ALPACA', 'feed': 'iex',
                 'version': self.version, 'detected_at': (self.now-timedelta(seconds=20)).isoformat()}
        if context:
            event['ma_context'] = {'state': 'DESCRIPTIVO', 'frames': [], 'levels': [], 'complete': False}
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT OR REPLACE INTO bollinger_radar_state VALUES(?,?)', ('AAPL', json.dumps(state)))
            db.execute('DELETE FROM bollinger_live_events')
            db.execute('INSERT INTO bollinger_live_events VALUES(?,?)', (event['detected_at'], json.dumps(event)))

    def render(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        page = AppTest.from_function(dashboard_page,
            args=(str(self.database), str(self.status), self.now.isoformat())).run(timeout=20)
        self.assertEqual(len(page.exception), 0, str(page.exception))
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).hexdigest())
        return page

    def test_call_and_put_show_company_price_candle_reference_and_review_button(self):
        for side, label in [('SUPERIOR', 'ALCISTA · CALL'), ('INFERIOR', 'BAJISTA · PUT')]:
            with self.subTest(side=side):
                self.seed(side=side)
                page = self.render()
                text = '\n'.join(item.value for item in page.markdown)
                captions = '\n'.join(item.value for item in page.caption)
                self.assertIn('AAPL · '+label, text)
                self.assertIn('104.25', text)
                self.assertIn('Vela de 15 minutos', captions)
                self.assertIn('No es el bid/ask', captions)
                self.assertIn('$0.35 – $0.90 USD', captions)
                self.assertIn('Operar', [b.label for b in page.button])
                self.assertTrue(next(e for e in page.expander if 'historial' in e.label).proto.expanded)

    def test_stale_future_and_retracted_signals_leave_history_without_active_card(self):
        for age, signal in [(4, True), (-1, True), (1, False)]:
            with self.subTest(age=age, signal=signal):
                self.seed(age=age, signal=signal)
                page = self.render()
                self.assertNotIn('Operar', [b.label for b in page.button])
                self.assertTrue(any('AAPL' in str(table.value) for table in page.dataframe))

    def test_context_of_original_detection_is_labeled_and_does_not_create_signal(self):
        self.seed(context=True)
        page = self.render()
        self.assertTrue(any('Contexto de la detección guardada' in c.value for c in page.caption))
        self.seed(signal=False, context=True, reason='WAITING_FOR_OPEN_OR_HISTORY')
        page = self.render()
        self.assertNotIn('Operar', [b.label for b in page.button])
        self.assertTrue(any('Esperando historial' in str(t.value) for t in page.dataframe))

    def test_closed_market_has_history_without_current_entry(self):
        self.seed()
        self.now = self.now.replace(hour=21)
        page = self.render()
        self.assertNotIn('Operar', [b.label for b in page.button])
        self.assertTrue(any('espera la sesión regular' in item.value for item in page.info))

    def test_snapshot_does_not_create_missing_database(self):
        missing = self.directory/'absent.db'
        with self.assertRaises(sqlite3.OperationalError):
            read_snapshot(missing, self.now.date())
        self.assertFalse(missing.exists())
