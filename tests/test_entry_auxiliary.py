"""Trading never waits for optional presentation. Synthetic data and temp DBs."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import TestCase
from unittest.mock import patch
from tests import test_automatic_entry_queue as fixtures

class EntryAuxiliaryTests(TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.runner.background_entry_auxiliary=True

    def test_optional_signal_and_order_diagnostics_do_not_run_before_dispatch(self):
        h=self.h;h.arm()
        with patch.object(h.store,'decision') as write:
            h.runner.step();write.assert_not_called()
            self.assertEqual(h.plan()['state'],'SUBMITTED')
            self.assertTrue(h.f.service.observation_requested.is_set())
            h.f.quote(seconds=1);h.f.service.observe()
            self.assertEqual(h.f.engine.ledger.order(h.plan()['client_key'])['status'],'FILLED')
            while h.runner.drain_auxiliary():pass
            stages=[call.args[1] for call in write.call_args_list]
            self.assertIn('SIGNAL_READY',stages);self.assertIn('ORDER_REGISTERED',stages)

    def test_catalog_explanation_and_receipt_run_after_durable_dispatch(self):
        h=self.h;h.arm()
        with patch('queue_entry_diagnostics.catalog_check') as check:
            h.runner.step();check.assert_not_called()
        self.assertEqual(h.plan()['state'],'SUBMITTED');self.assertIsNone(h.plan()['intent'])
        self.assertTrue(h.f.service.observation_requested.is_set())
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        while h.runner.drain_auxiliary():pass
        self.assertIsNotNone(h.plan()['intent']);self.assertIsNotNone(h.store.last_catalog_check(h.plan()['id']))
        self.assertEqual(len(h.f.engine.ledger.orders()),1)

    def test_blocked_receipt_does_not_hold_workflow_lock_or_prevent_fill(self):
        h=self.h;h.arm();h.runner.step()
        started=Event();release=Event();original=h.runner._receipt
        def blocked(*args):
            started.set()
            if not release.wait(3):raise RuntimeError('TEST_TIMEOUT')
            return original(*args)
        def drain():
            while h.runner.drain_auxiliary():pass
        with patch.object(h.runner,'_receipt',side_effect=blocked),ThreadPoolExecutor(max_workers=1) as pool:
            worker=pool.submit(drain)
            try:
                self.assertTrue(started.wait(1))
                acquired=h.f.service.lock.acquire(timeout=.2)
                if acquired:h.f.service.lock.release()
                self.assertTrue(acquired)
                h.f.quote(seconds=1);h.f.service.observe()
                self.assertEqual(h.f.engine.ledger.order(h.plan()['client_key'])['status'],'FILLED')
            finally:release.set()
            worker.result(timeout=2)
        self.assertIsNotNone(h.plan()['intent'])

    def test_receipt_failure_does_not_turn_confirmed_dispatch_into_uncertainty(self):
        h=self.h;h.arm();h.runner.step()
        with patch.object(h.runner,'_receipt',side_effect=OSError('PRIVATE_DETAIL')):
            while h.runner.drain_auxiliary():pass
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(h.store.read('SELECT state FROM queue_attempts')[0]['state'],'SUBMITTED')
        h.runner.step();self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertNotIn('PRIVATE_DETAIL',str(h.store.read('SELECT * FROM queue_decisions')))

    def test_full_optional_queue_never_blocks_or_duplicates_dispatch(self):
        h=self.h
        for _ in range(h.runner.auxiliary_jobs.maxsize):h.runner.auxiliary_jobs.put_nowait(('discarded',))
        h.arm();h.runner.step();h.runner.step()
        self.assertEqual(h.plan()['state'],'SUBMITTED');self.assertIsNone(h.plan()['intent'])
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertTrue(h.f.service.observation_requested.is_set())

    def test_entry_quality_is_after_dispatch_and_records_selected_quote(self):
        h=self.h;h.arm()
        with patch('entry_quality_research.execution_observation') as quality:
            h.runner.step();quality.assert_not_called()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertTrue(h.f.service.observation_requested.is_set())
        calls_before=h.f.client.quotes.call_count
        while h.runner.drain_auxiliary():pass
        self.assertEqual(h.f.client.quotes.call_count,calls_before)
        rows=h.store.read("SELECT details_json FROM queue_decisions WHERE stage='ENTRY_QUALITY_OBSERVATION'")
        self.assertEqual(len(rows),1)
        import json
        details=json.loads(rows[0]['details_json'])
        self.assertFalse(details['entry_gate_enabled'])
        self.assertIn('selected_bid',details)
        self.assertIn('selected_ask',details)
        self.assertIn('spread_pct_ask',details['spread'])

    def test_failed_quality_never_retries_or_changes_dispatched_order(self):
        h=self.h;h.arm();h.runner.step()
        with patch('entry_quality_research.execution_observation',side_effect=ValueError('PRIVATE_DETAIL')):
            while h.runner.drain_auxiliary():pass
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(h.store.read('SELECT state FROM queue_attempts')[0]['state'],'SUBMITTED')
        h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(h.plan()['client_key'])['status'],'FILLED')
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertNotIn('PRIVATE_DETAIL',str(h.store.read('SELECT * FROM queue_decisions')))
