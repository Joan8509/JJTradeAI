"""Isolated fixtures only. No private config, broker API or messages."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from tests.test_manual_execution import ManualExecutionTests
from manual_execution import configured_workflow
from schwab_simulation import ManualPracticePolicy,AutomationPolicy,ExecutionBlocked
from manual_practice_report import practice_summary
from position_monitor import position_mark
from trade_close_reporting import sale_reports,format_sale_notice


class ManualPracticeTests(unittest.TestCase):
    def setUp(self):
        h=self.h=ManualExecutionTests('runTest');h.setUp();self.addCleanup(h.doCleanups)
        h.engine.policy=ManualPracticePolicy()
        h.market.increments={};h.market.fee_per_contract=None

    def test_manual_quantity_target_ask_and_unknown_costs(self):
        h=self.h;r=h.prepare(target='35',quantity=7)
        self.assertEqual(r['entry_cost'],'1400.0');self.assertFalse(r['fees_known'])
        key=h.service.confirm('owner',r['id'])['client_key'];order=h.engine.ledger.order(key)['order']
        self.assertEqual(order['quantity'],7);self.assertEqual(Decimal(order['limit']),2)
        self.assertIsNone(order['plan']['increment']);self.assertIsNone(order['plan']['max_holding_minutes'])
        self.assertEqual(order['plan']['target_pct'],'35');self.assertFalse(order['fees_known'])

    def test_observed_quotes_no_invented_tick_and_full_stop_cycle(self):
        h=self.h;h.filled(quantity=2)
        h.quote(bid=1.6,ask=1.65,seconds=2)
        result=h.service.observe()[0];self.assertEqual(result['reason'],'LOSS_LIMIT')
        h.quote(bid=1.6,ask=1.65,seconds=3);h.service.observe()
        reports=sale_reports(h.engine.ledger,h.engine.policy.account_alias,now=h.now)
        self.assertEqual(reports[0]['gross_pnl'],Decimal('-80'))
        self.assertIsNone(reports[0]['net_pnl']);self.assertIsNone(reports[0]['fees'])
        self.assertIn('Neto no disponible',format_sale_notice(reports[0]))
        s=practice_summary(h.engine.ledger,h.engine.policy.account_alias,now=h.now)
        self.assertEqual(s['closed_trades'],1);self.assertEqual(s['closed_win_rate_pct'],0)
        self.assertEqual(s['closed_realized_drawdown'],80);self.assertEqual(s['remaining_contracts'],0)

    def test_percent_target_sells_at_observed_bid_and_manual_always_available(self):
        h=self.h;h.filled(target='10')
        h.quote(bid=2.23,ask=2.27,seconds=2)
        review=h.service.prepare_close('owner',h.code)
        self.assertEqual(review['action'],'CLOSE')
        result=h.service.observe()[0];self.assertEqual(result['reason'],'TARGET')
        self.assertEqual(Decimal(result['limit']),Decimal('2.23'))
        with self.assertRaisesRegex(ExecutionBlocked,'NO_FILLED_POSITION'):
            h.service.confirm('owner',review['id'])
        self.assertEqual(len(h.engine.broker.snapshot()),2)

    def test_live_mark_gross_only_and_no_invented_time_exit(self):
        h=self.h;h.filled(target='MANUAL')
        h.quote(bid=1.9,ask=1.95,seconds=61)
        self.assertEqual(h.service.observe()[0]['status'],'HOLD')
        position=h.service.positions()[0]
        mark=position_mark(position,h.service.position_market(h.code),now=h.now)
        self.assertEqual(mark['status'],'LIVE');self.assertIsNone(mark['net_estimate'])
        self.assertIsNone(mark['target']);self.assertEqual(mark['stop'],Decimal('1.8'))

    def test_duplicates_stale_retraction_spread_keep_original_gates(self):
        h=self.h;first=h.prepare();second=h.prepare();h.service.confirm('owner',first['id'])
        with self.assertRaisesRegex(ExecutionBlocked,'DUPLICATE'):
            h.service.confirm('owner',second['id'])
        for scenario in ('stale','retracted','spread'):
            h.now=h.now+timedelta(seconds=1);h.quote(seconds=int((h.now-h.now.replace(second=0)).total_seconds())+5)
            if scenario=='stale':h.now+=timedelta(seconds=31)
            elif scenario=='retracted':h.state['tick']['signal']=None
            else:h.quote(bid=1.9,ask=2.,seconds=10)
            with self.subTest(scenario=scenario),self.assertRaises(Exception):h.prepare()
        self.assertEqual(len(h.engine.broker.snapshot()),1)

    def test_quote_liquidity_not_reused_and_no_unfilled_win_statistics(self):
        h=self.h;h.enter(quantity=3);h.quote(seconds=1,size=1)
        self.assertEqual(h.service.observe()[0]['status'],'HOLD')
        row=h.engine.ledger.orders()[0];contract=h.market.get_chain('AMZN','CALL',h.now).chain.contracts[0]
        self.assertEqual(h.engine.broker.match_quote(row['broker_id'],contract,now=h.now,execution_id='another'),0)
        s=practice_summary(h.engine.ledger,h.engine.policy.account_alias,now=h.now)
        self.assertIsNone(s['closed_win_rate_pct']);self.assertEqual(s['remaining_contracts'],1)

    def test_partial_entry_cancels_remaining_before_stop_instead_of_buying_more(self):
        h=self.h;key=h.enter(quantity=3);h.quote(seconds=1,size=1);h.service.observe()
        self.assertEqual(h.engine.ledger.order(key)['filled_quantity'],1)
        h.quote(bid=1.6,ask=1.65,seconds=2,size=10);h.service.observe()
        self.assertEqual(h.engine.ledger.order(key)['status'],'CANCELED')
        self.assertEqual(h.engine.ledger.order(key)['filled_quantity'],1)
        exits=[r for r in h.engine.ledger.orders() if r['order']['instruction']=='SELL_TO_CLOSE']
        self.assertEqual(len(exits),1);self.assertEqual(exits[0]['order']['quantity'],1)
        h.quote(bid=1.6,ask=1.65,seconds=3);h.service.observe()
        self.assertEqual(h.service.positions(),[])
        report=sale_reports(h.engine.ledger,h.engine.policy.account_alias,now=h.now)[0]
        self.assertEqual(report['gross_pnl'],-40);self.assertEqual(report['sold_quantity'],1)

    def test_strict_policy_still_incomplete_and_missing_tick_blocks_original_mode(self):
        with self.assertRaisesRegex(ExecutionBlocked,'POLICY_INCOMPLETE'):AutomationPolicy().require_complete()
        h=self.h
        from tests.test_schwab_simulation import synthetic_policy
        h.engine.policy=synthetic_policy(stop_loss_pct=Decimal('10'));h.market.fee_per_contract='.65'
        with self.assertRaises(ValueError):h.prepare()

    def test_factory_is_explicit_separate_and_conflicts_fail_before_mutation(self):
        h=self.h
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for profile in ({'real_orders_enabled':False},
                {'real_orders_enabled':True,'manual_practice_enabled':True},
                {'real_orders_enabled':False,'api_product':'MARKET_DATA_ONLY','manual_practice_enabled':True,'manual_simulation_policy':{}}):
                with self.assertRaises(ExecutionBlocked):configured_workflow(profile,root,read_state=lambda _:h.state,market_data=h.market)
                self.assertEqual(list(root.iterdir()),[])
            service=configured_workflow({'real_orders_enabled':False,'api_product':'MARKET_DATA_ONLY','manual_practice_enabled':True},
                root,read_state=lambda _:deepcopy(h.state),market_data=h.market)
            self.assertEqual(service.engine.ledger.path.parent.name,'observed_manual_v1')
            self.assertIs(type(service.engine.policy),ManualPracticePolicy)

    def test_telegram_owner_bound_single_buy_then_confirmed_gross_sale(self):
        from tests import test_telegram_manual as tf
        from telegram_manual import TelegramManualService,TelegramManualStore,TelegramManualError
        from urllib.parse import urlsplit,parse_qs
        h=self.h;service=TelegramManualService(h.service,TelegramManualStore(h.root/'tg.db'),
            token=tf.TOKEN,user_id=tf.OWNER,base_url='https://jj.example/telegram/')
        draft=service.begin('AMZN','CALL',h.state['tick']['signal']['candle']);service.card(draft)
        for action in ('c0','q3','t10'):
            draft=service.change(draft['id'],draft['version'],action);card=service.card(draft)
        self.assertIn('sin comisiones verificadas',card['text'])
        intent=parse_qs(urlsplit(card['reply_markup']['inline_keyboard'][-1][0]['web_app']['url']).fragment)['intent'][0]
        with self.assertRaises(TelegramManualError):service.execute('unsigned',intent)
        raw=tf.signed(h.now);first=service.execute(raw,intent);service.execute(raw,intent)
        self.assertEqual(first['quantity'],3);self.assertEqual(len(h.engine.broker.snapshot()),1)
        h.quote(seconds=1);h.service.observe()
        h.quote(bid=2.2,ask=2.25,seconds=2);h.service.observe()
        h.quote(bid=2.2,ask=2.25,seconds=3);h.service.observe()
        receipt=service.state(tf.signed(h.now),intent)
        self.assertFalse(receipt['position_open']);self.assertEqual(receipt['sale_report']['gross_pnl'],60)
        self.assertIsNone(receipt['sale_report']['net_pnl'])

    def test_future_live_transport_stays_unconditionally_disabled(self):
        from schwab_connection import DisabledLiveExecution,SchwabError
        with self.assertRaisesRegex(SchwabError,'REAL_ORDERS_DISABLED'):DisabledLiveExecution().dispatch({})

    def test_monitor_readiness_blocks_buy_but_never_manual_exit(self):
        h=self.h;h.service.entry_ready=lambda:False
        with self.assertRaisesRegex(ExecutionBlocked,'MONITOR_NOT_READY'):h.prepare()
        h.service.entry_ready=lambda:True;h.filled()
        h.service.entry_ready=lambda:False
        self.assertEqual(h.service.prepare_close('owner',h.code)['action'],'CLOSE')

    def test_private_opt_in_preserves_other_fields_and_ciphertext_backup(self):
        from contextlib import nullcontext
        from scripts.enable_connected_manual_practice import enable
        h=self.h
        class FakeStore:
            path=h.root/'synthetic.dpapi'
            value={'real_orders_enabled':False,'api_product':'MARKET_DATA_ONLY','tokens':{'opaque':'fixture-only'},'other':{'preserve':1}}
            def locked(self):return nullcontext()
            def load(self):return deepcopy(self.value)
            def save(self,value):self.value=deepcopy(value)
        store=FakeStore();store.path.write_bytes(b'fake-encrypted-fixture')
        result=enable(store,now=h.now)
        self.assertFalse(result['real_orders_enabled']);self.assertTrue(store.value['manual_practice_enabled'])
        self.assertEqual(store.value['tokens'],{'opaque':'fixture-only'});self.assertNotIn('opaque',str(result))
        self.assertEqual(len(list(h.root.glob('schwab.before_manual_practice.*.dpapi'))),1)
        self.assertEqual(enable(store,now=h.now)['status'],'ALREADY_CONFIGURED')
