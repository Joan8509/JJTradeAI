"""Isolated SQLite contention and observed-position trace regressions."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock,patch
import json,sqlite3
from threading import Event
import time

from live_strategy_service import save_data_only_preview
from live_service_runtime import ResilientStreamSupervisor
from observation_journal import ObservationJournal
from tests.test_live_service_runtime import FakeContinuity,ReturningStream,NOW
from tests import test_automatic_entry_queue as queued
from tests.test_bollinger_tick_stream import seed
from bollinger_tick_stream import RealtimeBollingerWorker,ingest_timing_snapshot

def busy():
    error=sqlite3.OperationalError('private fixture')
    error.sqlite_errorcode=sqlite3.SQLITE_BUSY
    return error

class OptionalProjectionTests(TestCase):
    def test_timing_receipt_identifies_blocked_persistence_without_network_or_sql_work(self):
        with TemporaryDirectory() as folder:
            database=Path(folder)/'market.db';seed(database)
            worker=RealtimeBollingerWorker(database,'iex',['AAPL'])
            entered=Event();release=Event()
            def persist(*args,**kwargs):
                entered.set();release.wait(3)
            try:
                worker.geometry.store.upsert_bars=Mock(side_effect=persist)
                worker.bar(Mock(symbol='AAPL'),lambda _:None)
                self.assertTrue(entered.wait(2))
                receipt=ingest_timing_snapshot(worker)
                self.assertEqual(receipt['persistence_stage'],'BAR_PERSIST')
                self.assertNotEqual(receipt['stage'],'BAR_PERSIST')
                self.assertEqual(receipt['revision'],'ingest_stage_timing_v1')
                self.assertNotIn('payload',json.dumps(receipt))
                # Receipt sampling does not call the writer again or require
                # the blocked persistence operation to finish.
                self.assertEqual(worker.geometry.store.upsert_bars.call_count,1)
            finally:release.set();worker.close()

    def test_busy_health_does_not_drop_bar_or_claim_updated_receipt(self):
        health=Mock();received=[]
        def update(*args,**kwargs):
            if 'bar_timestamp' in kwargs:raise busy()
        health.update.side_effect=update
        supervisor=ResilientStreamSupervisor(stream_factory=lambda:ReturningStream(emit_bar=True),
            continuity=FakeContinuity(),health=health,sleeper=lambda _:None,now=lambda:NOW)
        supervisor.run(['SPY'],received.append,max_attempts=1)
        self.assertEqual(len(received),1)
        self.assertEqual(supervisor.continuity.calls[0][0],'SPY')

    def test_preview_busy_is_optional_only_after_canonical_commit(self):
        with patch('indexed_bollinger_preview.preview_for_bar',return_value={}), \
             patch('live_strategy_service.LiveBollingerPreviewRepository') as repository, \
             patch('bollinger_tick_stream.record_ingest_failure') as receipt:
            repository.return_value.save.side_effect=busy()
            self.assertFalse(save_data_only_preview('unused',None,feed='iex',already_persisted=True))
            receipt.assert_called_once()
            with self.assertRaises(sqlite3.OperationalError):
                save_data_only_preview('unused',None,feed='iex',already_persisted=False)
            repository.return_value.save.side_effect=sqlite3.OperationalError('schema missing')
            with self.assertRaises(sqlite3.OperationalError):
                save_data_only_preview('unused',None,feed='iex',already_persisted=True)

class PositionTraceTests(TestCase):
    def test_marks_are_private_deferred_deduplicated_and_bounded(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'journal.jsonl';j=ObservationJournal(path,capacity=2)
            fields=dict(at=NOW,quote_at=NOW,client_key='a'*64,contract='AMZN261023C00100000',
                        bid=2,ask=2.05,bid_size=1,ask_size=2,quantity=2,target=2.4,stop=1.6,
                        entry_average=2,token='SECRET')
            j.record('POSITION_MARK',**fields);j.record('POSITION_MARK',**fields)
            self.assertEqual(len(j.pending),1);self.assertFalse(path.exists())
            fields['quote_at']=NOW+timedelta(seconds=1);j.record('POSITION_MARK',**fields)
            fields['quote_at']=NOW+timedelta(seconds=2);j.record('POSITION_MARK',**fields)
            self.assertEqual(j.dropped,1);j.flush()
            body=path.read_text();self.assertNotIn('SECRET',body)
            self.assertEqual(len(body.splitlines()),2)
            row=json.loads(body.splitlines()[0]);self.assertEqual(row['stop'],'1.6')
            self.assertEqual(row['bid_size'],'1')
            j.lock.acquire()
            try:j.record('POSITION_MARK',**fields)
            finally:j.lock.release()
            self.assertEqual(j.dropped,2)

    def harness(self):
        h=queued.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm(target='35');h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
        return h

    def test_holding_position_records_bid_without_order_or_extra_lookup(self):
        h=self.harness();f=h.f
        journal=Mock();f.service.observation_journal=journal
        f.quote(bid=2,ask=2.05,seconds=2);f.client.quotes.reset_mock()
        f.service.observe()
        marks=[c for c in journal.record.call_args_list if c.args[0]=='POSITION_MARK']
        self.assertTrue(marks);self.assertEqual(marks[0].kwargs['quantity'],2)
        self.assertEqual(len(f.engine.ledger.orders()),1)
        self.assertEqual(f.client.quotes.call_count,1)

    def test_optional_trace_failure_does_not_block_position_management(self):
        h=self.harness();f=h.f
        f.service.observation_journal=Mock();f.service.observation_journal.record.side_effect=OSError('private')
        f.quote(bid=1.5,ask=1.55,seconds=2);f.service.observe()
        self.assertEqual(f.service.pending_orders()[0]['order']['instruction'],'SELL_TO_CLOSE')
