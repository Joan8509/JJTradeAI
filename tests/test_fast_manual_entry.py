"""Direct UI selection uses synthetic feeds and isolated SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from copy import deepcopy
import unittest

from fast_manual_entry import FastManualEntry
from tests import test_telegram_manual as telegram_fixture


class FastEntryTests(unittest.TestCase):
    def setUp(self):
        self.h=telegram_fixture.TelegramServiceTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.f=self.h.f;self.entry=FastManualEntry(self.h.service)
        self.candle=self.f.state['tick']['signal']['candle']

    def raw(self):return self.h.raw()

    def buy(self,**changes):
        values=dict(symbol='AMZN',side='CALL',candle=self.candle,contract=self.f.code,quantity=3,
            target='35',ask='2.00',total='601.95',stop='10',request_id='11111111111111111111111111111111')
        values.update(changes)
        return self.entry.buy(self.raw(),**values)

    def test_open_catalog_and_local_selections_do_not_prepare_or_submit(self):
        data=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(data['buy_ready']);self.assertEqual(len(data['contracts']),1)
        self.assertEqual(data['stop'],'10');self.assertFalse(data['real_orders_enabled'])
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.assertEqual(self.h.store.read('SELECT id FROM telegram_intents'),[])
        self.assertEqual(self.f.service.reviews.read('SELECT id FROM manual_reviews'),[])

    def test_direct_entry_with_current_fast_tick_works_while_display_and_poller_lag(self):
        self.f.state['radar']=None
        self.h.service.operational_check=lambda:False
        self.h.service.direct_operational_check=lambda:True
        self.assertTrue(self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)['buy_ready'])
        result=self.buy();self.assertEqual(result['status'],'WORKING')
        self.assertEqual(result['selection']['quantity'],3);self.assertEqual(result['selection']['stop'],'10')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_readonly_diagnostics_never_create_review_or_actionable_contract(self):
        from tests.test_schwab_simulation import synthetic_contract
        from dataclasses import replace
        market=self.f.market.get_chain('AMZN','CALL',self.f.now)
        observed=(synthetic_contract(now=self.f.now,strike=103.,bid=2.81,ask=2.88),
            synthetic_contract(now=self.f.now,strike=105.,bid=1.57,ask=1.62))
        market=replace(market,chain=replace(market.chain,contracts=observed))
        with patch.object(self.f.market,'get_chain',return_value=market):
            data=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertEqual(data['reason'],'NO_ELIGIBLE_CONTRACTS')
        self.assertFalse(data['buy_ready']);self.assertEqual(data['contracts'],[])
        self.assertEqual(data['contract_diagnostics']['counts']['eligible'],0)
        self.assertEqual(len(data['contract_diagnostics']['observed']),2)
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.assertEqual(self.h.store.read('SELECT id FROM telegram_intents'),[])
        self.assertEqual(self.f.service.reviews.read('SELECT id FROM manual_reviews'),[])

    def test_optional_diagnostic_failure_never_changes_valid_catalog(self):
        with patch('fast_manual_entry.contract_diagnostics',side_effect=ValueError('PRIVATE_ERROR')):
            data=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(data['buy_ready']);self.assertEqual(len(data['contracts']),1)
        self.assertNotIn('contract_diagnostics',data);self.assertIsNone(data['reason'])
        self.assertNotIn('PRIVATE_ERROR',str(data))
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_duplicate_or_uncertain_launch_never_submits_again_even_with_new_request_id(self):
        first=self.buy();self.assertEqual(first['status'],'WORKING')
        duplicate=self.buy(request_id='22222222222222222222222222222222',quantity=5,total='1003.25')
        self.assertEqual(duplicate['intent'],first['intent']);self.assertEqual(duplicate['selection']['quantity'],3)
        self.assertEqual(self.entry.result(self.raw())['intent'],first['intent'])
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_concurrent_double_click_claims_before_market_lookup_and_dispatches_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.buy(),range(2)))
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)
        self.assertTrue(any(r['status']=='WORKING' for r in results))

    def test_real_retraction_stale_trade_and_exit_monitor_failure_block_without_dispatch(self):
        for mode in ('retracted','stale','monitor'):
            with self.subTest(mode=mode):
                old_signal=self.f.state['tick']['signal'];old_stamp=self.f.state['tick']['source_timestamp']
                try:
                    if mode=='retracted':self.f.state['tick']['signal']=None
                    elif mode=='stale':self.f.state['tick']['source_timestamp']=(self.f.now-timedelta(seconds=4)).isoformat()
                    else:self.h.service.direct_operational_check=lambda:False
                    result=self.buy(request_id=mode.ljust(32,'a'))
                    self.assertEqual(result['status'],'ENTRY_BLOCKED')
                    self.assertEqual(self.f.engine.broker.snapshot(),[])
                    self.assertEqual(self.h.store.read('SELECT id FROM telegram_intents'),[])
                finally:
                    self.f.state['tick']['signal']=old_signal;self.f.state['tick']['source_timestamp']=old_stamp
                    self.h.service.direct_operational_check=None

    def test_changed_visible_price_stop_total_or_candle_never_becomes_an_order(self):
        for index,change in enumerate(({'ask':'2.01'},{'total':'600'},{'stop':'20'},
                                       {'candle':(self.f.now-timedelta(minutes=15)).isoformat()})):
            result=self.buy(request_id=str(index).ljust(32,'a'),**change)
            self.assertEqual(result['status'],'ENTRY_BLOCKED');self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_same_blocked_request_does_not_reexecute_but_new_explicit_request_can_recheck(self):
        self.f.state['tick']['signal']=None
        blocked=self.buy();self.assertEqual(blocked['status'],'ENTRY_BLOCKED')
        self.f.quote(seconds=1)
        self.assertEqual(self.buy()['status'],'ENTRY_BLOCKED')
        self.assertEqual(self.buy(request_id='22222222222222222222222222222222')['status'],'WORKING')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_unknown_costs_keep_manual_rules_and_fills_reconcile_without_real_orders(self):
        from schwab_simulation import ManualPracticePolicy
        self.f.engine.policy=ManualPracticePolicy();self.f.market.fee_per_contract=None;self.f.market.increments={}
        result=self.buy(total='600');self.assertEqual(result['status'],'WORKING')
        self.f.quote(seconds=1);self.f.service.observe()
        receipt=self.entry.result(self.raw());self.assertEqual(receipt['status'],'FILLED')
        self.assertFalse(receipt['real_orders_enabled']);self.assertEqual(receipt['mark']['stop'],Decimal('1.80'))
        self.assertIsNone(receipt['mark']['net_estimate'])

    def test_forged_identity_and_absent_quantity_never_prepare(self):
        with self.assertRaisesRegex(ValueError,'TELEGRAM_AUTH_REQUIRED'):
            self.entry.catalog('forged','AMZN','CALL',self.candle)
        for quantity in (None,True,0):
            with self.assertRaises(ValueError):self.buy(quantity=quantity)
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_initial_retraction_allows_preparation_then_recovers_without_a_new_notice(self):
        self.f.state['tick']['signal']=None;self.f.state['tick']['reason']='READY_NO_EXIT'
        data=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(data['preparation_ready']);self.assertFalse(data['signal_ready']);self.assertFalse(data['buy_ready'])
        self.assertEqual(data['signal_reason'],'NO_CURRENT_SIGNAL');self.assertEqual(len(data['contracts']),1)
        self.assertEqual(self.h.store.read('SELECT id FROM telegram_intents'),[])
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.f.quote(seconds=1)
        recovered=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(recovered['signal_ready']);self.assertTrue(recovered['buy_ready'])
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.assertEqual(self.buy()['status'],'WORKING')

    def test_retraction_during_final_validation_does_not_permanently_consume_launch(self):
        original=self.f.service._entry
        def retract(*args,**kwargs):
            if kwargs.get('force'):self.f.state['tick']['signal']=None
            return original(*args,**kwargs)
        with patch.object(self.f.service,'_entry',side_effect=retract):blocked=self.buy()
        self.assertEqual(blocked['status'],'ENTRY_BLOCKED');self.assertEqual(blocked['reason'],'NO_CURRENT_SIGNAL')
        self.assertNotIn('intent',blocked);self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.assertEqual(self.h.store.read('SELECT state FROM telegram_intents')[0]['state'],'BLOCKED_BEFORE_DISPATCH')
        self.f.quote(seconds=1)
        self.assertEqual(self.buy()['status'],'ENTRY_BLOCKED')  # Same request is never executed again.
        self.assertEqual(self.buy(request_id='2'*32)['status'],'WORKING')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_unknown_exception_after_dispatch_boundary_never_releases_launch(self):
        with patch.object(self.f.engine,'enter',side_effect=TimeoutError) as enter:
            first=self.buy();second=self.buy(request_id='2'*32)
        self.assertEqual(first['status'],'BLOCKED_OR_UNCERTAIN');self.assertEqual(second['intent'],first['intent'])
        self.assertEqual(enter.call_count,1)

    def test_expired_purchase_auth_is_distinct_and_preparation_remains_non_actionable(self):
        raw=self.raw();self.f.quote(seconds=121)
        data=self.entry.catalog(raw,'AMZN','CALL',self.candle)
        self.assertTrue(data['preparation_ready']);self.assertFalse(data['access_ready']);self.assertFalse(data['buy_ready'])
        self.assertEqual(data['reason'],'TELEGRAM_AUTH_REQUIRED')
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_diagnostics_only_store_fixed_codes_not_identity_or_authentication_data(self):
        self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        rows=self.h.store.read('SELECT * FROM telegram_entry_checks')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['stage'],'CATALOG')
        self.assertNotIn('SIGNED',str(rows));self.assertNotIn('query',str(rows));self.assertNotIn(self.h.service.token,str(rows))

    def test_old_candle_requires_explicit_current_reference_never_silent_rollover(self):
        self.f.quote(seconds=900)
        data=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertEqual(data['reason'],'SIGNAL_CHANGED');self.assertFalse(data['buy_ready'])
        self.assertEqual(data['current_candle'],self.f.state['tick']['signal']['candle'])
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_changed_ask_before_dispatch_can_be_reviewed_again_but_not_replayed(self):
        original=self.f.service._entry
        def changed(*args,**kwargs):
            if kwargs.get('force'):
                q=self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
                q.update(bid=1.90,ask=1.95)
            return original(*args,**kwargs)
        with patch.object(self.f.service,'_entry',side_effect=changed):result=self.buy()
        self.assertEqual(result['status'],'ENTRY_BLOCKED');self.assertEqual(result['reason'],'MANUAL_CONFIRMATION_ASK_CHANGED')
        self.assertNotIn('intent',result);self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.f.quote(bid=1.90,ask=1.95,seconds=1)
        result=self.buy(request_id='2'*32,ask='1.95',total='586.95')
        self.assertEqual(result['status'],'WORKING');self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_missing_company_premium_range_has_explicit_reason_and_no_market_or_order_call(self):
        with patch('fast_manual_entry.optimal_option_premium',side_effect=ValueError('OPTIMAL_PREMIUM_RANGE_MISSING')):
            data=self.entry.catalog(self.raw(),'SPCX','CALL',self.candle)
        self.assertEqual(data['reason'],'OPTIMAL_PREMIUM_RANGE_MISSING');self.assertFalse(data['buy_ready'])
        self.assertEqual(self.f.client.full_chain.call_count,0);self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_eligible_strategy_with_no_option_contract_is_not_reported_as_retraction(self):
        self.f.payload['callExpDateMap']={}
        data=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(data['signal_ready']);self.assertIsNone(data['signal_reason']);self.assertFalse(data['buy_ready'])
        self.assertEqual(data['contract_reason'],data['reason']);self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_rejection_explains_fresh_spread_failure_instead_of_inventing_timeout(self):
        q=self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0];q['bid']=1.50
        result=self.buy()
        self.assertEqual(result['status'],'ENTRY_BLOCKED')
        self.assertEqual(result['contract_reasons'],['SPREAD_EXCEEDS_MAX'])
        self.assertEqual(self.f.engine.ledger.orders(),[])
        restored=self.entry.catalog(self.raw(),'AMZN','CALL',self.candle)
        self.assertEqual(restored['last_entry_result']['contract_reasons'],['SPREAD_EXCEEDS_MAX'])
