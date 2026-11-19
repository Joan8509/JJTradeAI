"""Fresh observations still validate, while unchanged ones perform no writes."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock

from real_order_ledger import RealOrderLedger,RealOrderBlocked
from tests import test_schwab_execution_snapshot as snapshots
from tests import test_real_order_ledger as journal


class ChangeOnlyJournalTests(TestCase):
    def setUp(self):
        self.f=snapshots.CumulativeExecutionTests();self.f.setUp()
        self.save=Mock(wraps=self.f.vault.save);self.f.vault.save=self.save

    def test_confirmed_cancel_wakes_exit_without_authorizing_a_sale(self):
        from real_execution_runtime import RealExecutionWorker
        for result in (dict(state='CANCELED'),dict(state='PARTIALLY_FILLED',fills={'one':{}})):
            with self.subTest(result=result):
                execution=Mock(binding=journal.BINDING)
                worker=RealExecutionWorker(Mock(),execution,Mock(),separate_observation=True)
                def observed():
                    worker._stop.set()
                    return [result]
                execution.observe_orders.side_effect=observed
                worker._loop('orders',1)
                self.assertTrue(worker._exit_wake.is_set())
                execution.monitor_positions.assert_not_called()
                execution.coordinator.submit.assert_not_called()

    def test_cancel_observation_interrupts_exit_periodic_wait(self):
        from threading import Event
        from real_execution_runtime import RealExecutionWorker
        first=Event();second=Event();execution=Mock(binding=journal.BINDING)
        worker=RealExecutionWorker(Mock(),execution,Mock(),separate_observation=True)
        calls=[]
        def monitor():
            calls.append(1)
            (first if len(calls)==1 else second).set()
            if len(calls)>1:worker._stop.set()
            return []
        execution.monitor_positions.side_effect=monitor
        from threading import Thread
        thread=Thread(target=worker._loop,args=('exits',30),daemon=True)
        try:
            thread.start();self.assertTrue(first.wait(1))
            worker._exit_wake.set();self.assertTrue(second.wait(1))
        finally:
            worker._stop.set();worker._exit_wake.set();thread.join(1)

    def test_identical_working_and_terminal_gets_do_not_rewrite_or_append_history(self):
        f=self.f
        for records,status in (([],'WORKING'),([f.first],'WORKING'),
                               ([(3,'.99',f.now.isoformat())],'FILLED')):
            with self.subTest(status=status,records=len(records)):
                p=snapshots.snapshot(f.row,records,status)
                # The complete fill must retain the earlier partial execution.
                if status=='FILLED':p=snapshots.snapshot(f.row,[f.first,(2,'.99',f.now.isoformat())],status)
                f.apply(p);before=deepcopy(f.vault.data);self.save.reset_mock()
                f.now+=timedelta(milliseconds=100)
                for _ in range(20):self.assertEqual(f.apply(p),before['requests'][f.row['id']])
                self.save.assert_not_called();self.assertEqual(f.vault.data,before)

    def test_changed_fills_in_same_partial_state_are_durable(self):
        f=self.f;f.apply(snapshots.snapshot(f.row,[f.first]));self.save.reset_mock()
        result=f.apply(snapshots.snapshot(f.row,[f.first,(1,'.98',f.now.isoformat())]))
        self.assertEqual(result['state'],'PARTIALLY_FILLED')
        self.assertEqual(sum(v['quantity'] for v in result['fills'].values()),2)
        self.save.assert_called_once()
        restarted=RealOrderLedger(lambda:f.vault,lambda:f.now)
        self.assertEqual(restarted.requests(journal.BINDING)[0],result)

    def test_repeat_error_does_not_grow_history_but_new_error_and_recovery_persist(self):
        f=self.f;p=snapshots.snapshot(f.row,[f.first]);f.apply(p)
        bad=snapshots.snapshot(f.row,[])
        self.assertEqual(f.apply(bad)['state'],'RECONCILIATION_REQUIRED')
        before=deepcopy(f.vault.data);self.save.reset_mock()
        for _ in range(20):self.assertEqual(f.apply(bad)['state'],'RECONCILIATION_REQUIRED')
        self.save.assert_not_called();self.assertEqual(f.vault.data,before)
        changed=deepcopy(bad);changed['orderActivityCollection']=[dict(executionType='UNKNOWN',executionLegs=[{}])]
        result=f.apply(changed);self.assertIn('UNSUPPORTED_EXECUTION_ACTIVITY',result['issues'])
        self.save.assert_called_once();self.save.reset_mock()
        self.assertEqual(f.apply(p)['state'],'PARTIALLY_FILLED');self.save.assert_called_once()

    def test_failed_change_save_remains_failure_and_identical_get_checks_identity(self):
        f=self.f;p=snapshots.snapshot(f.row,[]);f.apply(p)
        self.save.side_effect=OSError('SYNTHETIC_DISK_FAILURE')
        with self.assertRaises(OSError):f.apply(snapshots.snapshot(f.row,[f.first]))
        self.assertEqual(f.ledger.available_to_close(journal.BINDING,journal.CONTRACT),0)
        wrong=deepcopy(p);wrong['accountNumber']='87654321'
        with self.assertRaises(ValueError):f.apply(wrong)
        wrong=deepcopy(p);wrong['orderId']=999
        with self.assertRaises(RealOrderBlocked):f.apply(wrong)

    def test_repeated_cancel_poll_preserves_reservation_until_terminal_get(self):
        f=self.f;f.apply(snapshots.snapshot(f.row,[f.first]))
        f.gateway.cancel.return_value=True
        f.coordinator.cancel(journal.BINDING,f.row['id'])
        p=snapshots.snapshot(f.row,[f.first]);f.apply(p)
        before=deepcopy(f.vault.data);self.save.reset_mock()
        for _ in range(10):self.assertEqual(f.apply(p)['state'],'PENDING_CANCEL')
        self.save.assert_not_called();self.assertEqual(f.vault.data,before)
        self.assertEqual(f.ledger.available_to_close(journal.BINDING,journal.CONTRACT),1)
        terminal=snapshots.snapshot(f.row,[f.first],'CANCELED')
        self.assertEqual(f.apply(terminal)['state'],'CANCELED');self.save.assert_called_once()
