"""Confirmed sales, realized PnL and one-attempt alerts on synthetic TEMP data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import hashlib
import unittest
from unittest.mock import Mock

from tests import test_manual_execution as fixture
from trade_close_reporting import sale_reports,format_sale_notice
from trade_close_notifications import SaleNotifier,SaleNoticeStore
from schwab_simulation import ExecutionBlocked


class SaleNoticeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ManualExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.api=Mock(return_value={'message_id':123})
        self.store=SaleNoticeStore(self.f.root/'sale_notices.db');self.notifier=self.build();self.notifier.arm()

    def build(self):
        return SaleNotifier(self.f.engine.ledger,self.store,account_alias=self.f.policy.account_alias,
            user_id=123,call=self.api,clock=lambda:self.f.now)

    def report(self):return sale_reports(self.f.engine.ledger,self.f.policy.account_alias,now=self.f.now)[0]

    def working_exit(self,target='35',manual=False):
        self.entry=self.f.filled(target)
        if manual:
            self.f.quote(bid=2.1,ask=2.15,seconds=2)
            review=self.f.service.prepare_close('owner',self.f.code)
            result=self.f.service.confirm('owner',review['id'])
        else:
            self.f.quote(bid=2.7,ask=2.75,seconds=2);result=self.f.service.observe()[0]
        self.exit=result['client_key'];return result

    def sell(self,size=10,seconds=3,bid=2.7):
        self.f.quote(bid=bid,ask=bid+.05,size=size,seconds=seconds);self.f.service.observe()

    def test_target_or_order_acceptance_never_notifies_until_sale_fills(self):
        self.working_exit()
        self.assertEqual(sale_reports(self.f.engine.ledger,self.f.policy.account_alias,now=self.f.now),[])
        self.assertEqual(self.notifier.pump()['accepted'],0);self.api.assert_not_called()
        self.sell();self.assertEqual(self.notifier.pump()['accepted'],1)
        report=self.report()
        self.assertEqual(report['status'],'CLOSED');self.assertEqual(report['gross_pnl'],Decimal('210'))
        self.assertEqual(report['gross_pct'],Decimal('35'));self.assertEqual(report['fees'],Decimal('3.90'))
        self.assertEqual(report['net_pnl'],Decimal('206.10'))
        text=self.api.call_args.kwargs['text']
        self.assertIn('SIMULACIÓN LOCAL',text);self.assertIn('POSICIÓN CERRADA',text)
        self.assertIn('+206.10',text);self.assertIn('objetivo de ganancia',text)
        self.assertNotIn(self.f.policy.account_alias,text)

    def test_partial_sale_then_full_uses_cumulative_actual_fills_and_no_duplicate(self):
        self.working_exit();self.sell(size=1)
        partial=self.report();self.assertEqual(partial['status'],'PARTIAL_SALE')
        self.assertEqual(partial['sold_quantity'],1);self.assertEqual(partial['remaining_quantity'],2)
        self.assertEqual(partial['net_pnl'],Decimal('68.70'))
        self.notifier.pump();self.notifier.pump();self.assertEqual(self.api.call_count,1)
        self.assertIn('VENTA PARCIAL',self.api.call_args.kwargs['text'])
        self.sell(size=2,seconds=4);self.notifier.pump()
        self.assertEqual(self.api.call_count,2);self.assertEqual(self.report()['net_pnl'],Decimal('206.10'))
        self.assertIn('POSICIÓN CERRADA',self.api.call_args.kwargs['text'])

    def test_manual_close_available_with_percent_target_and_receipt_identifies_reason(self):
        self.working_exit('100',manual=True);self.sell(bid=2.1)
        report=self.report();self.assertEqual(report['reasons'],['MANUAL_CLOSE'])
        self.assertEqual(report['gross_pnl'],Decimal('30'));self.assertEqual(report['net_pnl'],Decimal('26.10'))
        self.notifier.pump();self.assertIn('cierre manual',self.api.call_args.kwargs['text'])

    def test_manual_profit_still_stops_at_twenty_percent_and_reports_loss(self):
        self.f.filled('MANUAL');self.f.quote(bid=1.6,ask=1.65,seconds=2)
        self.assertEqual(self.f.service.observe()[0]['reason'],'LOSS_LIMIT')
        self.sell(bid=1.6)
        report=self.report();self.assertEqual(report['gross_pct'],Decimal('-20'))
        self.assertEqual(report['net_pnl'],Decimal('-123.90'))
        self.notifier.pump();self.assertIn('stop loss',self.api.call_args.kwargs['text'])
        self.assertIn('-123.90',self.api.call_args.kwargs['text'])

    def test_existing_sales_are_suppressed_after_restart_not_replayed(self):
        self.working_exit();self.sell();restart=self.build();restart.arm()
        self.assertEqual(restart.pump()['skipped'],1);self.api.assert_not_called()
        self.assertEqual(self.store.read('SELECT state FROM sale_notices')[0]['state'],'HISTORICAL_SKIPPED')

    def test_old_broker_fill_reconciled_after_boot_is_not_a_new_notification(self):
        self.working_exit();self.f.quote(bid=2.7,ask=2.75,seconds=3)
        contract=fixture.f.synthetic_contract(self.f.now,bid=2.7,ask=2.75)
        self.f.engine.broker.match_quote(self.f.engine.ledger.order(self.exit)['broker_id'],contract,
            now=self.f.now,execution_id='OLD_BROKER_SALE')
        self.f.now+=timedelta(seconds=10);restart=self.build();restart.arm()
        self.f.engine.reconcile(self.f.now)
        self.assertEqual(restart.pump()['skipped'],1);self.api.assert_not_called()

    def test_uncertain_delivery_is_durable_claim_and_never_resent_after_restart(self):
        self.working_exit();self.sell()
        def uncertain(*args,**kwargs):
            self.assertEqual(self.store.read('SELECT state FROM sale_notices')[0]['state'],'CLAIMED')
            raise TimeoutError('PRIVATE_DETAIL')
        self.api.side_effect=uncertain
        self.assertEqual(self.notifier.pump()['unconfirmed'],1)
        self.notifier.pump();restart=self.build();restart.arm();restart.pump()
        self.assertEqual(self.api.call_count,1)
        row=self.store.read('SELECT * FROM sale_notices')[0]
        self.assertEqual(row['state'],'DELIVERY_UNCONFIRMED');self.assertNotIn('PRIVATE_DETAIL',str(row))

    def test_concurrent_pumps_claim_sale_only_once(self):
        self.working_exit();self.sell()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:self.notifier.pump(),range(2)))
        self.assertEqual(self.api.call_count,1)

    def test_reports_are_read_only_and_no_current_quote_needed(self):
        self.working_exit();self.sell();path=self.f.engine.ledger.path
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        self.f.state['session']=None;self.f.state['tick']['signal']=None
        self.assertEqual(self.report()['status'],'CLOSED')
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_unreconciled_or_missing_fill_details_cannot_claim_sale(self):
        self.working_exit();self.sell()
        with self.f.engine.ledger.transaction() as db:
            db.execute("UPDATE simulation_settings SET value='1' WHERE key='reconciliation_blocked'")
        with self.assertRaises(ExecutionBlocked):self.notifier.pump()
        self.api.assert_not_called();self.assertEqual(self.store.read('SELECT * FROM sale_notices'),[])
        with self.f.engine.ledger.transaction() as db:
            db.execute("UPDATE simulation_settings SET value='0' WHERE key='reconciliation_blocked'")
            db.execute('UPDATE simulated_orders SET filled_quantity=0 WHERE client_key=?',(self.exit,))
        with self.assertRaises(ExecutionBlocked):self.notifier.pump()
        self.api.assert_not_called()

    def test_rate_limit_cooldown_does_not_retry_attempted_message(self):
        from telegram_alerts import TelegramError
        self.working_exit();self.sell();self.api.side_effect=TelegramError('Wait',retry_after_seconds=75)
        self.assertEqual(self.notifier.pump()['retry_after_seconds'],75)
        self.notifier.pump();self.assertEqual(self.api.call_count,1)

    def test_canceled_unfilled_exit_is_not_a_sale(self):
        self.working_exit();review=self.f.service.prepare_cancel('owner',self.exit)
        self.f.service.confirm('owner',review['id'])
        self.assertEqual(self.notifier.pump()['accepted'],0);self.api.assert_not_called()

    def test_weighted_actual_entry_fills_instead_of_reviewed_ask(self):
        self.f.enter('35');self.f.quote(bid=1.9,ask=1.95,size=1,seconds=1)
        with self.assertRaises(ExecutionBlocked):self.f.service.observe()
        self.f.quote(bid=1.95,ask=2.,size=2,seconds=2);self.f.service.observe()
        self.f.quote(bid=2.75,ask=2.8,seconds=3);self.f.service.observe()
        self.f.quote(bid=2.75,ask=2.8,seconds=4);self.f.service.observe()
        report=self.report()
        self.assertEqual(report['entry_average'],Decimal(595)/300)
        self.assertEqual(report['gross_pnl'],Decimal('230'));self.assertEqual(report['net_pnl'],Decimal('226.10'))

    def test_target_partial_then_canceled_remainder_and_manual_sale_are_one_trade(self):
        self.working_exit();self.sell(size=1)
        review=self.f.service.prepare_cancel('owner',self.exit);self.f.service.confirm('owner',review['id'])
        self.f.quote(bid=2.6,ask=2.65,seconds=4)
        close=self.f.service.prepare_close('owner',self.f.code);self.f.service.confirm('owner',close['id'])
        self.sell(size=2,seconds=5,bid=2.6)
        report=self.report()
        self.assertEqual(report['status'],'CLOSED');self.assertEqual(report['sold_quantity'],3)
        self.assertEqual(report['reasons'],['MANUAL_CLOSE','TARGET'])
        self.assertEqual(report['gross_pnl'],Decimal('190'));self.assertEqual(report['net_pnl'],Decimal('186.10'))
