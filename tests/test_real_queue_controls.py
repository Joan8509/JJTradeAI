"""Atomic REAL waiting-list controls; no broker or production state."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock,patch
from real_order_ledger import RealOrderBlocked
from tests import test_real_order_ledger as journal


class RealQueueControlsTests(TestCase):
    def setUp(self):
        from tests.test_real_automatic_queue import RealQueueTests
        self.fx=RealQueueTests();self.fx.setUp();self.fx.single_radar()
        self.queue=self.fx.queue;self.plan=self.queue.read(journal.BINDING)

    def resume(self,**kw):return self.queue.resume(journal.BINDING,self.plan['id'],execution_ready=lambda:True,**kw)

    def test_resume_preserves_plan_original_clock_used_signals_and_removed_companies(self):
        row=self.plan['rows'][0]
        self.queue._change(journal.BINDING,self.plan['id'],row['id'],lambda p,r:r['used_signals'].append('ALREADY_USED'))
        self.queue.remove(journal.BINDING,self.plan['id'],self.plan['rows'][1]['id'])
        self.queue.pause(journal.BINDING);before=self.queue.read(journal.BINDING)
        self.fx.now+=timedelta(minutes=20)
        after=self.resume()
        self.assertEqual(after['id'],before['id']);self.assertEqual(after['armed_at'],before['armed_at'])
        self.assertEqual(after['session_close'],before['session_close'])
        self.assertEqual(after['rows'][0]['used_signals'],['ALREADY_USED'])
        self.assertEqual(after['rows'][0]['state'],'ARMED');self.assertFalse(after['rows'][0]['repeat_new_signals'])
        self.assertEqual(after['rows'][1],before['rows'][1]);self.assertFalse(after['paused'])
        self.fx.execution.enter.assert_not_called()

    def test_resume_requires_current_executor_and_same_unexpired_session(self):
        self.queue.pause(journal.BINDING);before=self.queue.read(journal.BINDING)
        with self.assertRaisesRegex(RealOrderBlocked,'EXECUTOR_NOT_VERIFIED'):
            self.queue.resume(journal.BINDING,self.plan['id'],execution_ready=lambda:False)
        with self.assertRaisesRegex(RealOrderBlocked,'QUEUE_CHANGED'):
            self.queue.resume(journal.BINDING,'STALE',execution_ready=lambda:True)
        self.fx.now=self.fx.end
        with self.assertRaisesRegex(RealOrderBlocked,'SESSION_INVALID'):self.resume()
        self.assertEqual(self.queue.read(journal.BINDING),before)

    def test_resume_cannot_reset_a_first_fill_or_uncertain_claim(self):
        for field,value in (('entry_consumed',True),('entry_owner','CLAIMED')):
            with self.subTest(field=field):
                self.queue.pause(journal.BINDING)
                self.queue._change(journal.BINDING,self.plan['id'],self.plan['rows'][0]['id'],lambda p,r:p.update({field:value}))
                before=self.queue.read(journal.BINDING)
                with self.assertRaisesRegex(RealOrderBlocked,'FIRST_ENTRY_RESERVED'):self.resume()
                self.assertEqual(self.queue.read(journal.BINDING),before)
                self.queue._change(journal.BINDING,self.plan['id'],self.plan['rows'][0]['id'],lambda p,r:p.update({field:False if field=='entry_consumed' else None}))

    def test_resume_does_not_revive_excluded_completed_or_review_rows(self):
        self.queue.pause(journal.BINDING)
        for state in ('EXCLUDED_FIRST_ENTRY','COMPLETED','REQUIRES_REVIEW'):
            with self.subTest(state=state):
                self.queue._change(journal.BINDING,self.plan['id'],self.plan['rows'][0]['id'],lambda p,r:r.update(state=state))
                before=self.queue.read(journal.BINDING)
                if state=='REQUIRES_REVIEW':
                    with self.assertRaisesRegex(RealOrderBlocked,'FIRST_ENTRY_RESERVED'):self.resume()
                    self.assertEqual(self.queue.read(journal.BINDING),before)
                else:
                    after=self.resume();self.assertEqual(after['rows'][0],before['rows'][0])
                    self.queue.pause(journal.BINDING)

    def test_clear_removes_only_waiting_rows_and_preserves_submitted_order_and_history(self):
        row=self.plan['rows'][0]
        self.queue._change(journal.BINDING,self.plan['id'],row['id'],lambda p,r:(
            p.update(entry_owner=r['id']),r.update(state='ORDER_SENT',request_id='OWN_ORDER',claim='USED',used_signals=['USED'])))
        before=self.queue.read(journal.BINDING)
        after=self.queue.remove_waiting(journal.BINDING,self.plan['id'])
        self.assertTrue(after['paused']);self.assertEqual(after['rows'][0],before['rows'][0])
        self.assertEqual(after['entry_owner'],before['entry_owner'])
        self.assertEqual(after['rows'][1]['state'],'REMOVED')
        self.fx.execution.enter.assert_not_called();self.fx.execution.close_manually.assert_not_called()
        self.assertEqual(self.queue.remove_waiting(journal.BINDING,self.plan['id'])['rows'],after['rows'])

    def test_clear_from_stale_plan_cannot_affect_a_new_plan(self):
        before=self.queue.read(journal.BINDING)
        with self.assertRaisesRegex(RealOrderBlocked,'QUEUE_CHANGED'):
            self.queue.remove_waiting(journal.BINDING,'STALE')
        self.assertEqual(self.queue.read(journal.BINDING),before)

    def test_clear_during_contract_preparation_prevents_the_pending_claim(self):
        def provider(row):
            proposal=self.fx.any_company(row)
            self.queue.remove_waiting(journal.BINDING,self.plan['id'])
            return proposal
        with self.assertRaisesRegex(RealOrderBlocked,'QUEUE_PAUSED'):self.fx.step(provider)
        self.fx.execution.enter.assert_not_called()
        self.assertTrue(all(r['state']=='REMOVED' for r in self.queue.read(journal.BINDING)['rows']))

    def test_resume_keeps_previously_used_signal_unavailable(self):
        first=self.plan['rows'][0]
        self.queue._change(journal.BINDING,self.plan['id'],first['id'],lambda p,r:r['used_signals'].append('SIGNAL_AAPL'))
        self.queue.pause(journal.BINDING);self.resume()
        self.fx.step(lambda row:self.fx.any_company(row) if row['symbol']=='AAPL' else None)
        self.fx.execution.enter.assert_not_called()

    def test_proxy_preserves_account_selection_guard_without_arming_another_plan(self):
        from real_live_control import RealRuntimeProxy,register_selected_account
        from types import SimpleNamespace
        control=journal.Vault();queue=Mock()
        context=SimpleNamespace(binding=journal.BINDING,account_number='SYNTHETIC',account_hash='SYNTHETIC')
        register_selected_account(context,store_factory=lambda:control)
        proxy=RealRuntimeProxy(journal.BINDING,queue=queue,control_factory=lambda:control)
        proxy.resume('PLAN');queue.resume.assert_called_once()
        proxy.remove_waiting('PLAN');queue.remove_waiting.assert_called_once_with(journal.BINDING,'PLAN')
        queue.arm.assert_not_called()
        control.data['execution_authorized']=False
        with self.assertRaisesRegex(ValueError,'ACCOUNT_NOT_SELECTED'):proxy.resume('PLAN')
