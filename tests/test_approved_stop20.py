"""Current global stop20 and immutable historical plans; synthetic positions only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from option_exit_plan import (ExitPlan, ExitPlanConfirmation, ManualCloseConfirmation,
    PROFIT_PERCENT_CHOICES, load_global_exit_policy, GlobalExitPolicy)
from schwab_simulation import (SimulationEngine,SimulationLedger,LocalPaperBroker,
    policy_from_dict,ExecutionBlocked)
from tests import test_schwab_simulation as fixtures

NOW=fixtures.NOW
contract=fixtures.synthetic_contract


class ApprovedStopPolicyTests(unittest.TestCase):
    def test_public_policy_uses_stop20_manual_and_real_order_block(self):
        global_exit=load_global_exit_policy()
        self.assertEqual(global_exit.stop_loss_pct,Decimal('20'))
        from schwab_simulation import ManualPracticePolicy
        self.assertEqual(ManualPracticePolicy().require_complete().stop_loss_pct,Decimal('20'))
        self.assertTrue(global_exit.manual_close_available)
        root=Path(__file__).resolve().parents[1]
        payload=json.loads((root/'config/schwab_automation.example.json').read_text())
        self.assertIs(payload['real_orders_enabled'],False)
        self.assertEqual(policy_from_dict(payload).stop_loss_pct,Decimal('20'))
        with self.assertRaisesRegex(ExecutionBlocked,'POLICY_INCOMPLETE'):
            policy_from_dict(payload).require_complete()
        for stop in (5,10,15,25):
            with self.assertRaisesRegex(ExecutionBlocked,'GLOBAL_STOP_POLICY_MISMATCH'):
                policy_from_dict(payload|{'stop_loss_pct':stop})

    def test_missing_or_invalid_global_policy_never_assumes_a_stop_or_enables_orders(self):
        root=Path(__file__).resolve().parents[1]
        source=json.loads((root/'config/option_exit_policy.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'policy.json'
            with self.assertRaisesRegex(ValueError,'GLOBAL_EXIT_POLICY_UNAVAILABLE'):
                load_global_exit_policy(path)
            for changes in ({'stop_loss_pct':None},{'stop_loss_pct':True},{'stop_loss_pct':100},
                    {'stop_loss_pct':'NaN'},{'manual_close_available':False},
                    {'real_orders_enabled':True},{'stop_scope':'BY_SYMBOL'},{'schema_version':True}):
                with self.subTest(changes=changes):
                    path.write_text(json.dumps(source|changes),encoding='utf-8')
                    with self.assertRaisesRegex(ValueError,'GLOBAL_EXIT_POLICY_UNAVAILABLE'):
                        load_global_exit_policy(path)


class ApprovedStopSimulationTests(unittest.TestCase):
    def setUp(self):
        fixtures.SchwabSimulationTests.setUp(self)
        # Keep the old20% regression cases explicit: changing today's default
        # must never rewrite a plan already attached to an earlier position.
        context=patch(__name__+'.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('20'),True))
        context.start();self.addCleanup(context.stop)
    enter=fixtures.SchwabSimulationTests.enter
    confirmation=fixtures.SchwabSimulationTests.confirmation
    fill=fixtures.SchwabSimulationTests.fill

    def prepare(self,pct=Decimal('35')):
        self.policy=replace(fixtures.synthetic_policy(),stop_loss_pct=load_global_exit_policy().stop_loss_pct)
        self.run_number=getattr(self,'run_number',0)+1
        self.ledger=SimulationLedger(self.root/f'ledger20_{self.run_number}.db')
        self.broker=LocalPaperBroker(self.root/f'broker20_{self.run_number}.db')
        self.engine=SimulationEngine(self.ledger,self.broker,self.policy)
        plan=ExitPlan('TARGET_PERCENT' if pct is not None else 'MANUAL',pct,self.policy.stop_loss_pct,30)
        return self.enter(exit_confirmation=ExitPlanConfirmation(self.confirmation(),plan,NOW))

    def close_review(self,bid,now,quantity=3):
        position=self.ledger.portfolio()[contract().snapshot.symbol]
        return ManualCloseConfirmation(self.policy.account_alias,position['entry_client_key'],
            contract().snapshot.symbol,quantity,Decimal(bid),now)

    def test_stop_triggers_at_exact_20_for_every_profit_mode_but_not_above(self):
        for pct in (*PROFIT_PERCENT_CHOICES,None):
            with self.subTest(target=pct):
                self.fill(self.prepare(pct))
                now=NOW+timedelta(seconds=3)
                hold=self.engine.manage_exit(contract(now,bid=1.65,ask=1.7),self.controls,now)
                self.assertEqual(hold['status'],'HOLD');self.assertEqual(Decimal(hold['stop']),Decimal('1.60'))
                result=self.engine.manage_exit(contract(now,bid=1.6,ask=1.65),self.controls,now)
                self.assertEqual(result['reason'],'LOSS_LIMIT');self.assertEqual(result['quantity'],3)
                self.assertEqual(Decimal(result['limit']),Decimal('1.60'))

    def test_manual_close_before_stop_is_available_with_or_without_profit_target(self):
        for pct in (Decimal('35'),None):
            with self.subTest(target=pct):
                self.fill(self.prepare(pct));now=NOW+timedelta(seconds=3)
                q=contract(now,bid=1.9,ask=1.95)
                result=self.engine.close_position(q,self.controls,now,confirmation=self.close_review('1.90',now))
                self.assertEqual(result['reason'],'MANUAL_CLOSE');self.assertEqual(result['quantity'],3)
                self.assertEqual(Decimal(result['limit']),Decimal('1.90'))
                stopped=self.engine.manage_exit(contract(now,bid=1.6,ask=1.65),self.controls,now)
                self.assertEqual(stopped['status'],'EXIT_ALREADY_PENDING')
                self.assertEqual(len(self.broker.snapshot()),2)

    def test_stop20_uses_actual_fill_vwap_and_not_intended_entry_ask(self):
        key=self.prepare(None)
        self.fill(key,quantity=1,bid=1.9,ask=1.95)
        self.fill(key,quantity=2,offset=2,identity='entry-two')
        now=NOW+timedelta(seconds=3)
        hold=self.engine.manage_exit(contract(now,bid=1.6,ask=1.65),self.controls,now)
        self.assertEqual(hold['status'],'HOLD')
        average=Decimal('595')/Decimal('300')
        self.assertEqual(Decimal(hold['stop']),average*Decimal('.8'))
        result=self.engine.manage_exit(contract(now,bid=1.55,ask=1.6),self.controls,now)
        self.assertEqual(result['reason'],'LOSS_LIMIT')

    def test_manual_and_stop20_race_have_only_one_pending_sell(self):
        self.fill(self.prepare(None));now=NOW+timedelta(seconds=3)
        q=contract(now,bid=1.6,ask=1.65);review=self.close_review('1.60',now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            stop=pool.submit(self.engine.manage_exit,q,self.controls,now)
            manual=pool.submit(self.engine.close_position,q,self.controls,now,confirmation=review)
            results=[stop.result(),manual.result()]
        self.assertEqual(sorted(row['status'] for row in results),['EXIT_ALREADY_PENDING','EXIT_WORKING'])
        self.assertEqual(len(self.broker.snapshot()),2)

    def test_partial_entry_stop_waits_for_cancel_ack_and_sells_only_filled(self):
        key=self.prepare(None);self.fill(key,quantity=1)
        now=NOW+timedelta(seconds=3);q=contract(now,bid=1.6,ask=1.65)
        with self.assertRaisesRegex(ExecutionBlocked,'CANCELLATION'):
            self.engine.manage_exit(q,self.controls,now)
        self.broker.acknowledge_cancel(self.ledger.order(key)['broker_id'])
        with self.assertRaises(ExecutionBlocked):
            self.engine.manage_exit(q,self.controls,now)
        self.engine.reconcile(now)
        self.assertEqual(self.engine.manage_exit(q,self.controls,now)['quantity'],1)

    def test_existing_stop20_plan_survives_restart_and_later_policy_change(self):
        self.fill(self.prepare(None));now=NOW+timedelta(seconds=3)
        self.engine=SimulationEngine(self.ledger,self.broker,replace(self.policy,stop_loss_pct=Decimal('10')))
        hold=self.engine.manage_exit(contract(now,bid=1.75,ask=1.8),self.controls,now)
        self.assertEqual(hold['status'],'HOLD');self.assertEqual(Decimal(hold['stop']),Decimal('1.60'))
        result=self.engine.manage_exit(contract(now,bid=1.6,ask=1.65),self.controls,now)
        self.assertEqual(result['reason'],'LOSS_LIMIT')


if __name__=='__main__':unittest.main()
