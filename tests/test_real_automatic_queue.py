"""REAL queue durable claims and daily lifecycle; no worker/network starts."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from real_automatic_queue import RealAutomaticQueue
from real_order_ledger import RealOrderBlocked
from tests import test_real_order_ledger as journal
from tests import test_schwab_option_order_request as options
from schwab_option_order_request import prepare_option_limit


class RealQueueTests(TestCase):
    def test_signal_hints_skip_idle_companies_before_preparation_and_read_once(self):
        self.single_radar()
        hints=Mock(return_value=frozenset({'MSFT'}))
        provider=Mock(side_effect=self.any_company)
        self.queue.step(journal.BINDING,self.execution,provider,signal_symbols=hints)
        hints.assert_called_once_with(('AAPL','MSFT'))
        self.assertEqual([c.args[0]['symbol'] for c in provider.call_args_list],['MSFT'])
        self.assertTrue(self.execution.enter.call_args.kwargs['draft'].contract.startswith('MSFT'))

    def test_hint_is_not_authorization_and_next_turn_can_observe_new_signal(self):
        hints=Mock(return_value=frozenset())
        provider=Mock(return_value=None)
        self.queue.step(journal.BINDING,self.execution,provider,signal_symbols=hints)
        provider.assert_not_called();self.execution.enter.assert_not_called()
        hints.return_value=frozenset({'AAPL'})
        self.queue.step(journal.BINDING,self.execution,provider,signal_symbols=hints)
        provider.assert_called_once();self.execution.enter.assert_not_called()
        self.assertEqual(hints.call_count,2)

    def test_failed_or_invalid_hint_falls_back_to_original_lookup(self):
        for value in (None,['MSFT']):
            hints=Mock(return_value=value);provider=Mock(return_value=None)
            self.queue.step(journal.BINDING,self.execution,provider,signal_symbols=hints)
            self.assertEqual(provider.call_count,2)
        provider=Mock(return_value=None)
        self.queue.step(journal.BINDING,self.execution,provider,signal_symbols=Mock(side_effect=OSError()))
        self.assertEqual(provider.call_count,2)

    def test_pause_does_not_query_hints_and_keeps_exit_monitor(self):
        self.queue.pause(journal.BINDING)
        hints=Mock();provider=Mock()
        self.queue.step(journal.BINDING,self.execution,provider,signal_symbols=hints)
        hints.assert_not_called();provider.assert_not_called();self.execution.poll.assert_called_once()

    def test_positive_hint_cannot_bypass_atomic_removal(self):
        plan=self.queue.read(journal.BINDING)
        def removed(row):
            self.queue.remove(journal.BINDING,plan['id'],row['id'])
            return self.any_company(row)
        with self.assertRaisesRegex(RealOrderBlocked,'LIVE_QUEUE_PAUSED'):
            self.queue.step(journal.BINDING,self.execution,removed,signal_symbols=lambda symbols:{'AAPL'})
        self.execution.enter.assert_not_called()

    def test_recovered_ack_keeps_original_claim_and_excludes_other_companies_on_fill(self):
        self.single_radar()
        request=dict(id='RECOVERED',intent='SIGNAL_AAPL',state='SUBMITTING',broker_id=None,fills={})
        self.execution.ledger.requests.return_value=[request]
        self.execution.enter.side_effect=OSError('SYNTHETIC_ACK_SAVE_FAILED')
        self.step(self.any_company)
        plan=self.queue.read(journal.BINDING)
        self.assertEqual(plan['rows'][0]['request_id'],'RECOVERED')
        self.assertEqual(plan['rows'][0]['state'],'REQUIRES_REVIEW')
        request.update(broker_id='123',state='FILLED',fills={'x':dict(quantity=2)})
        self.step(self.any_company)
        plan=self.queue.read(journal.BINDING)
        self.assertTrue(plan['entry_consumed'])
        self.assertEqual(plan['rows'][1]['state'],'EXCLUDED_FIRST_ENTRY')
        self.assertEqual(plan['rows'][0]['state'],'ORDER_SENT')
        self.execution.enter.assert_called_once()

    def setUp(self):
        self.now=options.NOW;self.vault=journal.Vault()
        self.queue=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        self.end=self.now+timedelta(hours=6)
        self.rows=[dict(symbol='AAPL',quantity=2,target='20'),dict(symbol='MSFT',quantity=1,target='10')]
        self.execution=Mock(binding=journal.BINDING)
        self.execution.poll.return_value=[]
        self.execution.enter.return_value=dict(id='REQ',broker_id='123',state='ACKNOWLEDGED')
        self.execution.ledger.requests.return_value=[]
        self.arm()
        self.now+=timedelta(seconds=1)

    def arm(self,**changes):
        args=dict(session_open=self.now,session_close=self.end,execution_ready=lambda:True)
        args.update(changes)
        return self.queue.arm(journal.BINDING,self.rows,**args)

    def proposal(self,row):
        if row['symbol']!='AAPL':return None
        draft=prepare_option_limit(options.contract(quote_timestamp=self.now),instruction='BUY_TO_OPEN',
            quantity=2,now=self.now,valid_until=self.now+timedelta(seconds=10))
        return dict(signal_key='SIGNAL',draft=draft,first_signal_at=self.now,source_at=self.now,
            session_close=self.end,target='20')

    def step(self,provider=None):
        return self.queue.step(journal.BINDING,self.execution,provider or self.proposal)

    def single_radar(self):
        self.queue.pause(journal.BINDING)
        self.arm(first_entry_only=True,repeat_new_signals=True)
        self.now+=timedelta(seconds=1)

    def any_company(self,row):
        from dataclasses import replace
        p=self.proposal(self.rows[0])
        p.update(signal_key='SIGNAL_'+row['symbol'],target=row['target'])
        p['draft']=replace(p['draft'],contract=row['symbol']+'  261102C00350000',quantity=row['quantity'])
        return p

    def test_single_radar_reserves_before_http_and_does_not_prepare_others(self):
        self.single_radar()
        def enter(**kw):
            plan=self.queue.read(journal.BINDING)
            self.assertEqual(plan['entry_owner'],plan['rows'][0]['id'])
            self.assertTrue(all(not r['repeat_new_signals'] for r in plan['rows']))
            return dict(id='REQ',broker_id='123',state='ACKNOWLEDGED')
        self.execution.enter.side_effect=enter
        provider=Mock(side_effect=self.any_company)
        self.step(provider);provider.assert_called_once()
        self.queue=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        self.step(provider)
        self.execution.enter.assert_called_once();provider.assert_called_once()

    def test_single_partial_fill_excludes_others_and_does_not_repeat_after_close(self):
        self.single_radar();self.step(self.any_company)
        buy=dict(id='REQ',state='WORKING',fills={'x':dict(quantity=1)})
        self.execution.ledger.requests.return_value=[buy]
        self.step(self.any_company)
        plan=self.queue.read(journal.BINDING)
        self.assertTrue(plan['entry_consumed']);self.assertEqual(plan['winning_symbol'],'AAPL')
        self.assertEqual(plan['rows'][1]['state'],'EXCLUDED_FIRST_ENTRY')
        self.queue=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        buy['state']='CANCELED'
        self.execution.ledger.requests.return_value=[buy,dict(parent_id='REQ',state='FILLED',fills={'y':dict(quantity=1)})]
        self.step(self.any_company)
        self.now+=timedelta(seconds=5);self.step(self.any_company)
        plan=self.queue.read(journal.BINDING)
        self.assertEqual(plan['rows'][0]['state'],'COMPLETED')
        self.assertTrue(plan['entry_consumed']);self.execution.enter.assert_called_once()

    def test_single_terminal_zero_fill_releases_for_another_company(self):
        self.single_radar();self.step(self.any_company)
        self.execution.ledger.requests.return_value=[dict(id='REQ',state='CANCELED',fills={})]
        self.step(self.any_company)
        self.assertIsNone(self.queue.read(journal.BINDING)['entry_owner'])
        self.now+=timedelta(seconds=1)
        self.step(lambda row:self.any_company(row) if row['symbol']=='MSFT' else None)
        self.assertEqual(self.execution.enter.call_count,2)
        self.assertEqual(self.execution.enter.call_args.kwargs['draft'].quantity,1)

    def test_single_uncertain_send_freezes_all_companies_after_restart(self):
        self.single_radar();self.execution.enter.side_effect=TimeoutError()
        self.step(self.any_company)
        self.queue=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        self.step(self.any_company)
        self.execution.enter.assert_called_once()
        plan=self.queue.read(journal.BINDING)
        self.assertIsNotNone(plan['entry_owner'])
        self.assertEqual(plan['rows'][0]['state'],'REQUIRES_REVIEW')

    def test_single_proven_no_dispatch_releases_without_resetting_signal(self):
        from real_execution_service import RealEntryNotDispatched
        self.single_radar();self.execution.enter.side_effect=RealEntryNotDispatched('LIVE_ENTRY_QUOTE_CHANGED')
        self.step(self.any_company)
        self.assertIsNone(self.queue.read(journal.BINDING)['entry_owner'])
        self.execution.enter.side_effect=None
        self.step(lambda row:self.any_company(row) if row['symbol']=='MSFT' else None)
        self.assertEqual(self.execution.enter.call_count,2)

    def test_single_two_schedulers_cannot_claim_two_companies(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.single_radar();barrier=Barrier(2)
        other=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        def provider_for(symbol):
            def provider(row):
                if row['symbol']!=symbol:return None
                barrier.wait(timeout=3)
                return self.any_company(row)
            return provider
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(q.step,journal.BINDING,self.execution,provider_for(symbol),monitor=False)
                for q,symbol in ((self.queue,'AAPL'),(other,'MSFT'))]
            for future in futures:future.result(timeout=5)
        self.execution.enter.assert_called_once()

    def test_single_can_arm_before_open_and_only_buy_in_official_session(self):
        self.queue.pause(journal.BINDING)
        opening=self.now+timedelta(minutes=15)
        self.arm(first_entry_only=True,session_open=opening)
        self.step(self.any_company);self.execution.enter.assert_not_called()
        self.now=opening;self.step(self.any_company)
        self.execution.enter.assert_called_once()

    def test_arming_requires_verified_executor_and_does_not_start_io(self):
        factory=Mock();RealAutomaticQueue(store_factory=factory);factory.assert_not_called()
        other=RealAutomaticQueue(store_factory=lambda:journal.Vault(),clock=lambda:self.now)
        with self.assertRaisesRegex(RealOrderBlocked,'EXECUTOR_NOT_VERIFIED'):
            other.arm(journal.BINDING,self.rows,session_open=self.now,session_close=self.end,execution_ready=lambda:False)
        self.execution.enter.assert_not_called()
        self.assertEqual(len(self.queue.read(journal.BINDING)['rows']),2)

    def test_provider_boundary_is_transient_and_final_queue_check_remains(self):
        plan=self.queue.read(journal.BINDING)
        def provider(row):
            self.assertEqual(row['_signal_after'],plan['armed_at'])
            proposal=self.proposal(row)
            if proposal:proposal['first_signal_at']=self.now-timedelta(seconds=1)
            return proposal
        self.step(provider)
        self.execution.enter.assert_not_called()
        self.assertEqual(self.queue.read(journal.BINDING),plan)
        self.assertNotIn('_signal_after',plan['rows'][0])

    def test_remove_keeps_audit_and_other_authorizations_and_survives_restart(self):
        plan=self.queue.read(journal.BINDING);row=plan['rows'][0]
        after=self.queue.remove(journal.BINDING,plan['id'],row['id'])
        self.assertEqual(after['rows'][0]['state'],'REMOVED')
        self.assertFalse(after['rows'][0]['repeat_new_signals'])
        self.assertEqual(after['rows'][1],plan['rows'][1])
        self.assertEqual(after['armed_at'],plan['armed_at']);self.assertFalse(after['paused'])
        self.queue=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        provider=Mock(return_value=None);self.step(provider)
        self.assertEqual([c.args[0]['symbol'] for c in provider.call_args_list],['MSFT'])
        self.execution.enter.assert_not_called();self.execution.poll.assert_called_once()
        self.assertEqual(self.queue.remove(journal.BINDING,plan['id'],row['id']),after)

    def test_remove_paused_row_and_rearm_only_after_explicit_action(self):
        self.queue.pause(journal.BINDING);plan=self.queue.read(journal.BINDING)
        for row in plan['rows']:self.queue.remove(journal.BINDING,plan['id'],row['id'])
        self.assertTrue(self.queue.read(journal.BINDING)['paused'])
        fresh=self.arm()
        self.assertTrue(all(r['state']=='ARMED' for r in fresh['rows']))
        self.assertEqual([r['state'] for r in fresh['history'][-1]['rows']],['REMOVED','REMOVED'])

    def test_remove_refuses_stale_plan_and_rows_with_claims_or_orders(self):
        plan=self.queue.read(journal.BINDING)
        with self.assertRaisesRegex(RealOrderBlocked,'QUEUE_CHANGED'):
            self.queue.remove(journal.BINDING,'OLD',plan['rows'][0]['id'])
        for changes in (dict(state='SUBMITTING'),dict(state='ORDER_SENT'),dict(claim='SIGNAL'),dict(request_id='REQ')):
            self.vault.data['profiles'][journal.BINDING]=deepcopy(plan)
            self.vault.data['profiles'][journal.BINDING]['rows'][0].update(changes)
            before=deepcopy(self.vault.data)
            with self.assertRaisesRegex(RealOrderBlocked,'ROW_ALREADY_IN_PROGRESS'):
                self.queue.remove(journal.BINDING,plan['id'],plan['rows'][0]['id'])
            self.assertEqual(self.vault.data,before)

    def test_removal_wins_before_claim_even_after_slow_preparation_started(self):
        self.single_radar();plan=self.queue.read(journal.BINDING)
        def preparing(row):
            self.queue.remove(journal.BINDING,plan['id'],row['id'])
            return self.any_company(row)
        with self.assertRaisesRegex(RealOrderBlocked,'QUEUE_PAUSED'):self.step(preparing)
        self.execution.enter.assert_not_called()
        after=self.queue.read(journal.BINDING)
        self.assertIsNone(after['entry_owner']);self.assertEqual(after['rows'][0]['state'],'REMOVED')
        self.assertEqual(after['rows'][1],plan['rows'][1])

    def test_claim_wins_before_removal_and_reservation_remains(self):
        self.single_radar();self.step(self.any_company)
        plan=self.queue.read(journal.BINDING);row=plan['rows'][0]
        with self.assertRaisesRegex(RealOrderBlocked,'ROW_ALREADY_IN_PROGRESS'):
            self.queue.remove(journal.BINDING,plan['id'],row['id'])
        self.assertEqual(self.queue.read(journal.BINDING),plan)

    def test_claim_is_saved_before_entry_and_not_repeated_after_restart(self):
        def enter(**kw):
            row=self.queue.read(journal.BINDING)['rows'][0]
            self.assertEqual(row['state'],'SUBMITTING');self.assertEqual(row['claim'],'SIGNAL')
            return dict(id='REQ',broker_id='123',state='ACKNOWLEDGED')
        self.execution.enter.side_effect=enter
        self.step();self.queue=RealAutomaticQueue(store_factory=lambda:self.vault,clock=lambda:self.now)
        self.step();self.execution.enter.assert_called_once()

    def test_timeout_claim_stays_in_review_without_automatic_resend(self):
        self.execution.enter.side_effect=TimeoutError()
        self.step();self.step()
        row=self.queue.read(journal.BINDING)['rows'][0]
        self.assertEqual(row['state'],'REQUIRES_REVIEW');self.assertEqual(row['used_signals'],['SIGNAL'])
        self.execution.enter.assert_called_once()

    def test_proven_preparation_failure_can_retry_without_renewing_signal_clock(self):
        from real_execution_service import RealEntryNotDispatched
        self.execution.enter.side_effect=RealEntryNotDispatched('LIVE_ENTRY_QUOTE_CHANGED')
        first=self.now
        self.step()
        row=self.queue.read(journal.BINDING)['rows'][0]
        self.assertEqual(row['state'],'ARMED');self.assertEqual(row['used_signals'],[])
        self.execution.enter.side_effect=None
        self.step()
        calls=self.execution.enter.call_args_list
        self.assertEqual(calls[0].kwargs['first_signal_at'],first)
        self.assertEqual(calls[1].kwargs['first_signal_at'],first)

    def test_disk_failure_prevents_entry(self):
        self.vault.save=Mock(side_effect=OSError('SYNTHETIC_DISK_FULL'))
        with self.assertRaises(OSError):self.step()
        self.execution.enter.assert_not_called()

    def test_pause_and_session_end_prevent_buys_but_keep_exit_monitoring(self):
        self.queue.pause(journal.BINDING);self.step()
        self.execution.poll.assert_called_once();self.execution.enter.assert_not_called()
        self.now=self.end;self.step();self.assertEqual(self.execution.poll.call_count,2)
        self.assertFalse(self.queue.read(journal.BINDING)['rows'][0]['repeat_new_signals'])

    def test_expired_session_never_rolls_into_next_day(self):
        self.now=self.end;self.step()
        self.assertTrue(all(r['state']=='EXPIRED' for r in self.queue.read(journal.BINDING)['rows']))
        self.now+=timedelta(days=1);self.step();self.execution.enter.assert_not_called()

    def test_provider_cannot_change_company_quantity_target_or_session(self):
        for change in ['quantity','target','company','session']:
            def provider(row):
                p=self.proposal(row)
                if p is None:return None
                from dataclasses import replace
                if change=='quantity':p['draft']=replace(p['draft'],quantity=3)
                if change=='target':p['target']='100'
                if change=='company':p['draft']=replace(p['draft'],contract='MSFT  261102C00350000')
                if change=='session':p['session_close']+=timedelta(days=1)
                return p
            with self.assertRaises(RealOrderBlocked):self.step(provider)
        self.execution.enter.assert_not_called()

    def test_old_signal_or_signal_before_arming_never_enters(self):
        def provider(row):
            p=self.proposal(row)
            if p:p['first_signal_at']-=timedelta(seconds=1)
            return p
        self.step(provider);self.execution.enter.assert_not_called()

    def test_repetition_requires_complete_close_then_distinct_later_signal(self):
        self.step()
        buy=dict(id='REQ',state='FILLED',fills={'x':dict(quantity=2)})
        sell=dict(parent_id='REQ',state='FILLED',fills={'y':dict(quantity=2)})
        self.execution.ledger.requests.return_value=[buy,sell]
        self.now+=timedelta(seconds=2);self.step()
        self.assertEqual(self.queue.read(journal.BINDING)['rows'][0]['state'],'ARMED')
        self.step();self.execution.enter.assert_called_once()
        self.now+=timedelta(seconds=1)
        def provider(row):
            p=self.proposal(row)
            if p:p['signal_key']='NEW_SIGNAL'
            return p
        self.step(provider);self.assertEqual(self.execution.enter.call_count,2)

    def test_partial_close_or_pending_sell_does_not_rearm(self):
        self.step();self.execution.ledger.requests.return_value=[
            dict(id='REQ',state='CANCELED',fills={'x':dict(quantity=2)}),
            dict(parent_id='REQ',state='WORKING',fills={'x':dict(quantity=1)})]
        self.step();self.assertEqual(self.queue.read(journal.BINDING)['rows'][0]['state'],'ORDER_SENT')
        self.execution.enter.assert_called_once()

    def test_account_mismatch_and_unresolved_queue_cannot_be_overwritten(self):
        with self.assertRaisesRegex(RealOrderBlocked,'ALREADY_EXISTS'):self.arm()
        self.execution.binding='b'*64
        with self.assertRaisesRegex(RealOrderBlocked,'ACCOUNT_MISMATCH'):self.step()

    def test_separate_entry_turn_does_not_wait_for_order_get_polling(self):
        self.execution.poll.side_effect=AssertionError('MUST_RUN_IN_SEPARATE_MONITOR')
        self.queue.step(journal.BINDING,self.execution,self.proposal,monitor=False)
        self.execution.enter.assert_called_once();self.execution.poll.assert_not_called()
