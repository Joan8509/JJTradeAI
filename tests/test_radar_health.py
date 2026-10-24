from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from radar_health import fast_feed_health

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)


class RadarHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'market.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('CREATE TABLE bollinger_tick_runtime(id INTEGER,state TEXT,heartbeat TEXT);'
                             'CREATE TABLE bollinger_tick_audit(received_at TEXT,source_timestamp TEXT,reason TEXT);')
            db.execute('INSERT INTO bollinger_tick_runtime VALUES(1,?,?)',('CONECTADO', NOW.isoformat()))

    def seed(self, reason, ahead_ms, *, received=NOW, n=6):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT INTO bollinger_tick_audit VALUES(?,?,?)',
                           [(received.isoformat(), (received+timedelta(milliseconds=ahead_ms)).isoformat(), reason)]*n)

    def test_connected_heartbeat_does_not_hide_future_price_rejections(self):
        self.seed('DISCONNECTED_OR_STALE',1200)
        report=fast_feed_health(self.path,now=NOW)
        self.assertEqual(report['state'],'REVISAR_RELOJ')
        self.assertEqual(report['future_count'],6)
        self.assertEqual(report['max_future_ms'],1200)

    def test_delay_is_not_reported_as_clock_ahead(self):
        self.seed('DISCONNECTED_OR_STALE',-4000)
        report=fast_feed_health(self.path,now=NOW)
        self.assertEqual(report['state'],'RECHAZOS_DE_FRESCURA')
        self.assertEqual(report['future_count'],0)

    def test_old_problem_expires_and_excluded_sales_do_not_mask_ready_data(self):
        self.seed('DISCONNECTED_OR_STALE',1200,received=NOW-timedelta(minutes=2))
        self.seed('EXCLUDED_CONDITION',1200)
        self.seed('READY_NO_EXIT',-40,n=1)
        report=fast_feed_health(self.path,now=NOW)
        self.assertEqual(report['state'],'DATOS_APTOS_OBSERVADOS')
        self.assertEqual(report['future_count'],0)

    def test_no_observations_is_not_healthy_and_does_not_create_database(self):
        self.assertEqual(fast_feed_health(self.path,now=NOW)['state'],'SIN_EVIDENCIA')
        missing=Path(self.temp.name)/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):
            fast_feed_health(missing,now=NOW)
        self.assertFalse(missing.exists())

    def test_stale_and_future_heartbeat_are_distinct(self):
        self.assertEqual(fast_feed_health(self.path,now=NOW+timedelta(seconds=4))['state'],'HEARTBEAT_ATRASADO')
        self.assertEqual(fast_feed_health(self.path,now=NOW-timedelta(seconds=1))['state'],'HEARTBEAT_FUTURO')

    def test_future_records_after_clock_correction_do_not_poison_sample(self):
        self.seed('DISCONNECTED_OR_STALE',1200,received=NOW+timedelta(minutes=2))
        self.seed('EXIT',-50,n=1)
        self.assertEqual(fast_feed_health(self.path,now=NOW)['state'],'DATOS_APTOS_OBSERVADOS')


if __name__ == '__main__':
    unittest.main()
