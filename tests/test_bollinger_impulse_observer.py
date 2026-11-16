import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from bollinger_impulse_observer import capture, open_archive, open_source, trailing_velocity
from scripts.build_impulse_study import evaluate, epoch


class ObserverTests(unittest.TestCase):
    def test_readonly_capture_cursor_gap_and_dedup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.db'
            src = sqlite3.connect(path)
            src.executescript('CREATE TABLE bollinger_tick_audit(id INTEGER PRIMARY KEY,received_at TEXT,symbol TEXT,source_timestamp TEXT,reason TEXT,message_json TEXT);'
                              'CREATE TABLE bollinger_live_events(event_key TEXT,detected_at TEXT,payload_json TEXT);')
            msg = json.dumps({'_jjtrade': {'geometry': {'price': 10}}})
            src.executemany('INSERT INTO bollinger_tick_audit VALUES (?,?,?,?,?,?)',
                            [(1,'a','X','a','EXIT',msg),(2,'b','X','b','EXCLUDED_CONDITION','{}')])
            src.execute("INSERT INTO bollinger_live_events VALUES ('key','a','{}')")
            src.commit()
            archive = open_archive(Path(folder) / 'archive.db')
            self.assertEqual(capture(path,archive)['preserved'],1)
            self.assertEqual(capture(path,archive)['scanned'],0)
            self.assertEqual(archive.execute('SELECT count(*) FROM events').fetchone()[0],1)
            src.execute('INSERT INTO bollinger_tick_audit VALUES (?,?,?,?,?,?)',(5,'c','X','c','READY_NO_EXIT',msg))
            src.commit()
            self.assertTrue(capture(path,archive)['retention_gap'])
            with closing(open_source(path)) as ro:
                with self.assertRaises(sqlite3.OperationalError):
                    ro.execute('DELETE FROM bollinger_tick_audit')
            self.assertEqual(src.execute('SELECT count(*) FROM bollinger_tick_audit').fetchone()[0],3)
            src.close(); archive.close()

    def test_velocity_cannot_use_future_or_late_received_ticks(self):
        ticks = [{'time': 7.,'received':7.,'price':100.},
                 {'time':10.,'received':10.,'price':102.},
                 {'time':10.,'received':11.,'price':150.},
                 {'time':11.,'received':10.,'price':160.}]
        self.assertEqual(trailing_velocity(ticks,10.,10.,3.,1,4),.5)
        self.assertEqual(trailing_velocity(ticks,10.,10.,3.,-1,4),-.5)
        self.assertIsNone(trailing_velocity(ticks,10.,10.,5.,1,4))

    def test_playback_missing_coverage_is_not_a_loss_and_future_not_feature(self):
        event={'symbol':'X','version':'v5_apertura_dentro_bandas_actuales',
               'source_timestamp':'2026-11-06T14:30:10+00:00',
               'detected_at':'2026-11-06T14:30:10.100+00:00','side':'SUPERIOR','price':102,
               'band_expansion':{'previous_upper':101,'previous_lower':97,'upper':101.5,
                                 'lower':96.5,'upper_pct':12.5,'lower_pct':12.5,'required_pct':3}}
        t=epoch(event['source_timestamp'])
        ticks=[{'time':t-3,'received':t-3,'price':100},
               {'time':t,'received':t,'price':102},
               {'time':t+10,'received':t+10,'price':103}]
        result=evaluate(event,ticks)
        self.assertEqual(result['features_at_decision']['velocity_3s_prior_width_fraction'],.5)
        self.assertIsNone(result['future_underlying_labels']['5']['directional_return_pct'])
        self.assertGreater(result['future_underlying_labels']['10']['directional_return_pct'],0)
        self.assertIsNone(result['path_30s']['observed_mfe_pct'])


if __name__ == '__main__':
    unittest.main()
