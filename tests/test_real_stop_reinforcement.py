"""Stop recovery with mocked broker, durable reservations and fill races."""
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock
from tests import test_real_execution_service as cycle
from tests import test_real_broker_target as targets
from tests import test_real_order_ledger as journal
from real_order_ledger import RealOrderBlocked


class StopReinforcementTests(TestCase):
    def setUp(self):
        self.f=cycle.RealExecutionCycleTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def reserved_stop(self):
        buy=self.f.own(target='10')
        self.f.ledger.trigger_exit(journal.BINDING,buy['id'],'STOP')
        row=self.f.ledger.prepare(journal.BINDING,intent='reserved-exit',contract=buy['contract'],
            instruction='SELL_TO_CLOSE',quantity=2,limit='.8',price_increment='.01',
            expires_at=self.f.now+timedelta(seconds=2),parent_id=buy['id'])
        return buy,row

    def pending_target(self):
        t=targets.BrokerTargetTests();t.setUp();self.addCleanup(t.f.doCleanups)
        self.f=t.f;buy=self.f.own(target='10');submit=self.f.coordinator.submit
        self.f.coordinator.submit=Mock(side_effect=lambda b,i:next(r for r in self.f.ledger.requests(b) if r['id']==i))
        try:t.targets.step()
        finally:self.f.coordinator.submit=submit
        row=self.f.ledger.requests(journal.BINDING)[-1]
        self.assertEqual(row['state'],'PREPARED');self.assertIsNone(row['broker_id'])
        return buy,row

    def test_expired_unsent_stop_recovers_after_restart_and_rebound(self):
        buy,row=self.reserved_stop();self.f.now+=timedelta(seconds=3)
        self.f.service._drafts={};self.f.bid='.90';self.f.ask='.92'
        sale=self.f.service.monitor_positions()[-1]
        rows=self.f.ledger.requests(journal.BINDING)
        self.assertEqual(next(r for r in rows if r['id']==row['id'])['state'],'EXPIRED')
        self.assertEqual(sale['instruction'],'SELL_TO_CLOSE');self.assertEqual(sale['quantity'],2)
        self.assertEqual(sale['limit'],'0.9');self.assertEqual(self.f.gateway.submit.call_count,2)
        self.f.broker(sale,2,'FILLED','.9');self.f.service.poll()
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_expired_submission_with_uncertain_http_is_never_released_or_repeated(self):
        buy,row=self.reserved_stop();self.f.ledger.begin_submit(journal.BINDING,row['id'])
        self.f.now+=timedelta(seconds=3);self.f.bid='.75';self.f.ask='.77'
        result=self.f.service.monitor_positions()[-1]
        self.assertEqual(result['code'],'LIVE_STOP_EXIT_CONFIRMATION_PENDING')
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,buy['contract']),0)
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_stop_releases_unsent_target_immediately_without_ten_second_wait(self):
        buy,row=self.pending_target();self.f.bid='.80';self.f.ask='.82'
        result=self.f.service.monitor_positions()[-1]
        self.assertEqual(result['id'],row['id']);self.assertEqual(result['state'],'EXPIRED')
        self.assertEqual(self.f.gateway.submit.call_count,1)
        sale=self.f.service.monitor_positions()[-1]
        self.assertEqual(sale['quantity'],2);self.assertEqual(sale['limit'],'0.8')
        self.assertEqual(self.f.gateway.submit.call_count,2)
        with self.assertRaises(RealOrderBlocked):self.f.coordinator.submit(journal.BINDING,row['id'])
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_submit_wins_release_race_reservation_remains_and_no_duplicate_sale(self):
        buy,row=self.pending_target();original=self.f.ledger.abandon_prepared
        def race(binding,identity):
            self.f.ledger.begin_submit(binding,identity)
            return original(binding,identity)
        self.f.ledger.abandon_prepared=race;self.f.bid='.8';self.f.ask='.82'
        self.assertEqual(self.f.service.monitor_positions()[-1]['state'],'SUBMITTING')
        self.assertEqual(self.f.service.monitor_positions()[-1]['code'],'LIVE_STOP_EXIT_CONFIRMATION_PENDING')
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,buy['contract']),0)
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_latched_stop_cancels_target_even_when_new_quote_is_unavailable(self):
        t=targets.BrokerTargetTests();t.setUp();self.addCleanup(t.f.doCleanups)
        row=t.native();f=t.f;f.broker(row,0,'WORKING');f.service.observe_orders()
        f.ledger.trigger_exit(journal.BINDING,t.buy['id'],'STOP')
        f.service.quote_contract=Mock(side_effect=TimeoutError())
        self.assertEqual(f.service.monitor_positions()[-1]['state'],'PENDING_CANCEL')
        f.gateway.cancel.assert_called_once();f.service.quote_contract.assert_not_called()
        f.service.monitor_positions();f.gateway.cancel.assert_called_once()
        self.assertEqual(f.gateway.submit.call_count,2)

    def test_slow_cancel_is_visible_then_partial_fill_closes_only_remaining(self):
        t=targets.BrokerTargetTests();t.setUp();self.addCleanup(t.f.doCleanups)
        row=t.native();f=t.f;f.broker(row,0,'WORKING');f.bid='.8';f.ask='.82'
        self.assertEqual(f.service.poll()[-1]['state'],'PENDING_CANCEL')
        f.now+=timedelta(seconds=6)
        self.assertEqual(f.service.monitor_positions()[-1]['code'],'LIVE_STOP_EXIT_CONFIRMATION_PENDING')
        f.broker(row,1,'CANCELED','1.10');f.service.observe_orders()
        f.bid='.74';f.ask='.76';sale=f.service.monitor_positions()[-1]
        self.assertEqual(sale['quantity'],1);self.assertEqual(sale['limit'],'0.74')
        f.broker(sale,1,'FILLED','.74');f.service.poll()
        self.assertEqual(f.gateway.submit.call_count,3)

    def test_stop_attention_notice_is_explicit_and_deduplicated(self):
        from real_trade_notices import RealTradeNotices
        buy,row=self.reserved_stop();self.f.ledger.begin_submit(journal.BINDING,row['id'])
        self.f.bid='.8';self.f.ask='.82';self.f.service.monitor_positions()
        store=journal.Vault();sender=Mock(return_value={'message_id':1})
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:store,
            sender=sender,clock=lambda:self.f.now)
        notices.initialize();notices.exit_status_provider=lambda:self.f.service.exit_observations
        notices.step();notices.step()
        messages=[c.args[0] for c in sender.call_args_list if 'Stop del 20%' in c.args[0]]
        self.assertEqual(len(messages),1)

    def test_no_stop_does_not_abandon_live_prepared_target(self):
        buy,row=self.pending_target();self.f.service.monitor_positions()
        self.assertEqual(self.f.ledger.requests(journal.BINDING)[-1]['state'],'PREPARED')
