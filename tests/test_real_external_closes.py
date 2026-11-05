"""Manual thinkorswim closes: isolated vaults/HTTP, never a live order."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock,patch

from real_external_closes import ExternalManualCloses
from real_automatic_queue import RealAutomaticQueue
from real_trade_notices import RealTradeNotices
from real_live_control import RealRuntimeProxy
from tests import test_real_execution_service as cycle
from tests import test_real_order_ledger as journal
from tests.test_schwab_execution_snapshot import snapshot


class ExternalCloseTests(TestCase):
    def setUp(self):
        self.f=cycle.RealExecutionCycleTests();self.f.setUp();self.buy=self.f.own(target='10')
        self.f.now+=timedelta(seconds=5)
        self.qvault=journal.Vault();self.queue=RealAutomaticQueue(store_factory=lambda:self.qvault,clock=lambda:self.f.now)
        self.queue.arm(journal.BINDING,[dict(symbol='AAPL',quantity=2,target='10'),dict(symbol='MSFT',quantity=1,target='10')],
            session_open=self.f.now-timedelta(minutes=1),session_close=self.f.end,
            execution_ready=lambda:True,repeat_new_signals=True)
        self.raw=self.manual();self.orders=Mock(return_value=[self.raw])
        self.f.responses['999']=self.raw
        self.monitor=self.make()

    def manual(self,*,identity='999',quantity=2,filled=2,status='FILLED',kind='LIMIT'):
        row=dict(self.buy,instruction='SELL_TO_CLOSE',broker_id=identity,quantity=quantity)
        records=[(filled,'1.15',self.f.now.isoformat())] if filled else []
        raw=snapshot(row,records,status)
        raw.update(orderType=kind,enteredTime=self.f.now.isoformat())
        if kind=='LIMIT':raw['price']='1.10'
        return raw

    def make(self):return ExternalManualCloses(self.f.service,self.queue,self.orders,clock=lambda:self.f.now)

    def own_target(self):
        self.f.bid='1.10';self.f.ask='1.12';row=self.f.service.poll()[-1]
        self.f.broker(row,0,'WORKING');return row

    def test_full_close_pauses_all_rows_and_never_resells_even_after_restart(self):
        self.monitor.step();self.make().step();self.f.bid='.70';self.f.ask='.72';self.f.service.poll()
        rows=self.f.ledger.requests(journal.BINDING)
        self.assertEqual(len(rows),2);self.assertEqual(rows[-1]['origin'],'BROKER_DETECTED_MANUAL_CLOSE')
        self.assertEqual(rows[-1]['state'],'FILLED');self.assertEqual(self.f.gateway.submit.call_count,1)
        plan=self.queue.read(journal.BINDING)
        self.assertTrue(plan['paused']);self.assertTrue(all(not r['repeat_new_signals'] for r in plan['rows']))
        self.assertTrue(all(r['state']=='PAUSED' for r in plan['rows']))

    def test_market_manual_sale_imports_actual_fills_without_inventing_a_limit(self):
        self.raw=self.manual(kind='MARKET');self.orders.return_value=[self.raw];self.f.responses['999']=self.raw
        self.monitor.step();row=self.f.ledger.requests(journal.BINDING)[-1]
        self.assertEqual(row['external_order_type'],'MARKET');self.assertIsNone(row['limit'])
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_working_manual_order_cancels_app_sale_and_waits_for_both_final_states(self):
        target=self.own_target();self.monitor.step()
        self.f.gateway.cancel.assert_called_once();self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),2)
        self.assertTrue(self.f.ledger.requests(journal.BINDING)[0]['external_close_hold'])
        self.f.bid='.70';self.f.ask='.72';self.f.service.monitor_positions()
        self.assertEqual(self.f.gateway.submit.call_count,2)
        self.f.broker(target,0,'CANCELED');self.monitor.step()
        rows=self.f.ledger.requests(journal.BINDING)
        self.assertEqual(len(rows),3);self.assertFalse(rows[0]['external_close_hold'])
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,self.buy['contract']),0)

    def test_partial_manual_order_in_progress_blocks_another_sale_until_terminal(self):
        self.raw=self.manual(filled=1,status='WORKING');self.orders.return_value=[self.raw];self.f.responses['999']=self.raw
        self.monitor.step()
        self.assertEqual(self.monitor.status()[self.buy['contract']]['state'],'WAITING_MANUAL_ORDER_FINAL')
        self.f.bid='.70';self.f.ask='.72';self.f.service.monitor_positions()
        self.assertEqual(self.f.gateway.submit.call_count,1)
        self.raw['status']='CANCELED';self.monitor.step()
        self.assertEqual(self.monitor.status()[self.buy['contract']]['remaining'],1)
        sale=self.f.service.monitor_positions()[-1]
        self.assertEqual(sale['quantity'],1);self.assertEqual(sale['limit'],'0.7')
        self.assertTrue(self.queue.read(journal.BINDING)['paused'])

    def test_two_terminal_partial_orders_import_only_the_confirmed_total(self):
        first=self.manual(filled=1,status='CANCELED')
        second=self.manual(identity='998',filled=1,status='CANCELED')
        self.orders.return_value=[first,second];self.f.responses.update({'999':first,'998':second})
        self.monitor.step()
        self.assertEqual(self.monitor.status()[self.buy['contract']]['remaining'],0)
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),3)

    def test_unrelated_company_other_account_and_old_sale_are_never_imported(self):
        for change in ('contract','account','old'):
            with self.subTest(change=change):
                raw=deepcopy(self.raw)
                if change=='contract':raw['orderLegCollection'][0]['instrument']['symbol']='MSFT  261102C00500000'
                if change=='account':raw['accountNumber']='87654321'
                if change=='old':raw['enteredTime']=(self.f.now-timedelta(days=1)).isoformat()
                self.orders.return_value=[raw];self.monitor.step()
                self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),1)
                self.assertFalse(self.queue.read(journal.BINDING)['paused'])

    def test_missing_history_oversized_sale_and_external_buy_require_review(self):
        for change in ('history','oversized','external_buy'):
            with self.subTest(change=change):
                self.setUp()
                if change=='history':self.raw['orderActivityCollection']=None
                if change=='oversized':self.raw=self.manual(quantity=3,filled=3)
                self.f.responses['999']=self.raw;self.orders.return_value=[self.raw]
                if change=='external_buy':
                    external=deepcopy(self.raw);external['orderId']=888
                    external['orderLegCollection'][0]['instruction']='BUY_TO_OPEN'
                    self.orders.return_value.append(external)
                self.monitor.step()
                self.assertTrue(self.queue.read(journal.BINDING)['paused'])
                self.assertTrue(self.monitor.status()[self.buy['contract']]['review'])
                self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),1)

    def test_disconnect_after_detection_keeps_hold_and_recovers_without_duplicate(self):
        read=self.f.service.read_order;self.f.service.read_order=Mock(side_effect=TimeoutError())
        self.monitor.step();self.assertTrue(self.f.ledger.requests(journal.BINDING)[0]['external_close_hold'])
        self.f.service.read_order=read
        # Restart and an incomplete list still fetch the durable detected ID.
        self.orders.return_value=[];self.make().step();self.make().step()
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),2)
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_list_failure_without_detection_does_not_disable_existing_stop(self):
        self.orders.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):self.monitor.step()
        self.f.bid='.80';self.f.ask='.82';sale=self.f.service.monitor_positions()[-1]
        self.assertEqual(sale['limit'],'0.8')

    def test_inflight_unknown_app_order_is_never_abandoned_or_duplicated(self):
        row=self.own_target();saved=self.f.vault.data['requests'][row['id']]
        saved.update(state='UNCERTAIN',broker_id=None)
        self.monitor.step()
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),2)
        self.assertEqual(self.f.gateway.submit.call_count,2)
        self.assertTrue(self.f.ledger.requests(journal.BINDING)[0]['external_close_hold'])

    def test_unsent_prepared_app_sale_is_released_before_manual_import(self):
        row=self.own_target();self.f.vault.data['requests'][row['id']].update(state='PREPARED',broker_id=None)
        self.monitor.step()
        self.assertEqual(self.f.ledger.requests(journal.BINDING)[1]['state'],'EXPIRED')
        self.assertEqual(self.monitor.status()[self.buy['contract']]['remaining'],0)

    def test_manual_cancel_without_fills_keeps_position_and_queue_paused(self):
        raw=self.manual(filled=0,status='CANCELED');self.orders.return_value=[raw];self.f.responses['999']=raw
        self.monitor.step();self.monitor.step()
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),1)
        self.assertEqual(self.monitor.status()[self.buy['contract']]['remaining'],2)
        self.assertTrue(self.queue.read(journal.BINDING)['paused'])

    def test_persistent_hold_blocks_final_sell_guard_and_new_entry(self):
        row=self.own_target();saved=self.f.vault.data['requests'][row['id']];saved['state']='SUBMITTING'
        self.f.ledger.flag_external_close(journal.BINDING,self.buy['id'],['999'])
        self.assertFalse(self.f.service.commit_guard(self.f.ledger.requests(journal.BINDING)[-1],'SUBMIT'))
        with self.assertRaisesRegex(RuntimeError,'EXTERNAL_CLOSE'):self.f.enter(signal_key='NEW_SIGNAL')

    def test_automatic_manual_history_and_notices_show_close_without_rearm(self):
        store=journal.Vault();sender=Mock(return_value={'message_id':12})
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:store,sender=sender,clock=lambda:self.f.now)
        notices.initialize();self.monitor.step();notices.external_status_provider=self.monitor.status
        notices.step();notices.step()
        texts=[call.args[0] for call in sender.call_args_list]
        self.assertTrue(any('VENTA REAL CONFIRMADA' in text and 'Cierre manual conciliado' in text for text in texts))
        self.assertTrue(any('VENTA MANUAL DETECTADA EN SCHWAB' in text for text in texts))
        with patch('real_order_ledger.RealOrderLedger',return_value=self.f.ledger):
            proxy=RealRuntimeProxy(journal.BINDING)
            self.assertEqual(proxy.positions(),[]);self.assertTrue(proxy.trade_history()[0]['manual_close'])
        self.assertTrue(self.queue.read(journal.BINDING)['paused'])

    def test_consumed_first_entry_and_excluded_companies_survive_manual_close(self):
        plan=self.qvault.data['profiles'][journal.BINDING]
        plan.update(first_entry_only=True,entry_consumed=True,winning_symbol='AAPL',winning_request_id=self.buy['id'])
        plan['rows'][0].update(state='ORDER_SENT',request_id=self.buy['id'],repeat_new_signals=False)
        plan['rows'][1].update(state='EXCLUDED_FIRST_ENTRY',repeat_new_signals=False)
        self.monitor.step();self.queue.step(journal.BINDING,self.f.service,Mock(),monitor=False)
        plan=self.queue.read(journal.BINDING)
        self.assertTrue(plan['paused']);self.assertTrue(plan['entry_consumed'])
        self.assertEqual(plan['winning_request_id'],self.buy['id'])
        self.assertEqual(plan['rows'][0]['state'],'COMPLETED')
        self.assertEqual(plan['rows'][1]['state'],'EXCLUDED_FIRST_ENTRY')

    def test_missing_or_mismatched_final_identity_keeps_protection_hold(self):
        self.raw['orderId']=998
        self.orders.return_value=[dict(self.raw,orderId=999)]
        self.monitor.step()
        self.assertTrue(self.monitor.status()[self.buy['contract']]['review'])
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),1)

    def test_cancel_fill_race_cannot_import_more_than_still_owned(self):
        target=self.own_target();self.f.broker(target,2,'FILLED','1.10')
        self.monitor.step()
        self.assertTrue(self.monitor.status()[self.buy['contract']]['review'])
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),2)
        self.assertEqual(self.f.gateway.submit.call_count,2)

    def test_partial_buy_remaining_is_canceled_before_confirmed_manual_close(self):
        self.f=cycle.RealExecutionCycleTests();self.f.setUp();self.buy=self.f.enter(target='10')
        self.f.broker(self.buy,1,'WORKING');self.f.service.poll();self.f.now+=timedelta(seconds=1)
        self.raw=self.manual(quantity=1,filled=1)
        self.orders.return_value=[self.raw];self.f.responses['999']=self.raw;self.monitor=self.make()
        self.monitor.step();self.f.gateway.cancel.assert_called_once()
        self.f.responses[self.buy['broker_id']]['status']='CANCELED';self.monitor.step()
        state=self.monitor.status()[self.buy['contract']]
        self.assertEqual(state.get('remaining'),0,state)
        self.assertEqual(self.f.gateway.submit.call_count,1)

    def test_complex_manual_close_is_detected_but_never_imported_as_single(self):
        child=deepcopy(self.raw)
        self.raw.update(orderLegCollection=[],orderStrategyType='OCO',childOrderStrategies=[child])
        self.monitor.step()
        self.assertTrue(self.queue.read(journal.BINDING)['paused'])
        self.assertTrue(self.monitor.status()[self.buy['contract']]['review'])
        self.assertEqual(len(self.f.ledger.requests(journal.BINDING)),1)
