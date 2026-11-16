"""First-opportunity time is identical with the selective SQLite index."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sqlite3,tempfile
from unittest import TestCase
from bollinger_tick_stream import FIRST_EXIT_INDEX_SQL,TickRepository
from manual_trade_service import detector_first_source


class FirstExitIndexTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'isolated.db'
        TickRepository(self.path)
        self.at=datetime(2026,11,16,14,30,tzinfo=timezone.utc)
        self.tick=dict(symbol='AAPL',version='v7_ruptura_temprana_30s',
            signal=dict(candle=self.at.isoformat(),side='SUPERIOR'))
        with closing(sqlite3.connect(self.path)) as db,db:
            for delta,symbol,reason,side in [(-1,'OTHER','READY',None),(0.1,'OTHER','EXIT','SUPERIOR'),
                    (1,'AAPL','EXIT','INFERIOR'),(3,'AAPL','EXIT','SUPERIOR'),
                    (4,'AAPL','READY',None),(9,'AAPL','EXIT','SUPERIOR')]:
                stamp=(self.at+timedelta(seconds=delta)).isoformat()
                raw=json.dumps({'_jjtrade':{'geometry':{'side':side}}})
                db.execute('INSERT INTO bollinger_tick_audit(received_at,symbol,source_timestamp,reason,message_json) VALUES(?,?,?,?,?)',
                    (stamp,symbol,stamp,reason,raw))

    def test_index_preserves_first_side_symbol_and_candle_without_renewing_clock(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DROP INDEX idx_bollinger_tick_exit_symbol_time')
            previous=detector_first_source(db,self.path,self.tick,cache={})
            db.execute(FIRST_EXIT_INDEX_SQL)
            current=detector_first_source(db,self.path,self.tick,cache={})
            self.assertEqual(previous,current)
            self.assertEqual(current,(self.at+timedelta(seconds=3)).isoformat())

    def test_first_exit_query_uses_symbol_index_and_index_creation_is_idempotent(self):
        with closing(sqlite3.connect(self.path)) as db:
            before=db.execute('SELECT * FROM bollinger_tick_audit ORDER BY id').fetchall()
            db.execute(FIRST_EXIT_INDEX_SQL);db.execute(FIRST_EXIT_INDEX_SQL)
            plan=db.execute("EXPLAIN QUERY PLAN SELECT source_timestamp FROM bollinger_tick_audit "
                "WHERE received_at>=? AND received_at<? AND symbol=? AND reason='EXIT' "
                "AND json_extract(message_json,'$._jjtrade.geometry.side')=? ORDER BY received_at LIMIT 1",
                (self.at.isoformat(),(self.at+timedelta(minutes=15)).isoformat(),'AAPL','SUPERIOR')).fetchall()
            self.assertTrue(any('idx_bollinger_tick_exit_symbol_time' in r[-1] for r in plan))
            self.assertEqual(db.execute('SELECT * FROM bollinger_tick_audit ORDER BY id').fetchall(),before)

    def test_index_keeps_missing_evidence_fail_closed(self):
        with closing(sqlite3.connect(self.path)) as db:
            tick=dict(self.tick,symbol='MISSING')
            self.assertIsNone(detector_first_source(db,self.path,tick,cache={}))
            db.execute('DELETE FROM bollinger_tick_audit WHERE received_at<?',(self.at.isoformat(),))
            self.assertIsNone(detector_first_source(db,self.path,self.tick,cache={}))
