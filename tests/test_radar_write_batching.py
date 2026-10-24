"""Database contention regression: preserve state/events with fewer transactions."""
from contextlib import contextmanager, closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch

import bollinger_phone_worker as phone
from bollinger_tick_stream import TickRepository,TickGeometry
from tests.test_bollinger_tick_stream import CANDLE,seed,trade


class RadarWriteBatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.database=Path(self.temp.name)/'market.db';seed(self.database)
        self.now=CANDLE+timedelta(seconds=2)
        self.repository=TickRepository(self.database)

    @contextmanager
    def traced(self):
        original=phone._database;transactions=[]
        @contextmanager
        def opened(path):
            statements=[]
            with original(path) as db:
                db.set_trace_callback(statements.append)
                yield db
            transactions.append(statements)
        with patch.object(phone,'_database',opened):yield transactions

    def test_18_quiet_symbols_publish_all_states_in_one_short_transaction(self):
        symbols=['AAPL']+['TEST'+str(i) for i in range(17)]
        snapshots={s:dict(symbol=s,provider='ALPACA',feed='iex',source_kind='TRADE',
            source_timestamp=self.now.isoformat(),received_at=self.now.isoformat(),
            opening=100.,signal=None,reason='READY_NO_EXIT') for s in symbols}
        self.repository.flush(snapshots,[],state='CONECTADO',feed='iex',symbols=symbols,now=self.now)
        sender=Mock()
        with self.traced() as transactions,patch.object(phone,'enabled',return_value=False), \
             patch.object(phone,'connection',return_value=None),patch.object(phone,'load_watchlist',return_value={'symbols':symbols}):
            result=phone.tick(self.database,as_of=self.now,sender=sender,support_worker=Mock())
        writes=[t for t in transactions if any('INSERT INTO bollinger_radar_state' in sql for sql in t)]
        self.assertEqual(len(writes),1)
        self.assertEqual(sum('INSERT INTO bollinger_radar_state' in sql for sql in writes[0]),18)
        self.assertIn('COMMIT',writes[0])
        self.assertEqual(result['observed'],18);sender.assert_not_called()
        with closing(sqlite3.connect(self.database)) as db:
            rows=db.execute('SELECT symbol,payload_json FROM bollinger_radar_state ORDER BY symbol').fetchall()
        self.assertEqual({r[0] for r in rows},set(symbols))
        self.assertTrue(all(json.loads(r[1])['status']=='SIN_SALIDA_NUEVA' for r in rows))

    def test_repeated_exit_keeps_original_event_without_rewriting_or_resending(self):
        geometry=TickGeometry(self.database,'iex',now=lambda:self.now)
        geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        geometry.observe(trade(100.,self.now-timedelta(seconds=1),1),self.now-timedelta(seconds=1))
        snapshot,_=geometry.observe(trade(104.,self.now,2),self.now)
        self.repository.flush({'AAPL':snapshot},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=self.now)
        sender=Mock(return_value={'message_id':1,'date':self.now.timestamp()})
        with patch.object(phone,'enabled',return_value=True),patch.object(phone,'connection',return_value={'chat_id':'fixture'}), \
             patch.object(phone,'load_watchlist',return_value={'symbols':['AAPL']}),patch('manual_trade_links.signal_link',return_value=None):
            self.assertEqual(phone.tick(self.database,as_of=self.now,sender=sender,support_worker=Mock())['sent'],1)
            with closing(sqlite3.connect(self.database)) as db:
                original=db.execute('SELECT * FROM bollinger_live_events').fetchall()
            with self.traced() as transactions:
                self.assertEqual(phone.tick(self.database,as_of=self.now+timedelta(milliseconds=100),sender=sender,support_worker=Mock())['sent'],0)
        self.assertFalse(any('INSERT OR IGNORE INTO bollinger_live_events' in sql for t in transactions for sql in t))
        sender.assert_called_once()
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM bollinger_live_events').fetchall(),original)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bollinger_phone_notifications').fetchone()[0],1)

    def test_unchanged_projection_is_not_rewritten_just_to_refresh_check_clock(self):
        with closing(sqlite3.connect(self.database)) as db,db:
            db.execute('CREATE TABLE bollinger_radar_state(symbol TEXT PRIMARY KEY,source_timestamp TEXT,payload_json TEXT)')
            db.execute('CREATE TABLE updates(id INTEGER)')
            db.execute('CREATE TRIGGER radar_updates AFTER UPDATE ON bollinger_radar_state BEGIN INSERT INTO updates VALUES(1); END')
        def rows(checked,stamp='2026-10-13T14:00:02+00:00',status='SIN_SALIDA_NUEVA'):
            return [('AAPL',stamp,json.dumps(dict(checked_at=checked,source_timestamp=stamp,status=status)))]
        phone._save_radar_states(self.database,rows('first'))
        phone._save_radar_states(self.database,rows('second'))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM updates').fetchone()[0],0)
        phone._save_radar_states(self.database,rows('third',status='SALIDA_DETECTADA'))
        phone._save_radar_states(self.database,rows('fourth',stamp='2026-10-13T14:00:03+00:00'))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM updates').fetchone()[0],2)


if __name__=='__main__':unittest.main()
