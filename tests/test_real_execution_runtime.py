"""Account wiring and loop separation without production credentials or calls."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from threading import Event

from real_execution_runtime import connect_live_execution, RealExecutionWorker
from tests import test_real_execution_service as cycle


class RuntimeTests(TestCase):
    def test_slow_manual_close_discovery_never_holds_price_or_entry_threads(self):
        release=Event();discovery=Event();prices=Event();entries=Event()
        execution=Mock(binding='a'*64);queue=Mock();external=Mock()
        execution.monitor_positions.side_effect=lambda:(prices.set(),[])[-1]
        queue.step.side_effect=lambda *a,**kw:entries.set()
        external.step.side_effect=lambda:(discovery.set(),release.wait(3))
        execution.observe_orders.return_value=[]
        worker=RealExecutionWorker(queue,execution,Mock(),separate_observation=True)
        worker.external_closes=external
        try:
            worker.start();self.assertTrue(discovery.wait(1))
            self.assertTrue(prices.wait(1));self.assertTrue(entries.wait(1))
            self.assertFalse(worker.status()['external_closes_current'])
        finally:release.set();worker.shutdown()

    def test_slow_orders_and_telegram_do_not_block_price_or_entry_loops(self):
        release=Event();orders=Event();notices=Event();prices=Event();entries=Event()
        execution=Mock(binding='a'*64);queue=Mock();notifier=Mock()
        execution.observe_orders.side_effect=lambda:(orders.set(),release.wait(3),[])[-1]
        notifier.step.side_effect=lambda:(notices.set(),release.wait(3))
        execution.monitor_positions.side_effect=lambda:(prices.set(),[])[-1]
        queue.step.side_effect=lambda *a,**kw:entries.set()
        worker=RealExecutionWorker(queue,execution,Mock(),separate_observation=True,notices=notifier)
        try:
            worker.start()
            self.assertTrue(orders.wait(1));self.assertTrue(notices.wait(1))
            self.assertTrue(prices.wait(1));self.assertTrue(entries.wait(1))
            execution.poll.assert_not_called()
            self.assertFalse(worker.status()['notices_current'])
        finally:release.set();worker.shutdown()

    def test_factory_is_lazy_and_scoped_to_explicit_account(self):
        context=SimpleNamespace(binding='a'*64,account_number='12345678',account_hash='ACCOUNT_HASH',oauth=Mock())
        gateway=Mock();quote=Mock();ready=Mock(return_value=False);signal=Mock()
        service=connect_live_execution(context,quote_contract=quote,entry_ready=ready,signal_current=signal,
            ledger=Mock(),gateway_factory=gateway)
        context.oauth.access.assert_not_called();quote.assert_not_called();ready.assert_not_called()
        gateway.return_value.submit.assert_not_called()
        self.assertEqual(gateway.call_args.kwargs['account_hash'],'ACCOUNT_HASH')
        self.assertIs(gateway.call_args.kwargs['commit_guard'].__self__,service)

    def test_slow_exit_poll_does_not_hold_entry_loop_and_constructor_starts_nothing(self):
        release=Event();entered=Event();polled=Event()
        queue=Mock();execution=Mock(binding='a'*64)
        execution.poll.side_effect=lambda:(polled.set(),release.wait(3),[])[-1]
        queue.step.side_effect=lambda *a,**kw:entered.set()
        worker=RealExecutionWorker(queue,execution,Mock())
        self.assertFalse(worker.status()['started']);execution.poll.assert_not_called()
        try:
            worker.start()
            self.assertTrue(polled.wait(1));self.assertTrue(entered.wait(1))
            self.assertFalse(worker.status()['exits_current'])
            with self.assertRaisesRegex(RuntimeError,'ALREADY_STARTED'):worker.start()
            self.assertFalse(queue.step.call_args.kwargs['monitor'])
        finally:release.set();worker.shutdown()

    def test_monitor_errors_do_not_report_ready_and_do_not_stop_other_loop(self):
        execution=Mock(binding='a'*64);queue=Mock()
        worker=RealExecutionWorker(queue,execution,Mock())
        def poll():
            worker._stop.set()
            return [dict(state='LIVE_ORDER_READ_UNAVAILABLE')]
        execution.poll.side_effect=poll
        worker._loop('exits',1)
        self.assertFalse(worker.status()['exits_current'])
        self.assertEqual(worker.status()['errors']['exits'],'LIVE_MONITOR_REQUIRES_REVIEW')
        worker._stop.clear();worker._wake.set()
        queue.step.side_effect=lambda *a,**kw:worker._stop.set()
        worker._loop('entries',.2)
        queue.step.assert_called_once()

    def test_real_transport_rechecks_signal_after_readiness_changes(self):
        fixture=cycle.RealExecutionCycleTests();fixture.setUp()
        service=fixture.service
        # Durable service guard is also what the real transport receives.
        row=fixture.enter()
        stored=fixture.ledger.requests('a'*64)
        row=stored[0];row=dict(row,state='SUBMITTING')
        fixture.vault.data['requests'][row['id']]['state']='SUBMITTING'
        self.assertTrue(service.commit_guard(row,'SUBMIT'))
        fixture.ready=False
        self.assertFalse(service.commit_guard(row,'SUBMIT'))
