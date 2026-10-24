"""Queued entries -> automatic sale -> Telegram MOCK, temporary local data only."""
from decimal import Decimal
import unittest
from unittest.mock import Mock

from tests import test_automatic_entry_queue as fixture
from trade_close_notifications import SaleNotifier, SaleNoticeStore


class QueuedCloseNoticeTests(unittest.TestCase):
    def harness(self):
        h=fixture.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        api=Mock(return_value={'message_id':123})
        notices=SaleNoticeStore(h.f.root/'sale_notices.db')
        notifier=SaleNotifier(h.f.engine.ledger,notices,account_alias=h.f.engine.policy.account_alias,
            user_id=123,call=api,clock=lambda:h.f.now)
        notifier.arm()
        return h,notifier,api

    def test_each_queued_profit_target_notifies_once_only_after_confirmed_sale(self):
        for target,bid,gross in [('10',2.2,'40'),('20',2.4,'80'),('35',2.7,'140'),('100',4.,'400')]:
            with self.subTest(target=target):
                h,notifier,api=self.harness()
                h.arm(quantity=2,target=target);h.runner.step()
                h.f.quote(seconds=1);h.f.service.observe()
                h.f.quote(bid=bid,ask=bid+.05,seconds=2)
                _,_,contract,controls,now=h.f.service._exit(h.f.code,force=True)
                h.f.engine.manage_exit(contract,controls,now)
                notifier.pump();api.assert_not_called()  # Target hit/order pending is not a sale.
                h.f.quote(bid=bid,ask=bid+.05,seconds=3);h.f.service.observe()
                self.assertEqual(notifier.pump()['accepted'],1)
                notifier.pump();self.assertEqual(api.call_count,1)
                args=api.call_args.kwargs;text=args['text']
                self.assertEqual(api.call_args.args[0],'sendMessage')
                for required in ('SIMULACIÓN LOCAL','POSICIÓN CERRADA','AMZN','CALL',
                        'Vendidos: 2 / 2','Restantes: 0','Entrada media: $2.0000',
                        f'Venta media: ${bid:.4f}',f'+{Decimal(gross):.2f} USD',
                        f'+{Decimal(target):.2f}%','objetivo de ganancia','ET',
                        'Costos no verificados','Neto no disponible'):
                    self.assertIn(required,text)
                self.assertNotIn(h.f.engine.policy.account_alias,text)
                # Removing a completed card does not delete notice claims or resend.
                h.store.archive(h.plan()['id'],now=h.f.now,ledger_path=h.f.engine.ledger.path)
                notifier.pump();self.assertEqual(api.call_count,1)

    def test_queue_stop_and_manual_close_report_the_actual_exit_reason(self):
        for mode,bid,reason,result in [('STOP',1.8,'stop loss','-40.00'),('MANUAL',2.1,'cierre manual','+20.00')]:
            with self.subTest(mode=mode):
                h,notifier,api=self.harness()
                h.arm(quantity=2,target='100');h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
                h.f.quote(bid=bid,ask=bid+.05,seconds=2)
                if mode=='MANUAL':
                    review=h.f.service.prepare_close('owner',h.f.code);h.f.service.confirm('owner',review['id'])
                else:h.f.service.observe()
                api.assert_not_called()
                h.f.quote(bid=bid,ask=bid+.05,seconds=3);h.f.service.observe();notifier.pump()
                self.assertEqual(api.call_count,1)
                text=api.call_args.kwargs['text'];self.assertIn(reason,text);self.assertIn(result+' USD',text)

    def test_queued_partial_sale_is_distinct_and_final_sale_not_duplicated(self):
        h,notifier,api=self.harness()
        h.arm(quantity=2,target='35');h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
        h.f.quote(bid=2.7,ask=2.75,seconds=2)
        _,_,contract,controls,now=h.f.service._exit(h.f.code,force=True)
        h.f.engine.manage_exit(contract,controls,now)
        h.f.quote(bid=2.7,ask=2.75,size=1,seconds=3);h.f.service.observe();notifier.pump()
        self.assertIn('VENTA PARCIAL',api.call_args.kwargs['text'])
        self.assertIn('Restantes: 1',api.call_args.kwargs['text'])
        notifier.pump();self.assertEqual(api.call_count,1)
        h.f.quote(bid=2.7,ask=2.75,size=1,seconds=4);h.f.service.observe();notifier.pump()
        self.assertEqual(api.call_count,2)
        self.assertIn('POSICIÓN CERRADA',api.call_args.kwargs['text'])
        self.assertIn('+140.00 USD (+35.00%)',api.call_args.kwargs['text'])
        notifier.pump();self.assertEqual(api.call_count,2)
