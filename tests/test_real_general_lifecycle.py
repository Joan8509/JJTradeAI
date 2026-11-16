"""Prepared per-company target -> buy -> fill notice -> broker profit sale.

All vaults, quotes, previews, orders and Telegram receipts are synthetic.
"""
from datetime import timedelta
from decimal import Decimal,ROUND_CEILING
from unittest import TestCase
from unittest.mock import Mock
from tests import test_real_broker_target as target_fixture
from tests import test_real_order_ledger as journal
from tests import test_schwab_option_order_request as option_fixture
from real_automatic_queue import RealAutomaticQueue
from real_trade_preparation import RealPreparationSession
from real_trade_notices import RealTradeNotices
from schwab_option_order_request import prepare_option_limit


class GeneralRealLifecycleTests(TestCase):
    def test_every_company_side_and_selected_target_buys_before_notice_and_sells_at_its_target(self):
        for symbol in ('AAPL','NVDA','QQQ','GLD','BABA'):
            for side in ('CALL','PUT'):
                for target in ('10','20','35','100'):
                    with self.subTest(symbol=symbol,side=side,target=target):
                        self.check_cycle(symbol,side,target)

    def check_cycle(self,symbol,side,target):
        fixture=target_fixture.BrokerTargetTests();fixture.setUp();f=fixture.f
        contract=symbol.ljust(6)+'261102'+('C' if side=='CALL' else 'P')+'00350000'
        f.quote=lambda identity:option_fixture.contract(side,symbol=identity,
            underlying_symbol=identity.split()[0],bid=.95,ask=1.,quote_timestamp=f.now)
        f.service.quote_contract=f.quote
        prep_vault=journal.Vault()
        prep=RealPreparationSession(store_factory=lambda:prep_vault,clock=lambda:f.now)
        saved=prep.save(journal.BINDING,[dict(symbol=symbol,quantity=2,target=target),
            dict(symbol='MSFT',quantity=1,target='20')])
        queue_vault=journal.Vault()
        queue=RealAutomaticQueue(store_factory=lambda:queue_vault,clock=lambda:f.now-timedelta(seconds=1))
        queue.arm(journal.BINDING,saved['rows'],session_open=f.now,session_close=f.end,
            execution_ready=lambda:True,first_entry_only=True)
        queue.clock=lambda:f.now
        notice_vault=journal.Vault();sender=Mock(return_value={'message_id':123})
        notices=RealTradeNotices(journal.BINDING,f.ledger,store_factory=lambda:notice_vault,
            sender=sender,clock=lambda:f.now);notices.initialize()
        draft=prepare_option_limit(f.quote(contract),instruction='BUY_TO_OPEN',quantity=2,
            now=f.now,valid_until=f.now+timedelta(seconds=10))
        provider=Mock(side_effect=lambda row:dict(signal_key='REAL:'+symbol+':'+side,draft=draft,
            first_signal_at=f.now,source_at=f.now,session_close=f.end,target=row['target']))
        queue.step(journal.BINDING,f.service,provider,monitor=False)
        provider.assert_called_once();f.gateway.submit.assert_called_once()
        buy=f.ledger.requests(journal.BINDING)[0]
        self.assertEqual(buy['exit_plan']['target'],target)
        notices.step();sender.assert_not_called() # HTTP receipt is not a fill.
        f.broker(buy,2,'FILLED','.95');f.service.observe_orders();notices.step()
        sender.assert_called_once()
        self.assertIn('COMPRA REAL CONFIRMADA',sender.call_args.args[0])
        self.assertIn(symbol+' '+side,sender.call_args.args[0])
        self.assertIn('Objetivo '+target+'%',sender.call_args.args[0])
        # Editing a subsequent preparation cannot overwrite an executed trade.
        prep.save(journal.BINDING,[dict(symbol=symbol,quantity=1,target='35' if target!='35' else '10')])
        fixture.targets.step()
        close=f.ledger.requests(journal.BINDING)[-1]
        expected=(Decimal('.95')*(1+Decimal(target)/100)).quantize(Decimal('.01'),rounding=ROUND_CEILING)
        self.assertEqual((close['contract'],close['instruction'],close['quantity']),
            (contract,'SELL_TO_CLOSE',2))
        self.assertEqual(Decimal(close['limit']),expected)
        self.assertEqual(close['exit_role'],'BROKER_TARGET')
        self.assertEqual(f.gateway.submit.call_count,2)
        # The target is submitted while Bid is below it, before any price touch.
        self.assertLess(Decimal('.95'),Decimal(close['limit']))
        f.broker(close,2,'FILLED',close['limit']);f.service.observe_orders();notices.step()
        self.assertEqual(sender.call_count,2)
        self.assertIn('VENTA REAL CONFIRMADA',sender.call_args.args[0])
        self.assertEqual(f.ledger.available_to_close(journal.BINDING,contract),0)
        queue.step(journal.BINDING,f.service,provider,monitor=False)
        plan=queue.read(journal.BINDING)
        self.assertTrue(plan['entry_consumed'])
        self.assertEqual(plan['rows'][1]['state'],'EXCLUDED_FIRST_ENTRY')
        self.assertEqual(f.gateway.submit.call_count,2)
