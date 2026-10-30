"""Slow canonical storage cannot queue trades or authorize old references."""
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import sqlite3
from unittest import TestCase
from unittest.mock import Mock

from bollinger_tick_stream import RealtimeBollingerWorker
from live_market import MarketBar
from tests.test_bollinger_tick_stream import CANDLE,seed,trade


class AsyncBarStorageTests(TestCase):
    def harness(self):
        folder=TemporaryDirectory();self.addCleanup(folder.cleanup)
        database=Path(folder.name)/'market.db';seed(database)
        worker=RealtimeBollingerWorker(database,'iex',['AAPL'])
        self.addCleanup(worker.close)
        worker.state='CONECTADO'
        worker.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        self.now=CANDLE+timedelta(seconds=1);worker.geometry.now=lambda:self.now
        observations=[];done=Event();original=worker.geometry.observe
        def observe(message,received,**kwargs):
            value=original(message,received,**kwargs)
            observations.append(value);done.set();return value
        worker.geometry.observe=observe
        return worker,observations,done

    def send(self,worker,done,price,offset,identifier):
        self.now=CANDLE+timedelta(seconds=offset);done.clear()
        worker.queue.put(('trade',trade(price,self.now,identifier),self.now,None))
        self.assertTrue(done.wait(2),'trade processing waited for storage')

    def block_storage(self,worker):
        entered=Event();release=Event();original=worker.geometry.store.upsert_bars
        def persist(*args,**kwargs):
            entered.set();release.wait(4);return original(*args,**kwargs)
        worker.geometry.store.upsert_bars=Mock(side_effect=persist)
        self.addCleanup(release.set)
        return entered,release

    def test_pending_reference_keeps_true_opening_and_never_uses_old_bands(self):
        worker,observed,done=self.harness();entered,release=self.block_storage(worker)
        callback=Event()
        worker.bar(MarketBar('AAPL',CANDLE,100,101,99,100,100),lambda _:callback.set())
        self.assertTrue(entered.wait(2))
        self.send(worker,done,100,1,1)
        self.send(worker,done,104,2,2)
        self.assertEqual(observed[-1][1],'WAITING_FOR_REFERENCE_STORAGE')
        self.assertIsNone(observed[-1][0]['signal'])
        self.assertEqual(worker.geometry.states['AAPL']['opening'],100)
        self.assertFalse(callback.is_set());self.assertFalse(worker.failed.is_set())
        release.set();self.assertTrue(callback.wait(2))
        self.send(worker,done,104,3,3)
        self.assertEqual(observed[-1][1],'EXIT')
        self.assertEqual(observed[-1][0]['opening'],100)
        with closing(sqlite3.connect(worker.repository.database)) as db:
            self.assertEqual(db.execute('SELECT open FROM minute_bars WHERE symbol=? AND timestamp=?',
                ('AAPL',CANDLE.isoformat())).fetchone()[0],100)

    def test_unrelated_current_minute_storage_does_not_hold_up_valid_exit(self):
        worker,observed,done=self.harness()
        self.send(worker,done,100,1,1)
        prior=worker.geometry.states['AAPL']['history']
        entered,release=self.block_storage(worker);callback=Event()
        worker.bar(MarketBar('AAPL',CANDLE+timedelta(minutes=1),101,102,100,101,100),lambda _:callback.set())
        self.assertTrue(entered.wait(2))
        self.send(worker,done,104,120,2)
        self.assertEqual(observed[-1][1],'EXIT')
        self.assertFalse(callback.is_set());self.assertFalse(release.is_set())
        release.set();self.assertTrue(callback.wait(2))
        self.assertIs(worker.geometry.states['AAPL']['history'],prior)
        self.assertEqual(worker.geometry.states['AAPL']['opening'],100)

    def test_canonical_write_failure_still_stops_worker_and_does_not_call_analysis(self):
        worker,_,_=self.harness();callback=Mock()
        worker.geometry.store.upsert_bars=Mock(side_effect=sqlite3.OperationalError('private'))
        worker.bar(MarketBar('AAPL',CANDLE,100,101,99,100,100),callback)
        self.assertTrue(worker.failed.wait(2))
        self.assertEqual(worker.last_error,'BAR_STORAGE_FAILED');callback.assert_not_called()

    def test_premarket_minute_never_fences_regular_opening_references(self):
        worker,_,_=self.harness()
        session=worker.geometry.calendar.session(CANDLE.date())
        worker.geometry.session=session
        bar=MarketBar('AAPL',session.opens_at-timedelta(minutes=1),100,101,99,100,100)
        worker.pending_bars['AAPL']={1:bar}
        message=trade(100,session.opens_at+timedelta(seconds=1))
        self.assertFalse(worker._references_pending(message))
        self.assertFalse(worker.geometry.bar_affects_reference(bar,session.opens_at))
        # Regular bars within a required period still fence the calculation.
        regular=MarketBar('AAPL',session.opens_at,100,101,99,100,100)
        self.assertTrue(worker.geometry.bar_affects_reference(regular,session.opens_at+timedelta(minutes=15)))

    def test_ordered_revisions_commit_before_callbacks(self):
        worker,_,_=self.harness();seen=[];done=Event()
        def callback(bar):
            seen.append(bar.open)
            if len(seen)==2:done.set()
        worker.bar(MarketBar('AAPL',CANDLE,100,101,99,100,100),callback)
        worker.bar(MarketBar('AAPL',CANDLE,99,101,98,100,100),callback)
        self.assertTrue(done.wait(2));self.assertEqual(seen,[100,99])
        with closing(sqlite3.connect(worker.repository.database)) as db:
            self.assertEqual(db.execute('SELECT open FROM minute_bars WHERE symbol=? AND timestamp=?',
                ('AAPL',CANDLE.isoformat())).fetchone()[0],99)
