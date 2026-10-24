"""Exit policy and shared local close claims, with synthetic fills only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

from option_exit_plan import (ExitPlan, ExitPlanConfirmation, ManualCloseConfirmation,
    PROFIT_PERCENT_CHOICES, require_exit_plan)
from schwab_simulation import SimulationEngine, ExecutionBlocked
from tests import test_schwab_simulation as fixtures

NOW=fixtures.NOW
synthetic_contract=fixtures.synthetic_contract


class ExitPlanTests(unittest.TestCase):
    def test_selected_targets_and_gross_levels_on_verified_tick(self):
        for pct, expected in zip(PROFIT_PERCENT_CHOICES, ('1.10','1.20','1.35','2.00')):
            plan=ExitPlan('TARGET_PERCENT',pct,Decimal('10'),30)
            self.assertEqual(plan.levels('1.00','.05'),(Decimal(expected),Decimal('.90')))
        # Target rounds up; no promise of a fill or of net profit after fees.
        self.assertEqual(ExitPlan('TARGET_PERCENT',Decimal('35'),Decimal('10'),30)
            .levels('1.983333333333333333333333333','.05')[0],Decimal('2.70'))

    def test_missing_invalid_or_unapproved_numbers_are_not_defaults(self):
        base=ExitPlan('TARGET_PERCENT',Decimal('20'),Decimal('10'),30)
        for changes in ({'target_return_pct':None},{'target_return_pct':25},
                {'target_return_pct':True},{'stop_loss_pct':None},{'stop_loss_pct':True},
                {'stop_loss_pct':0},{'stop_loss_pct':100},{'stop_loss_pct':'NaN'},
                {'max_holding_minutes':True},{'profit_mode':'UNKNOWN'},
                {'profit_mode':'MANUAL'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(base,**changes).validated()
        self.assertIsNone(ExitPlan('MANUAL',None,Decimal('10'),30).levels('1','.05')[0])


class ExitSimulationTests(unittest.TestCase):
    setUp=fixtures.SchwabSimulationTests.setUp
    enter=fixtures.SchwabSimulationTests.enter
    confirmation=fixtures.SchwabSimulationTests.confirmation
    fill=fixtures.SchwabSimulationTests.fill

    def open_plan(self, pct=Decimal('35'), mode='TARGET_PERCENT', **changes):
        plan=replace(ExitPlan(mode,pct,Decimal('10'),30),**changes)
        review=ExitPlanConfirmation(self.confirmation(),plan,NOW)
        return self.enter(exit_confirmation=review)

    def close_review(self, bid='2.10', quantity=3, **changes):
        position=self.ledger.portfolio()[synthetic_contract().snapshot.symbol]
        return replace(ManualCloseConfirmation('SYNTHETIC_ACCOUNT',position['entry_client_key'],
            synthetic_contract().snapshot.symbol,quantity,Decimal(bid),NOW+timedelta(seconds=3)),**changes)

    def test_per_trade_35_target_uses_actual_partial_fills_and_survives_restart(self):
        key=self.open_plan()
        self.fill(key,quantity=1,bid=1.9,ask=1.95)
        self.fill(key,quantity=2,offset=2,identity='entry-two')
        self.engine=SimulationEngine(self.ledger,self.broker,self.policy)
        now=NOW+timedelta(seconds=3)
        hold=self.engine.manage_exit(synthetic_contract(now,bid=2.65,ask=2.7),self.controls,now)
        self.assertEqual(hold['status'],'HOLD');self.assertEqual(hold['target'],'2.70')
        result=self.engine.manage_exit(synthetic_contract(now,bid=2.7,ask=2.75),self.controls,now)
        self.assertEqual(result['reason'],'TARGET');self.assertEqual(Decimal(result['limit']),Decimal('2.70'))
        self.assertEqual(result['quantity'],3)

    def test_exit_review_is_bound_to_entry_and_fresh_time(self):
        entry=self.confirmation();plan=ExitPlan('TARGET_PERCENT',Decimal('10'),Decimal('10'),30)
        review=ExitPlanConfirmation(entry,plan,NOW)
        for changed in (replace(review,entry_review=replace(entry,quantity=2)),
                replace(review,confirmed_at=NOW-timedelta(seconds=31)),
                replace(review,confirmed_at=NOW+timedelta(microseconds=1)),
                replace(review,confirmed_at=NOW.replace(tzinfo=None))):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                require_exit_plan(changed,entry,NOW)
        self.assertEqual(require_exit_plan(review,entry,NOW),plan)

    def test_global_stop_cannot_vary_per_trade_and_time_cannot_weaken_policy(self):
        for changes,code in (({'stop_loss_pct':Decimal('11')},'GLOBAL_STOP_POLICY_MISMATCH'),
                ({'stop_loss_pct':Decimal('9')},'GLOBAL_STOP_POLICY_MISMATCH'),
                ({'max_holding_minutes':31},'HOLDING_TIME_EXCEEDS_POLICY_LIMIT')):
            with self.subTest(changes=changes),self.assertRaisesRegex(ExecutionBlocked,code):
                self.open_plan(**changes)
        self.assertEqual(self.ledger.orders(),[]);self.assertEqual(self.broker.snapshot(),[])

    def test_manual_profit_does_not_disable_loss_limit_or_pause_position_management(self):
        key=self.open_plan(pct=None,mode='MANUAL');self.fill(key)
        self.ledger.set_paused(True)
        now=NOW+timedelta(seconds=3)
        hold=self.engine.manage_exit(synthetic_contract(now,bid=4.1,ask=4.15),self.controls,now)
        self.assertEqual(hold['status'],'HOLD');self.assertIsNone(hold['target'])
        stopped=self.engine.manage_exit(synthetic_contract(now,bid=1.7,ask=1.75),self.controls,now)
        self.assertEqual(stopped['reason'],'LOSS_LIMIT');self.assertEqual(stopped['quantity'],3)
        self.assertEqual(stopped['limit'],'1.70')

    def test_manual_close_below_target_is_one_pending_exit_and_keeps_original_account(self):
        key=self.open_plan();self.fill(key)
        # Changing account for new entries never reassigns an existing position.
        self.engine.policy=replace(self.policy,account_alias='OTHER_SYNTHETIC_ACCOUNT')
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.1,ask=2.2)
        review=self.close_review()
        result=self.engine.close_position(q,self.controls,now,confirmation=review)
        self.assertEqual(result['reason'],'MANUAL_CLOSE');self.assertEqual(result['quantity'],3)
        self.assertEqual(self.ledger.order(result['client_key'])['order']['account_alias'],'SYNTHETIC_ACCOUNT')
        second=self.engine.close_position(q,self.controls,now,confirmation=review)
        self.assertEqual(second['status'],'EXIT_ALREADY_PENDING')
        self.assertEqual(self.engine.manage_exit(q,self.controls,now)['status'],'EXIT_ALREADY_PENDING')
        self.assertEqual(len(self.broker.snapshot()),2)

    def test_manual_close_rejects_changed_or_missing_review_without_submission(self):
        self.fill(self.open_plan())
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.1,ask=2.15)
        review=self.close_review()
        for changed in (None,replace(review,quantity=2),replace(review,account_alias='OTHER'),
                replace(review,minimum_price=Decimal('2.05')),
                replace(review,entry_client_key='ANOTHER_ENTRY'),
                replace(review,confirmed_at=now+timedelta(seconds=1)),
                replace(review,confirmed_at=now-timedelta(seconds=31))):
            with self.subTest(changed=changed),self.assertRaises(ExecutionBlocked):
                self.engine.close_position(q,self.controls,now,confirmation=changed)
        self.assertEqual(len(self.broker.snapshot()),1)

    def test_manual_close_requires_entry_cancel_ack_and_reconciliation_for_partial_entry(self):
        key=self.open_plan();self.fill(key,quantity=1)
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.1,ask=2.15)
        review=self.close_review(quantity=1)
        with self.assertRaisesRegex(ExecutionBlocked,'CANCELLATION'):
            self.engine.close_position(q,self.controls,now,confirmation=review)
        self.broker.acknowledge_cancel(self.ledger.order(key)['broker_id'])
        with self.assertRaises(ExecutionBlocked):
            self.engine.close_position(q,self.controls,now,confirmation=review)
        self.engine.reconcile(now)
        result=self.engine.close_position(q,self.controls,now,confirmation=review)
        self.assertEqual(result['quantity'],1)

    def test_concurrent_manual_and_target_share_one_durable_exit_claim(self):
        self.fill(self.open_plan(pct=Decimal('20')))
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.45,ask=2.5)
        review=self.close_review(bid='2.45')
        with ThreadPoolExecutor(max_workers=2) as pool:
            automatic=pool.submit(self.engine.manage_exit,q,self.controls,now)
            manual=pool.submit(self.engine.close_position,q,self.controls,now,confirmation=review)
            results=[automatic.result(),manual.result()]
        self.assertEqual(sorted(r['status'] for r in results),['EXIT_ALREADY_PENDING','EXIT_WORKING'])
        self.assertEqual(len(self.broker.snapshot()),2)

    def test_triggered_loss_limit_can_remain_unfilled_after_a_price_gap(self):
        self.fill(self.open_plan())
        now=NOW+timedelta(seconds=3)
        result=self.engine.manage_exit(synthetic_contract(now,bid=1.8,ask=1.85),self.controls,now)
        self.assertEqual(result['reason'],'LOSS_LIMIT')
        self.assertEqual(self.fill(result['client_key'],bid=1.6,ask=1.65,offset=4,identity='gap'),0)
        position=self.ledger.portfolio()[synthetic_contract().snapshot.symbol]
        self.assertEqual(position['quantity'],3)
        self.assertEqual(self.ledger.order(result['client_key'])['status'],'WORKING')

    def test_unknown_manual_close_ack_is_reconciled_without_second_order(self):
        self.fill(self.open_plan())
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.1,ask=2.15)
        accept=self.broker.accept
        def lost_ack(key, order):
            accept(key,order)
            raise TimeoutError('Synthetic acknowledgement loss')
        with patch.object(self.broker,'accept',side_effect=lost_ack):
            result=self.engine.close_position(q,self.controls,now,confirmation=self.close_review())
        self.assertEqual(result['status'],'EXIT_UNCERTAIN')
        self.assertEqual(self.ledger.order(result['client_key'])['status'],'UNKNOWN')
        self.engine=SimulationEngine(self.ledger,self.broker,self.policy)
        repeated=self.engine.close_position(q,self.controls,now,confirmation=self.close_review())
        self.assertEqual(repeated['status'],'EXIT_ALREADY_PENDING')
        self.assertEqual(len(self.broker.snapshot()),2)
        self.assertEqual(self.engine.reconcile(now)['status'],'RECONCILED')
        self.assertEqual(self.ledger.order(result['client_key'])['status'],'WORKING')

    def test_manual_close_does_not_ignore_stale_quote_or_closed_session(self):
        self.fill(self.open_plan())
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.1,ask=2.15)
        review=self.close_review()
        with self.assertRaisesRegex(ExecutionBlocked,'EXIT_QUOTE_UNUSABLE'):
            self.engine.close_position(q,self.controls,now+timedelta(seconds=31),confirmation=review)
        with self.assertRaisesRegex(ExecutionBlocked,'OUTSIDE_OFFICIAL_SESSION'):
            self.engine.close_position(q,self.controls,self.controls.session_closes,confirmation=review)
        self.assertEqual(len(self.broker.snapshot()),1)

    def test_cancelled_manual_review_cannot_be_replayed_as_a_new_close(self):
        self.fill(self.open_plan())
        now=NOW+timedelta(seconds=3);q=synthetic_contract(now,bid=2.1,ask=2.15)
        review=self.close_review()
        result=self.engine.close_position(q,self.controls,now,confirmation=review)
        self.broker.acknowledge_cancel(self.ledger.order(result['client_key'])['broker_id'])
        self.engine.reconcile(now)
        repeated=self.engine.close_position(q,self.controls,now,confirmation=review)
        self.assertEqual(repeated['status'],'EXIT_REVIEW_ALREADY_USED')
        self.assertEqual(len(self.broker.snapshot()),2)


if __name__=='__main__':unittest.main()
