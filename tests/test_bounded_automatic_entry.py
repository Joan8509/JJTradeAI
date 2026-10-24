"""Fresh synthetic quotes, bounded queue cap and immutable stops; no network."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import unittest
from tests import test_automatic_entry_queue as fixtures
from option_exit_plan import GlobalExitPolicy
from schwab_simulation import ManualPracticePolicy,ExecutionBlocked


class BoundedAutomaticEntryTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        for name in ('schwab_simulation.load_global_exit_policy','manual_execution.load_global_exit_policy'):
            context=patch(name,return_value=GlobalExitPolicy(Decimal('20'),True))
            context.start();self.addCleanup(context.stop)
        self.h.f.engine.policy=ManualPracticePolicy()

    def dispatch(self,quantity=1,target='MANUAL'):
        self.h.arm(quantity=quantity,target=target);self.h.runner.step()
        return self.h.plan()['client_key']

    def test_first_post_order_ask_can_rise_inside_authorized_cap(self):
        h=self.h;key=self.dispatch()
        row=h.f.engine.ledger.order(key)
        self.assertEqual(row['order']['limit'],'2.3')
        self.assertEqual(row['order']['reviewed_entry_cost'],'230.0')
        self.assertEqual(row['order']['plan']['stop_pct'],'20')
        self.assertTrue(h.f.service.observation_requested.is_set())
        self.assertEqual(row['filled_quantity'],0)
        h.f.quote(bid=2.05,ask=2.1,seconds=1);h.f.service.observe()
        filled=h.f.engine.ledger.order(key)
        self.assertEqual(filled['average_fill'],'2.1')
        self.assertEqual(filled['status'],'FILLED')
        self.assertEqual(len(h.f.engine.ledger.orders()),1)

    def test_outside_price_cap_cannot_fill_then_expires_without_retry(self):
        h=self.h;key=self.dispatch()
        h.f.quote(bid=2.35,ask=2.4,seconds=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['filled_quantity'],0)
        h.f.quote(seconds=10);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['status'],'CANCELED')
        h.runner.step();h.f.quote(seconds=270);h.f.service.observe();h.runner.step()
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertEqual(h.f.engine.ledger.order(key)['filled_quantity'],0)
        self.assertEqual(len(h.store.read('SELECT * FROM queue_attempts')),1)

    def test_spread_still_blocks_even_when_ask_inside_cap(self):
        h=self.h;key=self.dispatch()
        h.f.quote(bid=1.9,ask=2.1,seconds=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['filled_quantity'],0)
        h.f.quote(bid=2.02,ask=2.1,seconds=2);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['status'],'FILLED')

    def test_partial_entry_expiry_cancels_only_remainder_and_keeps_exit_plan(self):
        h=self.h;key=self.dispatch(quantity=2)
        h.f.quote(seconds=1,size=1)
        h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['status'],'PARTIALLY_FILLED')
        h.f.quote(seconds=10,size=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['status'],'CANCELED')
        self.assertEqual(h.f.engine.ledger.order(key)['filled_quantity'],1)
        self.assertEqual(h.f.service.positions()[0]['plan']['stop_pct'],'20')
        # Entry deadline does not expire the SELL inherited from the entry payload.
        h.f.quote(bid=1.6,ask=1.65,seconds=11);result=h.f.service.observe()[0]
        self.assertEqual(result['reason'],'LOSS_LIMIT')
        h.f.quote(bid=1.6,ask=1.65,seconds=12);h.f.service.observe()
        self.assertEqual(h.f.service.positions(),[])

    def test_new20_stop_and_exact_threshold_for_every_target(self):
        for target in ('10','20','35','100','MANUAL'):
            with self.subTest(target=target):
                # Independent harness per choice, no repeated signal/order.
                h=fixtures.AutomaticQueueTests();h.setUp()
                try:
                    with patch('schwab_simulation.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('20'),True)),patch('manual_execution.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('20'),True)):
                        h.f.engine.policy=ManualPracticePolicy();h.arm(quantity=1,target=target);h.runner.step()
                        h.f.quote(seconds=1);h.f.service.observe()
                        h.f.quote(bid=1.61,ask=1.65,seconds=2)
                        self.assertEqual(h.f.service.observe()[0]['status'],'HOLD')
                        h.f.quote(bid=1.6,ask=1.65,seconds=3)
                        self.assertEqual(h.f.service.observe()[0]['reason'],'LOSS_LIMIT')
                finally:h.doCleanups()

    def test_existing10_stop_is_not_rewritten_by_new20_policy(self):
        h=self.h
        with patch('schwab_simulation.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('10'),True)),patch('manual_execution.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('10'),True)):
            h.f.engine.policy=ManualPracticePolicy();h.f.filled(quantity=1)
        h.f.engine.policy=ManualPracticePolicy()
        h.f.quote(bid=1.8,ask=1.85,seconds=2)
        self.assertEqual(h.f.service.positions()[0]['plan']['stop_pct'],'10')
        self.assertEqual(h.f.service.observe()[0]['reason'],'LOSS_LIMIT')

    def test_pre_order_quote_cannot_be_reused_even_at_equal_timestamp(self):
        h=self.h;key=self.dispatch();h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['filled_quantity'],0)
        h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['status'],'FILLED')

    def test_old10_review_requires_a_new20_confirmation(self):
        h=self.h
        with patch('schwab_simulation.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('10'),True)),patch('manual_execution.load_global_exit_policy',return_value=GlobalExitPolicy(Decimal('10'),True)):
            h.f.engine.policy=ManualPracticePolicy();review=h.f.prepare()
        h.f.engine.policy=ManualPracticePolicy()
        with self.assertRaisesRegex(ExecutionBlocked,'REVIEW_POLICY_CHANGED'):
            h.f.service.confirm('owner',review['id'])
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_authorization_cannot_exceed_saved_company_ceiling_or_cost(self):
        from automatic_entry_execution import QueuedEntryAuthorization
        for quantity,cap,cost in [(1,'100','10000'),(1,'2.3','10000'),(2,'2.3','230')]:
            with self.assertRaisesRegex(ValueError,'QUEUE_PRICE_AUTHORIZATION_INVALID'):
                QueuedEntryAuthorization('AMZN',quantity,Decimal(cap),Decimal(cost)).payload(
                    symbol='AMZN',quantity=1,high=Decimal('2.3'),fee=0,now=self.h.f.now)

    def test_lookup_crossing_deadline_cannot_fill_a_late_order(self):
        h=self.h;key=self.dispatch();h.f.quote(seconds=9)
        lookup=h.f.market.get_entry_chain
        def slow(*args,**kwargs):
            market=lookup(*args,**kwargs)
            h.f.now+=timedelta(seconds=2)
            return market
        with patch.object(h.f.market,'get_entry_chain',side_effect=slow):h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.order(key)['status'],'CANCELED')
        self.assertEqual(h.f.engine.ledger.order(key)['filled_quantity'],0)
