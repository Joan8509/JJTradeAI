"""Automatic entry/confirmed ownership/exit cycle, entirely isolated."""
from dataclasses import replace
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock

from real_execution_service import RealExecutionService
from real_order_ledger import RealOrderLedger, RealOrderCoordinator, RealOrderBlocked
from schwab_option_order_request import prepare_option_limit
from tests import test_real_order_ledger as journal
from tests import test_schwab_execution_snapshot as evidence
from tests import test_schwab_option_order_request as options


class RealExecutionCycleTests(TestCase):
    def setUp(self):
        self.now=options.NOW;self.bid='.95';self.ask='1';self.ready=True
        self.vault=journal.Vault();self.ledger=RealOrderLedger(lambda:self.vault,lambda:self.now)
        self.gateway=Mock();self.gateway.submit.side_effect=(str(n) for n in range(100,200))
        self.gateway.cancel.return_value=True
        self.coordinator=RealOrderCoordinator(self.ledger,self.gateway,lambda *a:True)
        self.responses={}
        self.service=RealExecutionService(binding=journal.BINDING,account_number='12345678',
            ledger=self.ledger,coordinator=self.coordinator,read_order=lambda identity:self.responses[identity],
            quote_contract=self.quote,entry_ready=lambda:self.ready,signal_current=lambda key:True,clock=lambda:self.now)
        self.end=self.now+timedelta(hours=6)

    def quote(self,symbol):
        c=options.contract(bid=float(self.bid),ask=float(self.ask),quote_timestamp=self.now)
        return replace(c,snapshot=replace(c.snapshot,symbol=symbol))

    def enter(self,**changes):
        draft=prepare_option_limit(self.quote(options.contract().snapshot.symbol),instruction='BUY_TO_OPEN',
            quantity=2,now=self.now,valid_until=self.now+timedelta(seconds=30))
        args=dict(signal_key='AAPL:CANDLE:CALL',draft=draft,first_signal_at=self.now,
            source_at=self.now,session_close=self.end,target='20')
        args.update(changes);return self.service.enter(**args)

    def broker(self,row,amount,status='WORKING',price='1'):
        records=[(amount,price,self.now.isoformat())] if amount else []
        p=evidence.snapshot(row,records,status)
        self.responses[row['broker_id']]=p
        return p

    def own(self,target='20'):
        row=self.enter(target=target);self.broker(row,2,'FILLED')
        self.service.poll();return row

    def test_valid_signal_dispatches_once_and_receipt_is_not_ownership(self):
        row=self.enter()
        self.assertEqual(row['state'],'ACKNOWLEDGED')
        self.assertEqual(self.ledger.available_to_close(journal.BINDING,row['contract']),0)
        with self.assertRaises(RealOrderBlocked):self.enter()
        self.gateway.submit.assert_called_once()
        self.assertEqual(self.service.draft_for(dict(row)).limit,1)

    def test_stale_signal_readiness_and_expired_window_never_dispatch(self):
        for change in [dict(first_signal_at=self.now-timedelta(seconds=30)),
                       dict(source_at=self.now-timedelta(seconds=4),first_signal_at=self.now-timedelta(seconds=5)),
                       dict(source_at=self.now+timedelta(seconds=1)),dict(session_close=self.now)]:
            with self.assertRaises(RealOrderBlocked):self.enter(**change)
        self.ready=False
        with self.assertRaises(RealOrderBlocked):self.enter()
        self.gateway.submit.assert_not_called()

    def test_target_exit_is_reserved_and_fill_finishes_position(self):
        buy=self.own();self.bid='1.21';self.ask='1.22';self.ready=False
        results=self.service.poll();close=results[-1]
        self.assertEqual(close['instruction'],'SELL_TO_CLOSE');self.assertEqual(close['quantity'],2)
        self.assertEqual(close['limit'],'1.2')
        self.assertEqual(self.ledger.available_to_close(journal.BINDING,buy['contract']),0)
        self.broker(close,2,'FILLED','1.21');self.service.poll()
        self.assertEqual(self.ledger.available_to_close(journal.BINDING,buy['contract']),0)
        self.assertEqual(self.gateway.submit.call_count,2)

    def test_stop_uses_current_bid_and_is_latched_across_restart(self):
        buy=self.own();self.bid='.75';self.ask='.77'
        close=self.service.poll()[-1]
        self.assertEqual(close['limit'],'0.75')
        self.broker(close,0,'CANCELED')
        self.bid='.90';self.ask='.92'
        # Simulate losing volatile drafts and reconstructing the journal reader.
        self.service._drafts={}
        self.service.ledger=RealOrderLedger(lambda:self.vault,lambda:self.now)
        new_close=self.service.poll()[-1]
        self.assertEqual(new_close['instruction'],'SELL_TO_CLOSE')
        self.assertEqual(new_close['limit'],'0.9')
        self.assertEqual(self.gateway.submit.call_count,3)

    def test_stop_triggers_at_exact_twenty_percent_even_when_new_entries_are_blocked(self):
        buy=self.own();self.ready=False
        self.bid='.81';self.ask='.83'
        self.assertEqual(self.service.poll(),[])
        self.bid='.80';self.ask='.82'
        close=self.service.poll()[-1]
        self.assertEqual(close['instruction'],'SELL_TO_CLOSE')
        self.assertEqual(close['quantity'],2)
        self.assertEqual(close['limit'],'0.8')
        stored=next(r for r in self.ledger.requests(journal.BINDING) if r['id']==buy['id'])
        self.assertEqual(stored['exit_trigger'],'STOP')

    def test_quote_updated_during_http_is_checked_at_receipt_for_target_and_stop(self):
        self.own();quote=self.quote
        def refreshed(symbol):
            self.now+=timedelta(seconds=2)
            return quote(symbol)
        self.service.quote_contract=refreshed
        self.bid='1.21';self.ask='1.22'
        close=self.service.poll()[-1]
        self.assertEqual(close['instruction'],'SELL_TO_CLOSE')
        self.assertEqual(close['limit'],'1.2')

    def test_http_wait_does_not_make_an_old_quote_current(self):
        self.own();quote=self.quote(options.contract().snapshot.symbol)
        self.now+=timedelta(seconds=31)
        self.service.quote_contract=lambda symbol:quote
        result=self.service.poll()[-1]
        self.assertEqual(result['state'],'LIVE_EXIT_REQUIRES_REVIEW')
        self.assertEqual(self.gateway.submit.call_count,1)

    def test_stop_quote_during_http_uses_receipt_clock_and_preserves_twenty_percent(self):
        self.own();quote=self.quote
        def refreshed(symbol):
            self.now+=timedelta(seconds=2)
            return quote(symbol)
        self.service.quote_contract=refreshed;self.bid='.80';self.ask='.82'
        close=self.service.poll()[-1]
        self.assertEqual(close['limit'],'0.8')
        buy=self.ledger.requests(journal.BINDING)[0]
        self.assertEqual(buy['exit_trigger'],'STOP')

    def test_final_sale_transport_guard_rechecks_external_close_permission(self):
        self.own();self.bid='1.2';self.ask='1.22'
        close=self.service.poll()[-1]
        self.vault.data['requests'][close['id']]['state']='SUBMITTING'
        row=self.ledger.requests(journal.BINDING)[-1]
        self.assertTrue(self.service.commit_guard(row,'SUBMIT'))
        self.service.exit_admission=lambda contract:False
        self.assertFalse(self.service.commit_guard(row,'SUBMIT'))

    def test_rejected_close_never_becomes_a_loop_of_new_sell_orders(self):
        self.own();self.bid='1.2';self.ask='1.22'
        close=self.service.poll()[-1]
        payload=self.broker(close,0,'REJECTED')
        payload.update(remainingQuantity=0,orderActivityCollection=None)
        for _ in range(3):
            result=self.service.poll()[-1]
            self.assertEqual(result['code'],'LIVE_EXIT_REJECTION_REQUIRES_REVIEW')
        self.assertEqual(self.gateway.submit.call_count,2)
        self.gateway.cancel.assert_not_called()

    def test_ten_percent_profit_from_actual_fill_sells_on_first_valid_bid_at_floor(self):
        buy=self.own(target='10')
        # Actual execution cost was 1.00, not the original quoted Ask or Last.
        self.bid='1.09';self.ask='1.15'
        self.assertEqual(self.service.monitor_positions(),[])
        self.bid='1.10';self.ask='1.16'
        sale=self.service.monitor_positions()[-1]
        self.assertEqual(sale['instruction'],'SELL_TO_CLOSE')
        self.assertEqual(sale['limit'],'1.1')
        self.assertEqual(self.gateway.submit.call_count,2)

    def test_baba_price_case_uses_fifty_cent_fill_and_sells_at_fifty_five_cent_bid(self):
        self.bid='.49';self.ask='.51'
        buy=self.enter(target='10');self.broker(buy,2,'FILLED','.50');self.service.poll()
        original=self.quote
        self.service.quote_contract=lambda symbol:replace(original(symbol),price_increment=None)
        self.bid='.54';self.ask='.57'
        self.assertEqual(self.service.monitor_positions(),[])
        self.bid='.55'
        sale=self.service.monitor_positions()[-1]
        self.assertEqual(sale['limit'],'0.55')
        self.assertEqual(sale['instruction'],'SELL_TO_CLOSE')
        self.assertEqual(self.service.exit_observations[buy['contract']]['target_bid'],'0.55')

    def test_slow_account_order_read_does_not_hold_the_target_price_monitor(self):
        from threading import Thread,Event
        buy=self.own(target='10');self.bid='1.1';self.ask='1.12'
        # A second known WORKING order makes the observation GET slow.
        self.vault.data['requests'][buy['id']]['state']='WORKING'
        started=Event();release=Event()
        def slow(identity):started.set();release.wait(3);return self.responses[identity]
        self.service.read_order=slow
        worker=Thread(target=self.service.observe_orders,daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            # The actual broker fill remains confirmed; use a terminal snapshot
            # to check the price loop can acquire its own lock during the GET.
            self.vault.data['requests'][buy['id']]['state']='FILLED'
            sale=self.service.monitor_positions()[-1]
            self.assertEqual(sale['instruction'],'SELL_TO_CLOSE')
            self.assertFalse(release.is_set())
        finally:release.set();worker.join(1)

    def test_stop_cancels_gain_waits_for_terminal_then_sells_remainder_only(self):
        self.own();self.bid='1.21';self.ask='1.22'
        close=self.service.poll()[-1];self.broker(close,1,'WORKING','1.20')
        self.bid='.75';self.ask='.77'
        canceled=self.service.poll()[-1]
        self.assertEqual(canceled['state'],'PENDING_CANCEL')
        self.assertEqual(self.gateway.submit.call_count,2)
        self.broker(close,1,'CANCELED','1.20')
        stop=self.service.poll()[-1]
        self.assertEqual(stop['quantity'],1);self.assertEqual(stop['limit'],'0.75')

    def test_entry_timeout_cancels_unfilled_remainder_and_partial_keeps_exit(self):
        buy=self.enter();self.broker(buy,1)
        self.now+=timedelta(seconds=10)
        results=self.service.poll()
        self.assertTrue(any(r['state']=='PENDING_CANCEL' for r in results))
        self.gateway.cancel.assert_called_once()
        self.broker(buy,1,'CANCELED');self.bid='.75';self.ask='.77'
        stop=self.service.poll()[-1]
        self.assertEqual(stop['quantity'],1)

    def test_sell_timeout_is_uncertain_and_never_retried(self):
        self.own();self.bid='.75';self.ask='.77'
        self.gateway.submit.side_effect=TimeoutError()
        close=self.service.poll()[-1]
        self.assertEqual(close['state'],'UNCERTAIN')
        calls=self.gateway.submit.call_count
        self.service.poll();self.service.poll()
        self.assertEqual(self.gateway.submit.call_count,calls)

    def test_other_contract_same_company_blocked_while_position_open(self):
        self.own()
        other=replace(options.contract().snapshot,symbol='AAPL  261102P00350000',option_type='PUT')
        self.service.quote_contract=lambda symbol:replace(options.contract(),snapshot=other)
        draft=prepare_option_limit(replace(options.contract(),snapshot=other),instruction='BUY_TO_OPEN',
            quantity=1,now=self.now,valid_until=self.now+timedelta(seconds=10))
        with self.assertRaisesRegex(RealOrderBlocked,'SYMBOL_HAS_EXPOSURE'):
            self.enter(signal_key='NEW:PUT',draft=draft)

    def test_manual_target_has_stop_and_explicit_manual_close(self):
        buy=self.own(target='MANUAL');self.bid='1.5';self.ask='1.52'
        self.assertEqual(self.service.poll(),[])
        close=self.service.close_manually(buy['id'])
        self.assertEqual(close['limit'],'1.5')
        self.assertEqual(close['quantity'],2)

    def test_restart_never_reposts_acknowledged_entry_or_unknown_order(self):
        buy=self.enter();self.broker(buy,0)
        self.service._drafts={}
        self.service.poll()
        self.assertEqual(self.gateway.submit.call_count,1)
        self.service.read_order=Mock(side_effect=TimeoutError())
        self.assertTrue(any(r['state']=='LIVE_ORDER_READ_UNAVAILABLE' for r in self.service.poll()))
        self.assertEqual(self.gateway.submit.call_count,1)

    def test_gain_on_partial_entry_waits_for_final_buy_quantity_and_cost(self):
        buy=self.enter();self.broker(buy,1,price='.90');self.bid='1.10';self.ask='1.12'
        first=self.service.poll();self.assertEqual(first[-1]['state'],'PENDING_CANCEL')
        self.service.poll();self.assertEqual(self.gateway.submit.call_count,1)
        self.gateway.cancel.assert_called_once()  # A lagging WORKING GET does not repeat DELETE.
        p=evidence.snapshot(buy,[(1,'.90',self.now.isoformat()),(1,'1',self.now.isoformat())],'FILLED')
        self.responses[buy['broker_id']]=p
        results=self.service.poll()
        self.assertEqual(results[-1]['limit'],'1.14')
        self.assertEqual(results[-1]['quantity'],2)
