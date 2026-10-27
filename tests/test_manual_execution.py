"""Shared manual actions on synthetic quotes and isolated SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from manual_execution import ManualReviews,ManualWorkflow,configured_workflow,EntryNotDispatched
from manual_trade_service import ManualMarketData,ManualDataError
from schwab_simulation import SimulationEngine,SimulationLedger,LocalPaperBroker,ExecutionBlocked
from tests import test_schwab_simulation as f
from tests.test_manual_trade_service import state_fixture,payload_fixture


class ManualExecutionTests(unittest.TestCase):
    def setUp(self):
        # Explicit historical10% fixtures; current policy has separate stop20 tests.
        from option_exit_plan import GlobalExitPolicy
        for name in ('schwab_simulation.load_global_exit_policy','manual_execution.load_global_exit_policy'):
            context=patch(name,return_value=GlobalExitPolicy(Decimal('10'),True))
            context.start();self.addCleanup(context.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=f.NOW;self.state=state_fixture()
        self.payload=payload_fixture();self.code=f.synthetic_contract().snapshot.symbol
        self.client=Mock();self.client.full_chain.side_effect=lambda *a:deepcopy(self.payload)
        self.market=ManualMarketData(self.client,verified_increments={self.code:'.05'},fee_per_contract='.65')
        self.policy=f.synthetic_policy(stop_loss_pct=Decimal('10'))
        self.engine=SimulationEngine(SimulationLedger(self.root/'ledger.db'),LocalPaperBroker(self.root/'broker.db'),self.policy)
        self.service=self.build()

    def build(self):
        return ManualWorkflow(self.engine,ManualReviews(self.root/'reviews.db'),
            read_state=lambda symbol:deepcopy(self.state),market_data=self.market,clock=lambda:self.now)

    def quote(self,bid=1.95,ask=2.,seconds=1,size=10):
        self.now=f.NOW+timedelta(seconds=seconds)
        self.state=state_fixture(self.now)
        q=self.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q.update(bid=bid,ask=ask,bidSize=size,askSize=size,quoteTimeInLong=int(self.now.timestamp()*1000))
        self.market.cache.clear()

    def prepare(self,target='MANUAL',quantity=3,owner='owner'):
        return self.service.prepare_buy(owner,'AMZN','CALL',self.code,quantity,target)

    def enter(self,target='MANUAL',quantity=3):
        return self.service.confirm('owner',self.prepare(target,quantity)['id'])['client_key']

    def filled(self,target='MANUAL',quantity=3):
        key=self.enter(target,quantity);self.quote(seconds=1);self.service.observe()
        self.assertEqual(self.engine.ledger.order(key)['status'],'FILLED')
        return key

    def test_preparation_is_persisted_but_never_submits_and_no_default_quantity_target(self):
        r=self.prepare()
        self.assertEqual(self.engine.ledger.orders(),[])
        self.assertEqual(r['stop'],'10');self.assertEqual(r['target'],'MANUAL')
        for qty,target in [(None,'MANUAL'),(True,'MANUAL'),(0,'MANUAL'),(3,None),(3,15)]:
            with self.subTest(qty=qty,target=target),self.assertRaises((ValueError,TypeError)):
                self.prepare(target,qty)

    def test_observer_provider_wait_does_not_hold_entry_mutation_lock(self):
        from threading import Event,Thread
        self.enter();self.quote(seconds=1)
        started=Event();release=Event();errors=[]
        original=self.client.full_chain.side_effect
        def delayed(*args):
            started.set()
            if not release.wait(3):raise RuntimeError('TEST_TIMEOUT')
            return original(*args)
        self.client.full_chain.side_effect=delayed
        def observe():
            try:self.service.observe()
            except Exception as error:errors.append(error)
        worker=Thread(target=observe);worker.start()
        try:
            self.assertTrue(started.wait(2))
            acquired=self.service.lock.acquire(timeout=.2)
            if acquired:self.service.lock.release()
            self.assertTrue(acquired,'Provider wait blocked the entry mutation lock')
        finally:release.set();worker.join(4)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])

    def test_cancellation_during_quote_lookup_is_rechecked_before_matching(self):
        key=self.enter();self.quote(seconds=1)
        original=self.client.full_chain.side_effect
        def cancel_during_lookup(*args):
            row=self.engine.ledger.order(key)
            with self.service.lock:
                self.engine.broker.acknowledge_cancel(row['broker_id'])
                self.service._reconcile(self.now)
            return original(*args)
        self.client.full_chain.side_effect=cancel_during_lookup
        self.service.observe()
        self.assertEqual(self.engine.ledger.order(key)['status'],'CANCELED')
        self.assertEqual(self.service.positions(),[])

    def test_quote_failure_does_not_skip_healthy_position_stop(self):
        self.filled();self.quote(bid=1.6,ask=1.65,seconds=2)
        positions=self.service.positions()
        unavailable=dict(positions[0],symbol='UNAVAILABLE',contract='UNAVAILABLE')
        original=self.service._observation_market
        def quotes(symbol,contract,**kwargs):
            if symbol=='UNAVAILABLE':raise ManualDataError('MARKET_DATA_UNAVAILABLE')
            return original(symbol,contract,**kwargs)
        with patch.object(self.service,'positions',return_value=[unavailable,*positions]),\
             patch.object(self.service,'_observation_market',side_effect=quotes):
            with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_UNAVAILABLE'):
                self.service.observe()
        exits=[r for r in self.engine.ledger.orders() if r['order']['instruction']=='SELL_TO_CLOSE']
        self.assertEqual(len(exits),1);self.assertEqual(exits[0]['order']['exit_reason'],'LOSS_LIMIT')

    def test_owner_binding_then_single_use_across_service_restart(self):
        r=self.prepare()
        with self.assertRaisesRegex(ExecutionBlocked,'REVIEW_NOT_FOUND'):
            self.service.confirm('other',r['id'])
        result=self.build().confirm('owner',r['id'])
        self.assertEqual(result['status'],'WORKING');self.assertFalse(result['real_orders_enabled'])
        with self.assertRaisesRegex(ExecutionBlocked,'ALREADY_USED'):
            self.service.confirm('owner',r['id'])
        self.assertEqual(len(self.engine.broker.snapshot()),1)

    def test_app_and_chat_cannot_duplicate_same_signal_using_different_reviews(self):
        first=self.prepare(owner='app');second=self.prepare(owner='chat')
        self.service.confirm('app',first['id'])
        with self.assertRaisesRegex(ExecutionBlocked,'DUPLICATE'):
            self.service.confirm('chat',second['id'])
        self.assertEqual(len(self.engine.broker.snapshot()),1)

    def test_concurrent_confirmation_claims_once(self):
        r=self.prepare()
        def run(_):
            try:return self.build().confirm('owner',r['id'])['status']
            except ExecutionBlocked:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(sorted(results),['WORKING','blocked'])
        self.assertEqual(len(self.engine.broker.snapshot()),1)

    def test_fresh_lookup_bypasses_cache_and_changed_ask_needs_new_review(self):
        r=self.prepare();self.assertEqual(self.client.full_chain.call_count,1)
        self.payload['callExpDateMap']['2026-10-23:7']['100.0'][0].update(bid=1.9,ask=1.95)
        with self.assertRaisesRegex(ExecutionBlocked,'ASK_CHANGED'):
            self.service.confirm('owner',r['id'])
        self.assertEqual(self.client.full_chain.call_count,2)
        self.assertEqual(self.engine.ledger.orders(),[])

    def test_old_future_retracted_or_different_candle_reviews_cannot_submit(self):
        for mode in ('old','future','retracted','candle'):
            with self.subTest(mode=mode):
                self.now=f.NOW;self.state=state_fixture();r=self.prepare()
                if mode=='old':self.now=f.NOW+timedelta(seconds=31)
                elif mode=='future':self.now=f.NOW-timedelta(microseconds=1)
                elif mode=='retracted':self.state['tick']['signal']=None
                else:self.quote(seconds=15*60)
                with self.assertRaises((ValueError,ExecutionBlocked,ManualDataError)):
                    self.service.confirm('owner',r['id'])
        self.assertEqual(self.engine.ledger.orders(),[])

    def test_manual_close_after_signal_retracts_and_before_stop(self):
        self.filled();self.quote(bid=1.9,ask=1.95,seconds=2);self.state['tick']['signal']=None
        r=self.service.prepare_close('owner',self.code)
        self.assertEqual(r['quantity'],3);self.assertEqual(r['minimum_price'],'1.90')
        result=self.service.confirm('owner',r['id']);self.assertEqual(result['reason'],'MANUAL_CLOSE')
        self.assertEqual(self.service.positions()[0]['quantity'],3) #Pending is NOT closed.
        self.quote(bid=1.9,ask=1.95,seconds=3);self.service.observe()
        self.assertEqual(self.service.positions(),[])

    def test_changed_bid_or_quantity_invalidates_close_review(self):
        self.filled();r=self.service.prepare_close('owner',self.code)
        self.quote(bid=1.9,ask=1.95,seconds=2)
        with self.assertRaisesRegex(ExecutionBlocked,'PRICE_CHANGED'):
            self.service.confirm('owner',r['id'])
        self.assertEqual(len(self.engine.broker.snapshot()),1)

    def test_automatic_stop_and_manual_click_share_one_exit(self):
        self.filled();self.quote(bid=1.6,ask=1.65,seconds=2)
        r=self.service.prepare_close('owner',self.code)
        events=self.service.observe();self.assertEqual(events[0]['reason'],'LOSS_LIMIT')
        result=self.service.confirm('owner',r['id'])
        self.assertEqual(result['status'],'EXIT_ALREADY_PENDING')
        self.assertEqual(len(self.engine.broker.snapshot()),2)

    def test_all_four_target_choices_and_manual_preserve_global_stop(self):
        for target in ('10','20','35','100','MANUAL'):
            r=self.prepare(target);self.assertEqual(r['stop'],'10');self.assertEqual(r['target'],target)

    def test_partial_entry_cancel_ack_reconcile_then_close_only_filled(self):
        key=self.enter();self.quote(seconds=1,size=1)
        with self.assertRaisesRegex(ExecutionBlocked,'CANCELLATION'):
            self.service.observe()
        r=self.service.prepare_cancel('owner',key)
        self.assertEqual(self.service.confirm('owner',r['id'])['status'],'CANCELED')
        self.quote(bid=1.9,ask=1.95,seconds=2)
        r=self.service.prepare_close('owner',self.code)
        self.assertEqual(r['quantity'],1)
        self.assertEqual(self.service.confirm('owner',r['id'])['quantity'],1)

    def test_repeated_observation_does_not_reuse_quote_liquidity(self):
        self.engine.policy=replace(self.policy,risk=replace(self.policy.risk,max_position_cost=4000.))
        key=self.enter(quantity=12);self.quote(seconds=1,size=10)
        for _ in range(2):
            with self.assertRaises(ExecutionBlocked):self.service.observe()
        self.assertEqual(self.engine.ledger.order(key)['filled_quantity'],10)

    def test_unknown_dispatch_does_not_retry_after_restart(self):
        r=self.prepare()
        with patch.object(self.engine.broker,'accept',side_effect=TimeoutError):
            result=self.service.confirm('owner',r['id'])
        self.assertEqual(result['status'],'UNKNOWN')
        with self.assertRaisesRegex(ExecutionBlocked,'ALREADY_USED'):
            self.build().confirm('owner',r['id'])
        self.assertEqual(self.engine.broker.snapshot(),[])

    def test_account_or_policy_change_blocks_review_without_rewriting_plan(self):
        r=self.prepare();self.engine.policy=replace(self.policy,account_alias='OTHER_TEST')
        with self.assertRaisesRegex(ExecutionBlocked,'ACCOUNT_CHANGED'):
            self.service.confirm('owner',r['id'])
        self.assertEqual(self.engine.ledger.orders(),[])

    def test_fill_racing_with_cancel_is_reconciled_as_filled_not_canceled(self):
        key=self.enter();r=self.service.prepare_cancel('owner',key)
        self.engine.broker.match_quote(self.engine.ledger.order(key)['broker_id'],f.synthetic_contract(),
            now=self.now,execution_id='SYNTHETIC_RACING_FILL')
        result=self.service.confirm('owner',r['id'])
        self.assertEqual(result['status'],'FILLED')
        self.assertEqual(self.service.positions()[0]['quantity'],3)

    def test_policy_change_or_closed_session_blocks_before_dispatch(self):
        r=self.prepare();self.engine.policy=replace(self.policy,max_holding_minutes=25)
        with self.assertRaisesRegex(ExecutionBlocked,'POLICY_CHANGED'):
            self.service.confirm('owner',r['id'])
        self.engine.policy=self.policy;r=self.prepare();self.state['session']=None
        with self.assertRaises(EntryNotDispatched):self.service.confirm('owner',r['id'])
        self.assertEqual(self.engine.broker.snapshot(),[])

    def test_private_missing_or_live_or_incomplete_configuration_creates_no_database(self):
        root=self.root/'not_created'
        template=json.loads(Path('config/schwab_automation.example.json').read_text())
        for p in ({'real_orders_enabled':True},{'real_orders_enabled':False},
                  {'real_orders_enabled':False,'manual_simulation_policy':template}):
            with self.subTest(p=p),self.assertRaises(ExecutionBlocked):
                configured_workflow(p,root,read_state=lambda symbol:self.state,market_data=self.market)
            self.assertFalse(root.exists())

    def test_missing_verified_fees_blocks_factory_before_creating_databases(self):
        root=self.root/'not_created'
        payload=asdict(self.policy)|{'mode':'LOCAL_SIMULATION','real_orders_enabled':False}
        self.market.fee_per_contract=None
        with self.assertRaisesRegex(ExecutionBlocked,'VERIFIED_FEES_REQUIRED'):
            configured_workflow({'real_orders_enabled':False,'manual_simulation_policy':payload},root,
                read_state=lambda symbol:self.state,market_data=self.market)
        self.assertFalse(root.exists())


if __name__=='__main__':unittest.main()
