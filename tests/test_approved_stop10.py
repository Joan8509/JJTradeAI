"""Historical stop10 with isolated quote fills, no private config/network/messages."""
from decimal import Decimal
import unittest
from unittest.mock import patch

from tests import test_manual_execution as fixture
from option_exit_plan import GlobalExitPolicy,load_global_exit_policy
from schwab_simulation import ManualPracticePolicy,ExecutionBlocked
from trade_close_reporting import sale_reports


class ApprovedStop10Tests(unittest.TestCase):
    def setUp(self):
        # Keep the superseded10 policy as a historical regression, not a default assertion.
        for name in (__name__+'.load_global_exit_policy','schwab_simulation.load_global_exit_policy','manual_execution.load_global_exit_policy'):
            context=patch(name,return_value=GlobalExitPolicy(Decimal('10'),True))
            context.start();self.addCleanup(context.stop)
    def harness(self):
        h=fixture.ManualExecutionTests('runTest');h.setUp();self.addCleanup(h.doCleanups)
        h.engine.policy=ManualPracticePolicy();h.market.increments={};h.market.fee_per_contract=None
        return h

    def historical_policy(self):
        # A prior agreed20 plan, never a second live policy or configuration write.
        from contextlib import ExitStack
        stack=ExitStack()
        for name in ('schwab_simulation.load_global_exit_policy','manual_execution.load_global_exit_policy'):
            stack.enter_context(patch(name,return_value=GlobalExitPolicy(Decimal('20'),True)))
        return stack

    def test_historical_stop10_policy_and_practice_default(self):
        self.assertEqual(load_global_exit_policy().stop_loss_pct,Decimal('10'))
        self.assertEqual(ManualPracticePolicy().require_complete().stop_loss_pct,Decimal('10'))

    def test_exact_bid_threshold_for_each_profit_choice_and_no_break_even(self):
        for target in ('10','20','35','100','MANUAL'):
            with self.subTest(target=target):
                h=self.harness();h.filled(target=target,quantity=2)
                h.quote(bid=1.800001,ask=1.84,seconds=2)
                hold=h.service.observe()[0]
                self.assertEqual(hold['status'],'HOLD');self.assertEqual(Decimal(hold['stop']),Decimal('1.80'))
                h.quote(bid=1.8,ask=1.85,seconds=3)
                result=h.service.observe()[0]
                self.assertEqual(result['reason'],'LOSS_LIMIT');self.assertEqual(result['quantity'],2)
                h.quote(bid=1.8,ask=1.85,seconds=4);h.service.observe()
                report=sale_reports(h.engine.ledger,h.engine.policy.account_alias,now=h.now)[0]
                self.assertEqual(report['gross_pnl'],Decimal('-40'));self.assertIsNone(report['net_pnl'])
                self.assertEqual(len(h.engine.broker.snapshot()),2)

    def test_position_keeps_old20_plan_after_restart_into_new10_policy(self):
        h=self.harness()
        with self.historical_policy():
            h.engine.policy=ManualPracticePolicy();h.filled(target='MANUAL')
        h.engine.policy=ManualPracticePolicy();h.service=h.build()
        h.quote(bid=1.75,ask=1.8,seconds=2)
        hold=h.service.observe()[0]
        self.assertEqual(hold['status'],'HOLD');self.assertEqual(Decimal(hold['stop']),Decimal('1.60'))
        self.assertEqual(h.service.positions()[0]['plan']['stop_pct'],'20')
        self.assertEqual(h.engine.policy.stop_loss_pct,10)

    def test_old20_review_is_not_silently_confirmed_under_new10_policy(self):
        h=self.harness()
        with self.historical_policy():
            h.engine.policy=ManualPracticePolicy();review=h.prepare()
        h.engine.policy=ManualPracticePolicy();h.service=h.build()
        with self.assertRaisesRegex(ExecutionBlocked,'REVIEW_POLICY_CHANGED'):
            h.service.confirm('owner',review['id'])
        self.assertEqual(h.engine.ledger.orders(),[])

    def test_telegram_card_and_fresh_review_show_same_stop10(self):
        from telegram_manual import TelegramManualService,TelegramManualStore
        from tests.test_telegram_manual import TOKEN,OWNER
        h=self.harness()
        service=TelegramManualService(h.service,TelegramManualStore(h.root/'telegram.db'),
            token=TOKEN,user_id=OWNER,base_url='https://jj.example/telegram/')
        draft=service.begin('AMZN','CALL',h.state['tick']['signal']['candle'])
        card=service.card(draft)
        self.assertIn('Stop loss: 10%',card['text']);self.assertNotIn('Stop loss: 20%',card['text'])
        review=h.prepare(target='35')
        self.assertEqual(review['stop'],'10');self.assertEqual(review['target'],'35')
