"""Exercise real SQLite write/commit contention on isolated databases."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sqlite3,tempfile,time,unittest
from threading import Event
from unittest.mock import patch
from bollinger_tick_stream import RealtimeBollingerWorker,sqlite_busy
from live_market import MarketBar
from tests.test_bollinger_tick_stream import CANDLE,seed,trade

class IngestContentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'market.db';self.store,_=seed(self.db)

    def exercise_lock(self,reader):
        worker=RealtimeBollingerWorker(self.db,'iex',['AAPL']);seen=Event();second=Event()
        def observe(message,received):
            (seen if message['i']==1 else second).set()
            return dict(symbol='AAPL',source_timestamp=message['t'],received_at=received.isoformat(),
                signal={'side':'SUPERIOR'} if message['i']==1 else None), 'READY_NO_EXIT'
        try:
            with patch.object(worker.geometry,'observe',side_effect=observe):
                with closing(sqlite3.connect(self.db,timeout=1)) as lock:
                    lock.execute('BEGIN' if reader else 'BEGIN IMMEDIATE')
                    if reader:lock.execute('SELECT COUNT(*) FROM bollinger_tick_latest').fetchall()
                    worker.trade(trade(104.,datetime.now(timezone.utc),1))
                    self.assertTrue(seen.wait(.5))
                    time.sleep(.2) # The receiver now attempts a write/commit.
                    worker.trade(trade(100.,datetime.now(timezone.utc),2))
                    self.assertTrue(second.wait(.5),'SQLite contention must not hold the next trade for seconds')
                    self.assertFalse(worker.failed.is_set())
                    lock.rollback()
                worker.queue.join();deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    with closing(sqlite3.connect(self.db)) as db:
                        if db.execute('SELECT COUNT(*) FROM bollinger_tick_audit').fetchone()[0]==2:break
                    time.sleep(.02)
                else:self.fail('Both audit records must persist after contention ends')
        finally:worker.close()
        with closing(sqlite3.connect(self.db)) as db:
            rows=db.execute('SELECT message_json FROM bollinger_tick_audit ORDER BY id').fetchall()
            latest=json.loads(db.execute('SELECT payload_json FROM bollinger_tick_latest WHERE symbol=?',('AAPL',)).fetchone()[0])
        self.assertEqual([json.loads(r[0])['i'] for r in rows],[1,2])
        self.assertIsNone(latest['signal'],'A buffered breakout must not replace the later retraction')

    def test_writer_lock_does_not_hold_observe_and_keeps_all_audit(self):self.exercise_lock(False)
    def test_reader_blocking_commit_rolls_back_then_keeps_latest_retraction(self):self.exercise_lock(True)

    def test_slow_disk_commit_does_not_block_next_trade_and_retraction_is_final(self):
        worker=RealtimeBollingerWorker(self.db,'iex',['AAPL'])
        entered=Event();release=Event();second=Event();original=worker.repository.flush
        def slow(*args,**kwargs):
            entered.set();release.wait(3)
            return original(*args,**kwargs)
        def observe(message,received):
            if message['i']==2:second.set()
            return dict(symbol='AAPL',source_timestamp=message['t'],received_at=received.isoformat(),
                signal={'side':'SUPERIOR'} if message['i']==1 else None),'READY_NO_EXIT'
        try:
            with patch.object(worker.repository,'flush',side_effect=slow),patch.object(worker.geometry,'observe',side_effect=observe):
                worker.trade(trade(104.,datetime.now(timezone.utc),1))
                self.assertTrue(entered.wait(1))
                worker.trade(trade(100.,datetime.now(timezone.utc),2))
                self.assertTrue(second.wait(.5),'Slow filesystem commit must not stop trade evaluation')
                release.set();worker.queue.join()
        finally:release.set();worker.close()
        with closing(sqlite3.connect(self.db)) as db:
            rows=db.execute('SELECT message_json FROM bollinger_tick_audit ORDER BY id').fetchall()
            latest=json.loads(db.execute('SELECT payload_json FROM bollinger_tick_latest WHERE symbol=?',('AAPL',)).fetchone()[0])
        self.assertEqual([json.loads(r[0])['i'] for r in rows],[1,2])
        self.assertIsNone(latest['signal'])

    def test_writer_does_not_replace_evaluator_heartbeat_with_commit_time(self):
        from bollinger_tick_stream import TickPublisher,TickRepository
        failed=Event();repo=TickRepository(self.db);publisher=TickPublisher(repo,'iex',['AAPL'],failed)
        past=datetime.now(timezone.utc)-timedelta(seconds=30)
        try:publisher.submit({},[],state='CONECTADO',now=past)
        finally:publisher.close()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT heartbeat FROM bollinger_tick_runtime WHERE id=1').fetchone()[0],past.isoformat())

    def test_bar_bursts_batch_without_crossing_a_trade_and_keep_queue_accounting(self):
        worker=RealtimeBollingerWorker(self.db,'iex',['AAPL']);entered=Event();release=Event();sequence=[]
        original_status=worker.geometry.status;original_bars=worker.geometry.store.upsert_bars
        def status(state,stamp):entered.set();release.wait(2);original_status(state,stamp)
        def bars(values,**kwargs):sequence.append(('bars',[b.symbol for b in values]));return original_bars(values,**kwargs)
        def observe(message,received):sequence.append(('trade',message['i']));return None,'READY_NO_EXIT'
        try:
            with patch.object(worker.geometry,'status',side_effect=status),patch.object(worker.geometry.store,'upsert_bars',side_effect=bars),patch.object(worker.geometry,'observe',side_effect=observe):
                worker.status('CONECTADO');self.assertTrue(entered.wait(1))
                for symbol in ('AAPL','MSFT'):worker.bar(MarketBar(symbol,CANDLE,100,101,99,100,100),lambda b:None)
                worker.trade(trade(100.,datetime.now(timezone.utc),17))
                worker.bar(MarketBar('NVDA',CANDLE,100,101,99,100,100),lambda b:None)
                release.set();worker.queue.join()
                self.assertEqual(sequence,[('bars',['AAPL','MSFT']),('trade',17),('bars',['NVDA'])])
                self.assertFalse(worker.failed.is_set())
        finally:release.set();worker.close()

    def test_ordered_official_updates_to_same_minute_keep_final_ohlc(self):
        a=MarketBar('MSFT',CANDLE,100,101,99,100,100)
        b=MarketBar('MSFT',CANDLE,100,102,99,101,200)
        self.assertEqual(self.store.upsert_bars([a,b],provider='ALPACA',feed='iex'),2)
        frame=self.store.load_frame(symbol='MSFT',provider='ALPACA',feed='iex',start=CANDLE,end=CANDLE)
        self.assertEqual(len(frame),1);self.assertEqual(frame.iloc[0]['close'],101)
        self.assertEqual(frame.iloc[0]['volume'],200)

    def test_invalid_bar_rejects_entire_batch_before_any_write(self):
        a=MarketBar('MSFT',CANDLE,100,101,99,100,100)
        b=MarketBar('NVDA',CANDLE,100,99,98,100,100)
        with self.assertRaises(ValueError):self.store.upsert_bars([a,b],provider='ALPACA',feed='iex')
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM minute_bars WHERE symbol IN ('MSFT','NVDA')").fetchone()[0],0)

    def test_only_busy_and_locked_codes_are_retryable(self):
        for code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED,sqlite3.SQLITE_BUSY | 256):
            e=sqlite3.OperationalError('fixture');e.sqlite_errorcode=code;self.assertTrue(sqlite_busy(e))
        for code in (sqlite3.SQLITE_CORRUPT,sqlite3.SQLITE_IOERR,sqlite3.SQLITE_FULL):
            e=sqlite3.OperationalError('fixture');e.sqlite_errorcode=code;self.assertFalse(sqlite_busy(e))
        self.assertFalse(sqlite_busy(sqlite3.OperationalError('database is locked')))

    def test_pending_audit_overflow_fails_closed_instead_of_discarding_rows(self):
        worker=RealtimeBollingerWorker(self.db,'iex',['AAPL'])
        busy=sqlite3.OperationalError('fixture');busy.sqlite_errorcode=sqlite3.SQLITE_BUSY
        try:
            with patch('bollinger_tick_stream.MAX_PENDING_AUDIT',1),patch.object(worker.repository,'flush',side_effect=busy), \
                 patch.object(worker.geometry,'observe',return_value=(None,'READY_NO_EXIT')):
                worker.trade(trade(100.,datetime.now(timezone.utc),1))
                worker.trade(trade(100.,datetime.now(timezone.utc),2))
                self.assertTrue(worker.failed.wait(2))
                receipt=json.loads((self.db.parent/'fast_ingest_failure.json').read_text())
                self.assertEqual(receipt['error_type'],'BufferError')
        finally:worker.close()
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bollinger_tick_audit').fetchone()[0],2)

    def test_io_error_marks_worker_failed_and_does_not_log_raw_exception(self):
        worker=RealtimeBollingerWorker(self.db,'iex',['AAPL'])
        error=sqlite3.OperationalError('fixture-private-secret');error.sqlite_errorcode=sqlite3.SQLITE_IOERR
        try:
            with patch.object(worker.repository,'flush',side_effect=error) as flush:
                self.assertTrue(worker.failed.wait(2))
                time.sleep(.1)
                self.assertEqual(flush.call_count,1,'IOERR is fatal, not an automatic retry loop')
                text=(self.db.parent/'fast_ingest_failure.json').read_text()
                self.assertEqual(json.loads(text)['sqlite_errorcode'],sqlite3.SQLITE_IOERR)
                self.assertNotIn('fixture-private-secret',text)
        finally:worker.close()

    def test_exit_and_retraction_publish_urgently_even_with_long_routine_interval(self):
        worker=RealtimeBollingerWorker(self.db,'iex',['AAPL'])
        def observe(message,received):
            return dict(symbol='AAPL',source_timestamp=message['t'],received_at=received.isoformat(),
                signal=dict(side='SUPERIOR',candle=CANDLE.isoformat()) if message['i']==1 else None),'READY_NO_EXIT'
        try:
            with patch('bollinger_tick_stream.ROUTINE_FLUSH_SECONDS',60),patch.object(worker.geometry,'observe',side_effect=observe):
                for identity in (1,2):
                    worker.trade(trade(104. if identity==1 else 100.,datetime.now(timezone.utc),identity))
                    deadline=time.monotonic()+1
                    while time.monotonic()<deadline:
                        with closing(sqlite3.connect(self.db)) as db:
                            row=db.execute('SELECT payload_json FROM bollinger_tick_latest WHERE symbol=?',('AAPL',)).fetchone()
                        if row and bool(json.loads(row[0]).get('signal'))==(identity==1):break
                        time.sleep(.01)
                    else:self.fail('Signal transition must not wait for routine batching')
        finally:worker.close()

if __name__=='__main__':unittest.main()
