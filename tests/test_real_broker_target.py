"""Broker-held profit target, zero production credentials/orders or notices."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
import json

from tests import test_real_execution_service as cycle
from tests import test_real_order_ledger as journal
from real_broker_target import BrokerProfitTargets
from schwab_preview_client import wire_payload
from schwab_target_limit import target_candidate,confirm_target_preview


class BrokerTargetTests(TestCase):
    def setUp(self):
        self.f=cycle.RealExecutionCycleTests();self.f.setUp()
        self.preview=Mock();self.preview.preview.side_effect=self.report
        self.targets=BrokerProfitTargets(self.f.service,self.preview,clock=lambda:self.f.now)

    def report(self,draft):
        wire=wire_payload(draft,'12345678',self.f.now,'ORDER_REQUEST_V1')
        return dict(source='SCHWAB_PREVIEW_ENDPOINT',state='PREVIEW_NO_REJECTION_REPORTED',blockers=[],
            request_wire_format='ORDER_REQUEST_V1',request_fingerprint=sha256(json.dumps(wire,sort_keys=True,separators=(',',':')).encode()).hexdigest())

    def native(self):
        self.buy=self.f.own(target='10');self.targets.step()
        return self.f.ledger.requests(journal.BINDING)[-1]

    def test_every_dashboard_target_uses_confirmed_cost_and_exact_chosen_percentage(self):
        for goal,price in [('10','1.10'),('20','1.20'),('35','1.35'),('100','2.00')]:
            with self.subTest(goal=goal):
                self.setUp();self.f.own(target=goal);self.targets.step()
                self.assertEqual(self.f.ledger.requests(journal.BINDING)[-1]['limit'],price)

    def test_preview_disconnect_recovers_without_order_duplication(self):
        self.f.own(target='10');self.preview.preview.side_effect=TimeoutError()
        self.targets.step();self.assertEqual(self.f.gateway.submit.call_count,1)
        self.preview.preview.side_effect=self.report;self.targets.step()
        self.assertEqual(self.f.gateway.submit.call_count,1)
        self.f.now+=timedelta(seconds=15);self.targets.step();self.targets.step()
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_order_read_disconnect_then_partial_target_fill_stop_sells_only_remaining(self):
        row=self.native();self.f.service.read_order=Mock(side_effect=TimeoutError())
        self.f.bid='.80';self.f.ask='.82';self.f.service.poll()
        self.assertEqual(self.f.gateway.submit.call_count,2)
        # Cancellation acknowledgement alone never releases the reserved size.
        self.f.service.read_order=lambda identity:self.f.responses[identity]
        self.f.broker(row,1,'CANCELED','1.10')
        close=self.f.service.poll()[-1]
        self.assertEqual(close['instruction'],'SELL_TO_CLOSE');self.assertEqual(close['quantity'],1)
        self.assertEqual(close['limit'],'0.8')

    def test_profit_limit_is_posted_below_target_without_waiting_for_price(self):
        row=self.native()
        self.assertEqual(row['exit_role'],'BROKER_TARGET')
        self.assertEqual(row['limit'],'1.10');self.assertEqual(row['instruction'],'SELL_TO_CLOSE')
        self.assertEqual(self.f.gateway.submit.call_count,2)
        parent=self.f.ledger.requests(journal.BINDING)[0]
        self.assertIsNone(parent.get('exit_trigger'))
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,row['contract']),0)

    def test_baba_target_uses_actual_fifty_cent_fill_not_fifty_one_cent_ask(self):
        self.f.bid='.49';self.f.ask='.51';buy=self.f.enter(target='10')
        self.f.broker(buy,2,'FILLED','.50');self.f.service.poll();self.targets.step()
        row=self.f.ledger.requests(journal.BINDING)[-1]
        self.assertEqual(row['limit'],'0.55')
        self.assertEqual(row['state'],'ACKNOWLEDGED')

    def test_only_final_confirmed_quantity_can_get_a_profit_order(self):
        buy=self.f.enter(target='10');self.targets.step();self.preview.preview.assert_not_called()
        self.f.broker(buy,1,'WORKING');self.f.service.poll();self.targets.step()
        self.preview.preview.assert_not_called()

    def test_native_day_order_is_not_canceled_when_its_submission_draft_expires(self):
        row=self.native();self.f.broker(row,0,'WORKING')
        self.f.now+=timedelta(minutes=2);self.f.bid='1.10';self.f.ask='1.12'
        self.f.service.poll();self.targets.step()
        self.f.gateway.cancel.assert_not_called();self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_stop_cancels_native_profit_confirms_then_sells_remaining_at_bid(self):
        row=self.native();self.f.broker(row,0,'WORKING');self.f.bid='.80';self.f.ask='.82'
        canceled=self.f.service.poll()[-1]
        self.assertEqual(canceled['state'],'PENDING_CANCEL')
        self.targets.step();self.assertEqual(self.f.gateway.submit.call_count,2)
        self.f.broker(row,0,'CANCELED');close=self.f.service.poll()[-1]
        self.assertEqual(close['limit'],'0.8');self.assertNotEqual(close.get('exit_role'),'BROKER_TARGET')
        self.targets.step();self.assertEqual(self.f.gateway.submit.call_count,3)

    def test_restart_does_not_duplicate_accepted_or_uncertain_profit_order(self):
        row=self.native();self.f.service._drafts={};self.f.service._target_permits={}
        restarted=BrokerProfitTargets(self.f.service,self.preview,clock=lambda:self.f.now)
        restarted.step();self.assertEqual(self.f.gateway.submit.call_count,2)
        self.f.vault.data['requests'][row['id']]['state']='UNCERTAIN'
        restarted.step();self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_profit_fill_finishes_owned_position_and_no_second_sell(self):
        row=self.native();self.f.broker(row,2,'FILLED','1.10')
        self.f.service.poll();self.targets.step()
        self.assertEqual(self.f.gateway.submit.call_count,2)
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,row['contract']),0)

    def test_failed_or_mismatched_preview_creates_no_native_order_and_price_exit_still_works(self):
        self.f.own(target='10')
        self.preview.preview.return_value={};self.preview.preview.side_effect=None
        self.targets.step();self.assertEqual(self.f.gateway.submit.call_count,1)
        self.f.bid='1.1';self.f.ask='1.12'
        sale=self.f.service.monitor_positions()[-1]
        self.assertEqual(sale['instruction'],'SELL_TO_CLOSE')

    def test_stop_during_slow_preview_blocks_target_dispatch(self):
        self.f.own(target='10')
        def preview(draft):
            self.f.bid='.8';self.f.ask='.82';self.f.service.monitor_positions()
            return self.report(draft)
        self.preview.preview.side_effect=preview;self.targets.step()
        rows=self.f.ledger.requests(journal.BINDING)
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[-1].get('exit_role'),'BROKER_TARGET')

    def test_preview_proof_must_match_exact_price_and_wire_account(self):
        buy=self.f.own(target='10')
        draft=target_candidate(buy['contract'],2,'1','10',now=self.f.now,valid_until=self.f.now+timedelta(seconds=10))
        report=self.report(draft);report['request_fingerprint']='a'*64
        with self.assertRaises(Exception):confirm_target_preview(draft,report,binding=journal.BINDING,
            parent_id=buy['id'],account_number='12345678',now=self.f.now)
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_rounding_candidate_never_lowers_goal_and_is_not_an_order_grant(self):
        draft=target_candidate(journal.CONTRACT,1,'.50','35',now=self.f.now,valid_until=self.f.now+timedelta(seconds=10))
        self.assertEqual(str(draft.limit),'0.68');self.assertEqual(draft.price_validation,'PREVIEW_ONLY')

    def test_final_transport_guard_blocks_target_after_stop_latches(self):
        row=self.native()
        self.f.vault.data['requests'][row['id']]['state']='SUBMITTING'
        current=self.f.ledger.requests(journal.BINDING)[-1]
        self.assertTrue(self.f.service.commit_guard(current,'SUBMIT'))
        self.f.ledger.trigger_exit(journal.BINDING,self.buy['id'],'STOP')
        self.assertFalse(self.f.service.commit_guard(current,'SUBMIT'))

    def test_profit_order_can_be_prepared_without_waiting_for_a_quote(self):
        buy=self.f.own(target='10');self.f.service.quote_contract=Mock(side_effect=TimeoutError())
        self.targets.step()
        self.assertEqual(self.f.gateway.submit.call_count,2)
        self.f.service.quote_contract.assert_not_called()

    def test_expired_unsent_target_reservation_is_released_even_after_stop(self):
        row=self.native()
        saved=self.f.vault.data['requests'][row['id']]
        saved.update(state='PREPARED',broker_id=None)
        self.f.ledger.trigger_exit(journal.BINDING,self.buy['id'],'STOP')
        self.f.now+=timedelta(seconds=11);self.f.bid='.8';self.f.ask='.82'
        sale=self.f.service.monitor_positions()[-1]
        self.assertEqual(sale['limit'],'0.8')
        self.assertEqual(self.f.ledger.requests(journal.BINDING)[1]['state'],'EXPIRED')

    def test_validated_target_serializes_through_real_gateway_without_http(self):
        from schwab_order_gateway import SchwabOrderGateway
        row=self.native()
        gateway=SchwabOrderGateway(account_hash='HASH',account_binding=journal.BINDING,oauth=Mock(),
            draft_provider=self.f.service.draft_for,commit_guard=self.f.service.commit_guard,utcnow=lambda:self.f.now)
        payload=gateway._payload(row)
        self.assertEqual(payload['price'],'1.10')
        self.assertEqual(payload['orderType'],'LIMIT');self.assertEqual(payload['duration'],'DAY')
        self.assertEqual(payload['orderLegCollection'][0]['instruction'],'SELL_TO_CLOSE')

    def test_unknown_increments_never_allow_a_bare_computed_limit_to_bypass_preview(self):
        buy=self.f.own(target='10')
        draft=target_candidate(buy['contract'],2,'1','10',now=self.f.now,valid_until=self.f.now+timedelta(seconds=10))
        with self.assertRaises(Exception):self.f.service.place_broker_target(buy['id'],draft,{})
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_working_target_notice_is_separate_from_fill_and_is_not_duplicated(self):
        from real_trade_notices import RealTradeNotices
        store=journal.Vault();sender=Mock(return_value={'message_id':1})
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:store,sender=sender,clock=lambda:self.f.now)
        notices.initialize();row=self.native();notices.step()
        self.assertEqual(sender.call_count,1)  # Buy fill, not mere order receipt.
        self.f.broker(row,0,'WORKING');self.f.service.observe_orders();notices.step();notices.step()
        self.assertEqual(sender.call_count,2)
        self.assertIn('OBJETIVO REAL COLOCADO EN SCHWAB',sender.call_args.args[0])

    def test_preview_failure_produces_one_pending_notice_without_claiming_a_sale(self):
        from real_trade_notices import RealTradeNotices
        store=journal.Vault();sender=Mock(return_value={'message_id':1})
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:store,sender=sender,clock=lambda:self.f.now)
        notices.initialize();self.f.own(target='10');notices.step();sender.reset_mock()
        self.preview.preview.side_effect=TimeoutError();self.targets.step()
        notices.target_status_provider=self.targets.status;notices.step();notices.step()
        sender.assert_called_once();self.assertIn('OBJETIVO REAL PENDIENTE',sender.call_args.args[0])
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_uncertain_order_requires_review_and_never_claims_fallback_can_sell(self):
        row=self.native()
        self.f.vault.data['requests'][row['id']]['state']='UNCERTAIN'
        self.targets.step()
        self.assertTrue(self.targets.status()[row['contract']]['review'])
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_slow_target_preview_does_not_hold_price_monitor_and_late_proposal_cannot_duplicate(self):
        from threading import Thread,Event
        self.f.own(target='10');started=Event();release=Event();sold=Event()
        def preview(draft):started.set();release.wait(3);return self.report(draft)
        self.preview.preview.side_effect=preview
        thread=Thread(target=self.targets.step,daemon=True);thread.start()
        price_thread=None
        try:
            self.assertTrue(started.wait(1));self.f.bid='1.1';self.f.ask='1.12'
            price_thread=Thread(target=lambda:(self.f.service.monitor_positions(),sold.set()),daemon=True)
            price_thread.start();self.assertTrue(sold.wait(1))
        finally:
            release.set();thread.join(1)
            if price_thread:price_thread.join(1)
        self.assertEqual(self.f.gateway.submit.call_count,2)
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),2)

    def test_cancel_race_fills_profit_order_and_does_not_sell_another_contract(self):
        row=self.native();self.f.broker(row,0,'WORKING');self.f.bid='.8';self.f.ask='.82'
        self.f.service.poll()
        self.f.broker(row,2,'FILLED','1.10');self.f.service.poll();self.targets.step()
        self.assertEqual(self.f.gateway.submit.call_count,2)
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,row['contract']),0)
