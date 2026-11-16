from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
from unittest import TestCase
from unittest.mock import patch
from threading import Thread,Barrier
import sqlite3,json,hashlib
from real_entry_state import RealEntryStateReader
from manual_trade_service import read_manual_state,current_manual_signal,ManualDataError
from tests import test_manual_trade_service as f

def build(path):
    state=f.state_fixture()
    with closing(sqlite3.connect(path)) as db,db:
        db.executescript('PRAGMA journal_mode=WAL;'
            'CREATE TABLE market_sessions(session_date TEXT PRIMARY KEY,opens_at TEXT,closes_at TEXT);'
            'CREATE TABLE bollinger_tick_runtime(id INTEGER PRIMARY KEY,state TEXT,heartbeat TEXT,feed TEXT,symbols_json TEXT);'
            'CREATE TABLE bollinger_tick_latest(symbol TEXT PRIMARY KEY,payload_json TEXT);'
            'CREATE TABLE bollinger_radar_state(symbol TEXT PRIMARY KEY,payload_json TEXT);'
            'CREATE TABLE bollinger_tick_audit(received_at TEXT,source_timestamp TEXT,symbol TEXT,reason TEXT,message_json TEXT);'
            'CREATE INDEX first_exit ON bollinger_tick_audit(symbol,received_at) WHERE reason=\'EXIT\';')
        db.execute('INSERT INTO market_sessions VALUES(?,?,?)',(f.NOW.date().isoformat(),*state['session']))
        db.execute('INSERT INTO bollinger_tick_runtime VALUES(1,?,?,?,?)',('CONECTADO',f.NOW.isoformat(),'iex','["AMZN"]'))
        db.execute('INSERT INTO bollinger_tick_latest VALUES(?,?)',('AMZN',json.dumps(state['tick'])))
        db.execute('INSERT INTO bollinger_radar_state VALUES(?,?)',('AMZN',json.dumps(state['radar'])))
        db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',('2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00','OLD','READY_NO_EXIT','{}'))
        db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',(f.NOW.isoformat(),f.NOW.isoformat(),'AMZN','EXIT',json.dumps({'_jjtrade':{'geometry':{'side':state['tick']['signal']['side']}}})))
    return state

class RealEntryStateTests(TestCase):
    def test_reuses_connection_but_returns_identical_authoritative_document(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.db';build(path)
            expected=read_manual_state(path,'AMZN',f.NOW.date());expected['radar']=None
            reader=RealEntryStateReader(path,clock=lambda:f.NOW)
            try:
                with patch('real_entry_state.sqlite3.connect',wraps=sqlite3.connect) as connect:
                    one=reader('AMZN');two=reader('AMZN');self.assertEqual(connect.call_count,1)
                self.assertEqual(one,expected);self.assertEqual(two,expected)
                self.assertIsNot(one['tick'],two['tick'])
                self.assertFalse(reader._local.db.in_transaction)
                self.assertEqual(current_manual_signal(one,'AMZN',f.NOW),one['tick'])
                with self.assertRaises(sqlite3.OperationalError):reader._local.db.execute('DELETE FROM bollinger_tick_latest')
            finally:reader.close()

    def test_new_commits_and_retracted_signals_are_seen_without_snapshot_cache(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.db';build(path);reader=RealEntryStateReader(path,clock=lambda:f.NOW)
            try:
                first=reader('AMZN');tick=first['tick']|dict(reason='READY_NO_EXIT',signal=None)
                with closing(sqlite3.connect(path)) as db,db:
                    db.execute('UPDATE bollinger_tick_latest SET payload_json=?',(json.dumps(tick),))
                self.assertIsNone(reader('AMZN')['tick']['signal'])
                with self.assertRaisesRegex(ManualDataError,'NO_CURRENT_SIGNAL'):current_manual_signal(reader('AMZN'),'AMZN',f.NOW)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0],0)
            finally:reader.close()

    def test_invalid_json_discards_connection_without_replaying_last_good(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.db';build(path);reader=RealEntryStateReader(path,clock=lambda:f.NOW)
            try:
                old=reader('AMZN');first_db=reader._local.db
                with closing(sqlite3.connect(path)) as db,db:db.execute("UPDATE bollinger_tick_latest SET payload_json='invalid'")
                with self.assertRaisesRegex(ManualDataError,'SIGNAL_STATE_UNAVAILABLE'):reader('AMZN')
                self.assertIsNone(reader._local.db)
                with closing(sqlite3.connect(path)) as db,db:db.execute('UPDATE bollinger_tick_latest SET payload_json=?',(json.dumps(old['tick']),))
                self.assertEqual(reader('AMZN')['tick'],old['tick']);self.assertIsNot(reader._local.db,first_db)
            finally:reader.close()

    def test_auxiliary_radar_is_not_an_entry_gate_but_disconnect_still_blocks(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.db';build(path);reader=RealEntryStateReader(path,clock=lambda:f.NOW)
            try:
                with closing(sqlite3.connect(path)) as db,db:db.execute("UPDATE bollinger_radar_state SET payload_json='invalid'")
                self.assertEqual(current_manual_signal(reader('AMZN'),'AMZN',f.NOW)['reason'],'EXIT')
                with closing(sqlite3.connect(path)) as db,db:db.execute("UPDATE bollinger_tick_runtime SET state='DESCONECTADO'")
                with self.assertRaisesRegex(ManualDataError,'COLLECTOR_NOT_CURRENT'):
                    current_manual_signal(reader('AMZN'),'AMZN',f.NOW)
            finally:reader.close()

    def test_missing_database_is_not_created_and_threads_do_not_share_connections(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing.db';reader=RealEntryStateReader(path,clock=lambda:f.NOW)
            with self.assertRaises(ManualDataError):reader('AMZN')
            self.assertFalse(path.exists());build(path)
            barrier=Barrier(2);connections=[];errors=[]
            def run():
                try:reader('AMZN');connections.append(reader._local.db);barrier.wait(timeout=2)
                except Exception as error:errors.append(type(error).__name__)
                finally:reader.close()
            ts=[Thread(target=run) for _ in range(2)]
            for t in ts:t.start()
            for t in ts:t.join(3)
            self.assertEqual(errors,[]);self.assertEqual(len(connections),2);self.assertIsNot(connections[0],connections[1])
