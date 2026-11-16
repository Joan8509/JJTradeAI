"""Rejected exits never silently disable the stop; all broker I/O is mocked."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock
from tests import test_real_broker_target as target_fixture
from tests import test_real_live_adapters as capital_fixture
from tests import test_real_order_ledger as journal
from real_trade_notices import RealTradeNotices


class ExitRecoveryTests(TestCase):
    def test_closed_position_does_not_emit_old_exit_failure_or_keep_its_warning(self):
        close=self.f.service.monitor_positions()[-1]
        self.f.broker(close,2,'FILLED','.8');self.f.service.observe_orders()
        self.f.service.exit_observations[self.buy['contract']].update(state='LIVE_EXIT_NOT_DISPATCHED')
        vault=journal.Vault();sender=Mock(return_value={'message_id':1})
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:vault,
            sender=sender,clock=lambda:self.f.now);notices.initialize()
        notices.exit_status_provider=lambda:self.f.service.exit_observations
        notices.step()
        self.assertFalse(any('SALIDA REAL REQUIERE ATENCIÓN' in call.args[0] for call in sender.call_args_list))
        self.f.service.monitor_positions()
        self.assertNotIn(self.buy['contract'],self.f.service.exit_observations)

    def test_never_dispatched_sale_is_visible_and_does_not_flood_the_ledger(self):
        from schwab_order_gateway import OrderNotDispatched
        self.f.gateway.submit.side_effect=OrderNotDispatched('ORDER_AUTHORIZATION_UNAVAILABLE')
        first=self.f.service.monitor_positions()[-1]
        self.assertEqual(first['state'],'EXPIRED')
        self.assertEqual(self.f.service.exit_observations[self.buy['contract']]['state'],'LIVE_EXIT_NOT_DISPATCHED')
        count=len(self.rows());calls=self.f.gateway.submit.call_count
        for _ in range(3):
            self.assertEqual(self.f.service.monitor_positions()[-1]['code'],'LIVE_EXIT_NOT_DISPATCHED')
        self.assertEqual(len(self.rows()),count);self.assertEqual(self.f.gateway.submit.call_count,calls)

    def setUp(self):
        self.target=target_fixture.BrokerTargetTests();self.target.setUp()
        self.f=self.target.f;self.child=self.target.native()
        raw=self.f.broker(self.child,0,'REJECTED');raw.update(remainingQuantity=0,orderActivityCollection=None)
        self.f.service.observe_orders()
        self.buy=next(r for r in self.f.ledger.requests(journal.BINDING) if r['instruction']=='BUY_TO_OPEN')
        self.capital=capital_fixture.LiveAdapterTests();self.capital.setUp()
        self.guard=self.capital.guard;self.guard.ledger=self.f.ledger;self.guard.clock=lambda:self.f.now
        self.capital.account['positions']=[dict(instrument=dict(assetType='OPTION',symbol=self.buy['contract']),longQuantity=2,shortQuantity=0)]
        self.capital.reader.orders.return_value=[raw]
        self.guard.refresh();self.f.service.exit_retry_proof=self.guard.rejected_exit_retry_proof
        self.f.bid='.8';self.f.ask='.82'

    def rows(self):return self.f.ledger.requests(journal.BINDING)

    def test_rejected_target_does_not_disable_stop_when_position_and_orders_are_proven(self):
        close=self.f.service.monitor_positions()[-1]
        self.assertEqual((close['instruction'],close['quantity'],close['limit']),('SELL_TO_CLOSE',2,'0.8'))
        self.assertTrue(self.rows()[0]['exit_recovery_used'])
        self.assertIn(self.child['id'],self.rows()[0]['resolved_exit_rejections'])
        self.assertEqual(self.f.gateway.submit.call_count,3)
        self.f.service.monitor_positions();self.assertEqual(self.f.gateway.submit.call_count,3)

    def test_a_second_rejection_never_creates_an_unlimited_sell_loop(self):
        close=self.f.service.monitor_positions()[-1]
        raw=self.f.broker(close,0,'REJECTED');raw.update(remainingQuantity=0,orderActivityCollection=None)
        self.f.service.observe_orders();self.capital.reader.orders.return_value.append(raw);self.guard.refresh()
        for _ in range(3):
            result=self.f.service.monitor_positions()[-1]
            self.assertEqual(result['code'],'LIVE_EXIT_REJECTION_REQUIRES_REVIEW')
        self.assertEqual(self.f.gateway.submit.call_count,3)

    def test_stop_latches_and_alerts_if_the_position_proof_is_missing(self):
        self.capital.account.pop('positions');self.guard.refresh()
        result=self.f.service.monitor_positions()[-1]
        self.assertEqual(result['code'],'LIVE_EXIT_REJECTION_REQUIRES_REVIEW')
        self.assertEqual(self.rows()[0]['exit_trigger'],'STOP')
        self.assertTrue(self.guard.exit_refresh_requested)
        self.assertEqual(self.f.gateway.submit.call_count,2)
        vault=journal.Vault();sender=Mock(return_value={'message_id':1})
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:vault,sender=sender,clock=lambda:self.f.now)
        notices.initialize();notices.exit_status_provider=lambda:self.f.service.exit_observations
        notices.step();sender.reset_mock();notices.step();sender.assert_not_called()
        self.assertTrue(any(v['event'].get('kind')=='EXIT_REVIEW' for v in vault.data['profiles'][journal.BINDING]['events'].values()))

    def test_manual_sale_extra_external_contracts_or_short_position_never_allow_retry(self):
        for long,short in ((0,0),(1,0),(3,0),(2,1)):
            with self.subTest(long=long,short=short):
                self.capital.account['positions'][0].update(longQuantity=long,shortQuantity=short)
                self.guard.refresh()
                self.assertIsNone(self.guard.rejected_exit_retry_proof(self.buy,[self.rows()[1]],2))
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_stale_or_pre_rejection_snapshot_requests_background_refresh_without_http(self):
        for observed in (self.f.now-timedelta(seconds=6),self.f.now-timedelta(seconds=1)):
            self.guard.balance_observed_at=observed
            before=self.capital.reader.positions.call_count
            self.assertIsNone(self.guard.rejected_exit_retry_proof(self.buy,[self.rows()[1]],2))
            self.assertTrue(self.guard.exit_refresh_requested)
            self.assertEqual(self.capital.reader.positions.call_count,before)

    def test_foreign_active_close_or_missing_rejected_order_evidence_blocks_retry(self):
        original=deepcopy(self.capital.reader.orders.return_value)
        foreign=deepcopy(original[0]);foreign.update(orderId=999,status='WORKING')
        for orders in ([],original+[foreign]):
            self.capital.reader.orders.return_value=orders;self.guard.refresh()
            self.assertIsNone(self.guard.rejected_exit_retry_proof(self.buy,[self.rows()[1]],2))
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_exact_goal_is_kept_when_retrying_a_rejected_gain_order(self):
        self.f.bid='1.10';self.f.ask='1.12'
        close=self.f.service.monitor_positions()[-1]
        self.assertEqual((close['instruction'],close['limit']),('SELL_TO_CLOSE','1.1'))
        self.assertEqual(self.rows()[0]['exit_trigger'],'TARGET')

    def test_retry_proof_is_rechecked_after_oauth_or_transport_wait(self):
        close=self.f.service.monitor_positions()[-1]
        self.f.vault.data['requests'][close['id']]['state']='SUBMITTING'
        claimed=self.rows()[-1]
        self.assertTrue(self.f.service.commit_guard(claimed,'SUBMIT'))
        self.f.now+=timedelta(seconds=6)
        self.assertFalse(self.f.service.commit_guard(claimed,'SUBMIT'))

    def test_proven_no_dispatch_returns_retry_permission_but_an_uncertain_post_does_not(self):
        from schwab_order_gateway import OrderNotDispatched
        self.f.gateway.submit.side_effect=OrderNotDispatched('ORDER_PREPARATION_FAILED')
        first=self.f.service.monitor_positions()[-1]
        self.assertEqual(first['state'],'EXPIRED')
        self.assertFalse(self.rows()[0]['exit_recovery_used'])
        self.f.now+=timedelta(seconds=1)
        self.f.gateway.submit.side_effect=TimeoutError('SYNTHETIC')
        second=self.f.service.monitor_positions()[-1]
        self.assertEqual(second['state'],'UNCERTAIN')
        self.assertTrue(self.rows()[0]['exit_recovery_used'])
        for _ in range(2):self.f.service.monitor_positions()
        self.assertEqual(self.f.gateway.submit.call_count,4)
