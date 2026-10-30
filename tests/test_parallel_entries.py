"""Bounded independent entry lookups; synthetic data and temporary stores only."""
from copy import deepcopy
from threading import Event
from time import monotonic,sleep
from unittest import TestCase
from unittest.mock import patch
from tests import test_automatic_entry_queue as fixtures
from tests import test_telegram_manual_runtime as runtime_fixture


class ParallelEntryTests(TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.runner.enable_parallel_entries()
        self.h.runner.background_preparation=True
        self.h.runner.background_entry_auxiliary=True
        self.addCleanup(self.close_pool)

    def close_pool(self):
        self.h.runner.close_entries()
        self.h.runner.entry_pool.shutdown(wait=True,cancel_futures=True)

    def wait_done(self):
        deadline=monotonic()+3
        while self.h.runner.entry_capacity()['inflight'] and monotonic()<deadline:sleep(.005)
        self.assertEqual(self.h.runner.entry_capacity()['inflight'],0)
        self.assertEqual(self.h.runner.entry_capacity()['errors'],0)

    def test_slow_other_symbol_does_not_delay_real_local_order(self):
        h=self.h;h.arm();real=h.plan();other=deepcopy(real)
        other.update(id='synthetic-slow',symbol='AAPL')
        started=Event();release=Event();execute=h.runner._execute;validate=h.runner._signal
        def lookup(plan,signal):
            if plan['id']==other['id']:
                started.set()
                if not release.wait(3):raise AssertionError('TEST_TIMEOUT')
            else:execute(plan,signal)
        # The second company uses its real temporary queue, engine and broker.
        with patch.object(h.store,'active',return_value=[other,real]),patch.object(h.runner,'_execute',side_effect=lookup),\
             patch.object(h.runner,'_signal',side_effect=lambda plan,state,now:validate(real,state,now)):
            try:
                h.runner.step();self.assertTrue(started.wait(1))
                h.runner.step()
                deadline=monotonic()+1
                while h.plan()['state']!='SUBMITTED' and monotonic()<deadline:sleep(.005)
                self.assertEqual(h.plan()['state'],'SUBMITTED')
                self.assertFalse(release.is_set())
                for _ in range(4):h.runner.step()
                self.assertEqual(len(h.f.engine.ledger.orders()),1)
            finally:release.set()
            self.wait_done()

    def test_capacity_is_two_and_one_lookup_per_plan(self):
        h=self.h;h.arm();plans=[]
        for i in range(4):
            plan=deepcopy(h.plan());plan['id']='synthetic-'+str(i);plans.append(plan)
        started=[Event(),Event()];release=Event();calls=[]
        def blocked(plan,signal):
            calls.append(plan['id']);started[len(calls)-1].set();release.wait(3)
        with patch.object(h.store,'active',return_value=plans),patch.object(h.runner,'_execute',side_effect=blocked):
            try:
                h.runner.step();h.runner.step()
                self.assertTrue(all(event.wait(1) for event in started))
                for _ in range(10):h.runner.step()
                self.assertEqual(len(calls),2);self.assertEqual(len(set(calls)),2)
                self.assertEqual(h.runner.entry_capacity()['inflight'],2)
            finally:release.set()
            self.wait_done()

    def test_pause_during_lookup_prevents_order(self):
        self.mutate_during_lookup(lambda h:h.store.pause(h.plan()['id']))

    def test_changed_authorization_during_lookup_prevents_old_quantity(self):
        def change(h):
            with h.store.transaction() as db:
                db.execute('UPDATE queue_plans SET quantity=1,target=? WHERE id=?',('10',h.plan()['id']))
        self.mutate_during_lookup(change)

    def test_shutdown_during_lookup_prevents_order(self):
        self.mutate_during_lookup(lambda h:h.runner.close_entries())
        self.assertIsNone(self.h.runner.step())

    def test_quote_expiry_during_lookup_is_not_bypassed(self):
        def expire(h):
            from datetime import timedelta
            h.f.now+=timedelta(seconds=31)
        self.mutate_during_lookup(expire)

    def mutate_during_lookup(self,mutation):
        h=self.h;h.arm();started=Event();release=Event();original=h.f.market.get_catalog_chain
        def blocked(*args,**kwargs):
            result=original(*args,**kwargs);started.set();release.wait(3);return result
        with patch.object(h.f.market,'get_catalog_chain',side_effect=blocked):
            try:
                h.runner.step();self.assertTrue(started.wait(1));mutation(h)
            finally:release.set()
            self.wait_done()
        self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),[])

    def test_dispatch_once_and_fill_needs_post_order_quote(self):
        h=self.h;h.arm();h.runner.step();self.wait_done()
        for _ in range(4):h.runner.step()
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertEqual(h.f.engine.ledger.orders()[0]['status'],'WORKING')
        h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.orders()[0]['status'],'FILLED')

    def test_parallel_worker_keeps_shared_provider_backoff(self):
        from datetime import timedelta
        from schwab_connection import SchwabError
        h=self.h;h.arm()
        error=SchwabError('RATE_LIMITED',retry_after_seconds=60)
        h.f.client.full_chain.side_effect=error
        h.runner.step();self.wait_done()
        h.f.now+=timedelta(seconds=6)
        h.runner.step();self.wait_done()
        h.f.client.full_chain.assert_called_once()
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_stopping_companion_revokes_readiness_immediately(self):
        from datetime import datetime,timezone
        companion=runtime_fixture.TelegramRuntimeTests().companion()
        companion.monitor_ready=True;companion.monitor_at=datetime.now(timezone.utc)
        self.assertTrue(companion.monitor_active())
        companion.stop.set();self.assertFalse(companion.monitor_active())
