from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timedelta,timezone,date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bollinger_phone_worker import STRATEGY_VERSION
from option_market_data import OptionSnapshot
from option_position_sizing import ManualQuantityConfirmation, manual_entry_cost
from risk_engine import RiskLimits
from schwab_contracts import SchwabContract
from schwab_simulation import (AutomationPolicy, DataControls, SimulationLedger,
    LocalPaperBroker, SimulationEngine, ExecutionBlocked, process_current_signal, validated_signal)

NOW=datetime(2026,10,16,14,0,2,tzinfo=timezone.utc)


def synthetic_policy(**changes):
    """Test amounts only; never an approved user configuration."""
    return replace(AutomationPolicy(account_alias='SYNTHETIC_ACCOUNT',entry_sizing_mode='MANUAL_CONFIRMATION',
        min_dte=1,max_dte=14,min_bid_size=1,min_ask_size=1,max_open_positions=2,
        max_entries_per_day=4,max_daily_entry_cost=Decimal('4000'),max_daily_loss=Decimal('4000'),
        stop_loss_pct=Decimal('10'),max_holding_minutes=30,fee_per_contract=Decimal('.65'),
        entry_limit_rule='AT_ASK_LIMIT',risk=RiskLimits(.5,30.,10.,1,1000.)),**changes)


def synthetic_contract(now=NOW, *, bid=1.95,ask=2.,side='CALL',strike=100.,**changes):
    symbol='AMZN  261023'+('C' if side=='CALL' else 'P')+f'{int(strike*1000):08d}'
    q=OptionSnapshot(symbol,'AMZN',side,strike,date(2026,10,23),bid,ask,10,10,now,
        None,None,.6,None,None,None,'opra')
    return SchwabContract(replace(q,**changes),100,True,Decimal('.05'))


def synthetic_signal():
    return dict(symbol='AMZN',provider='ALPACA',feed='iex',version=STRATEGY_VERSION,
        source_kind='TRADE',reason='EXIT',source_timestamp=NOW.isoformat(),received_at=NOW.isoformat(),
        checked_at=NOW.isoformat(),opening=100.,signal={'side':'SUPERIOR','price':104.,
        'candle':NOW.replace(second=0).isoformat()})


class SchwabSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ledger=SimulationLedger(self.root/'ledger.db');self.broker=LocalPaperBroker(self.root/'broker.db')
        self.policy=synthetic_policy();self.engine=SimulationEngine(self.ledger,self.broker,self.policy)
        self.signal=synthetic_signal()
        self.runtime=dict(state='CONECTADO',feed='iex',heartbeat=NOW.isoformat())
        self.controls=DataControls(True,True,True,NOW.replace(hour=13,minute=30,second=0),NOW.replace(hour=20,second=0))

    def enter(self, *, engine=None, signal=None, contract=None, now=NOW, **changes):
        changes.setdefault('listed_expirations',(date(2026,10,23),))
        if 'manual_confirmation' not in changes:
            changes['manual_confirmation']=self.confirmation(engine=engine,signal=signal,contract=contract,now=now)
        return (engine or self.engine).enter(signal or self.signal,self.runtime,self.controls,
            contract or synthetic_contract(),now,now,**changes)

    def confirmation(self, *, quantity=3, engine=None, signal=None, contract=None, now=NOW):
        """Explicit synthetic per-order review; never a production default quantity."""
        engine=engine or self.engine;signal=signal or self.signal;contract=contract or synthetic_contract()
        try:key=validated_signal(signal,self.runtime,self.controls,now)['key']
        except ExecutionBlocked:key='SYNTHETIC_INVALID_SIGNAL'
        quote=contract.snapshot
        return ManualQuantityConfirmation(engine.policy.account_alias,quote.underlying_symbol,
            quote.symbol,key,quantity,Decimal(str(quote.ask)),manual_entry_cost(quote.ask,quantity,'.65'),now)

    def fill(self,key,*,quantity=None,bid=1.95,ask=2.,offset=1,identity='fill-1'):
        stamp=NOW+timedelta(seconds=offset)
        result=self.broker.match_quote(self.ledger.order(key)['broker_id'],
            synthetic_contract(stamp,bid=bid,ask=ask),now=stamp,execution_id=identity,max_quantity=quantity)
        self.assertEqual(self.engine.reconcile(stamp)['status'],'RECONCILED')
        return result

    def test_complete_lifecycle_partial_fills_weighted_target_and_net_fees(self):
        key=self.enter()
        self.assertEqual(self.fill(key,quantity=1,ask=1.95,bid=1.9),1)
        self.assertEqual(self.fill(key,quantity=2,offset=2,identity='fill-2'),2)
        position=self.ledger.portfolio()[synthetic_contract().snapshot.symbol]
        self.assertEqual(position['quantity'],3)
        self.assertEqual(position['premium'],Decimal('595.00'))
        # VWAP1.983333..., 20% ->2.38, rounded UP to verified .05 ->2.40.
        stamp=NOW+timedelta(seconds=3)
        exit=self.engine.manage_exit(synthetic_contract(stamp,bid=2.45,ask=2.5),self.controls,stamp)
        self.assertEqual(exit['reason'],'TARGET');self.assertEqual(Decimal(exit['limit']),Decimal('2.40'))
        self.assertEqual(self.fill(exit['client_key'],quantity=1,bid=2.45,ask=2.5,offset=4,identity='sale-1'),1)
        self.assertEqual(self.fill(exit['client_key'],quantity=2,bid=2.45,ask=2.5,offset=5,identity='sale-2'),2)
        self.assertEqual(self.ledger.portfolio(),{})
        with self.ledger.transaction() as db:
            _,realized=self.ledger._portfolio(db)
        self.assertEqual(sum(pnl for _,pnl in realized),Decimal('136.10'))

    def test_partial_entry_requires_cancel_ack_and_reconciliation_before_exit(self):
        key=self.enter();self.fill(key,quantity=1)
        stamp=NOW+timedelta(seconds=2);quote=synthetic_contract(stamp,bid=2.45,ask=2.5)
        with self.assertRaisesRegex(ExecutionBlocked,'CANCELLATION'):
            self.engine.manage_exit(quote,self.controls,stamp)
        self.broker.acknowledge_cancel(self.ledger.order(key)['broker_id'])
        with self.assertRaises(ExecutionBlocked):
            self.engine.manage_exit(quote,self.controls,stamp)
        self.engine.reconcile(stamp)
        exit=self.engine.manage_exit(quote,self.controls,stamp)
        self.assertEqual(exit['quantity'],1)

    def test_uncertain_ack_survives_restart_no_resubmit_then_exact_local_correlation(self):
        key=self.enter(lose_ack=True)
        self.assertEqual(self.ledger.order(key)['status'],'UNKNOWN')
        self.assertEqual(len(self.broker.snapshot()),1)
        engine=SimulationEngine(SimulationLedger(self.ledger.path),LocalPaperBroker(self.broker.path),self.policy)
        with self.assertRaises(ExecutionBlocked):
            self.enter(engine=engine)
        self.assertEqual(engine.reconcile(NOW)['status'],'RECONCILED')
        self.assertEqual(self.ledger.order(key)['status'],'WORKING')
        with self.assertRaisesRegex(ExecutionBlocked,'DUPLICATE'):
            self.enter(engine=engine)
        self.assertEqual(len(self.broker.snapshot()),1)

    def test_uncertain_never_received_order_does_not_get_resent(self):
        with patch.object(self.broker,'accept',side_effect=TimeoutError):
            key=self.enter()
        self.assertEqual(self.ledger.order(key)['status'],'UNKNOWN')
        self.assertEqual(self.engine.reconcile(NOW)['status'],'BLOCKED')
        with self.assertRaises(ExecutionBlocked):self.enter()
        self.assertEqual(self.broker.snapshot(),[])

    def test_utc_et_alias_and_concurrent_claims_produce_one_order(self):
        def attempt(index):
            signal=json.loads(json.dumps(self.signal))
            if index:signal['signal']['candle']='2026-10-16T10:00:00-04:00'
            try:return self.enter(signal=signal)
            except ExecutionBlocked:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[0,1]))
        self.assertEqual(results.count('blocked'),1)
        self.assertEqual(len(self.broker.snapshot()),1)

    def test_missing_policy_and_data_controls_block_before_order_claim(self):
        engine=SimulationEngine(self.ledger,self.broker,AutomationPolicy())
        with self.assertRaisesRegex(ExecutionBlocked,'POLICY_INCOMPLETE'):
            self.enter(engine=engine)
        for field in ('history_ready','operational_ready','account_reconciled'):
            with self.subTest(field=field),self.assertRaises(ExecutionBlocked):
                self.engine.enter(self.signal,self.runtime,replace(self.controls,**{field:False}),
                    synthetic_contract(),NOW,NOW)
        self.assertEqual(self.ledger.orders(),[])

    def test_stale_future_quarantined_and_retracted_signal_never_enter(self):
        for changes in ({'reason':'CORRECTION_QUARANTINE'},{'signal':None},
            {'source_timestamp':(NOW-timedelta(seconds=3,microseconds=1)).isoformat()},
            {'source_timestamp':(NOW+timedelta(microseconds=1)).isoformat()},
            {'version':'v3'},{'feed':'sip'}):
            signal=dict(self.signal,**changes)
            with self.subTest(changes=changes),self.assertRaises(ExecutionBlocked):self.enter(signal=signal)
        self.assertEqual(self.broker.snapshot(),[])

    def test_quote_lookup_rechecks_retraction_and_elapsed_signal_age(self):
        calls=[0]
        def read():
            calls[0]+=1
            signal=self.signal if calls[0]==1 else dict(self.signal,signal=None)
            return signal,self.runtime,self.controls,NOW
        with self.assertRaises(ExecutionBlocked):
            process_current_signal(self.engine,read_current=read,fetch_contract=lambda *a:synthetic_contract(),clock=lambda:NOW)
        self.assertEqual(self.ledger.orders(),[])
        times=iter([NOW,NOW+timedelta(seconds=4)])
        with self.assertRaises(ExecutionBlocked):
            process_current_signal(self.engine,read_current=lambda:(self.signal,self.runtime,self.controls,NOW),
                fetch_contract=lambda *a:synthetic_contract(),clock=lambda:next(times))

    def test_put_direction_and_contract_identity_cannot_cross(self):
        with self.assertRaisesRegex(ExecutionBlocked,'MISMATCH'):
            self.enter(contract=synthetic_contract(side='PUT',strike=105))
        signal=json.loads(json.dumps(self.signal));signal['signal']['side']='INFERIOR';signal['signal']['price']=96.
        self.enter(signal=signal,contract=synthetic_contract(side='PUT',strike=100))

    def test_daily_risk_and_position_cost_include_rounding_and_fees(self):
        for changes in ({'max_daily_loss':Decimal('600')},{'max_daily_entry_cost':Decimal('600')},
                        {'risk':RiskLimits(.5,30.,10.,1,600.)}):
            engine=SimulationEngine(self.ledger,self.broker,synthetic_policy(**changes))
            with self.subTest(changes=changes),self.assertRaises(ExecutionBlocked):self.enter(engine=engine)
        self.assertEqual(self.ledger.orders(),[])

    def test_user_quantity_is_preserved_and_reviewed_cost_persisted(self):
        contract=synthetic_contract(bid=2.,ask=2.05)
        review=self.confirmation(quantity=4,contract=contract)
        key=self.enter(contract=contract,manual_confirmation=review)
        order=self.ledger.order(key)['order']
        self.assertEqual(order['quantity'],4)
        self.assertEqual(order['entry_sizing_mode'],'MANUAL_CONFIRMATION')
        self.assertEqual(self.broker.snapshot()[0]['order']['quantity'],4)
        cost=(Decimal(order['limit'])*100+Decimal(order['fee_per_contract']))*order['quantity']
        self.assertEqual(cost,Decimal('822.60'))
        self.assertEqual(cost,Decimal(order['reviewed_entry_cost']))

    def test_missing_or_invalid_manual_quantity_cannot_claim_or_send_order(self):
        valid=self.confirmation()
        for review in (None,replace(valid,quantity=0),replace(valid,quantity=-1),
                       replace(valid,quantity=1.5),replace(valid,quantity=True)):
            with self.subTest(review=review),self.assertRaises(ExecutionBlocked):
                self.enter(manual_confirmation=review)
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_changed_contract_account_signal_ask_or_fees_need_new_review(self):
        valid=self.confirmation()
        for changes in ({'contract_symbol':'OTHER'},{'underlying_symbol':'OTHER'},
                {'account_alias':'OTHER'},{'signal_key':'old'},{'ask':Decimal('1.95')},
                {'entry_cost':Decimal('600')},{'confirmed_at':NOW-timedelta(seconds=31)},
                {'confirmed_at':NOW+timedelta(microseconds=1)}):
            with self.subTest(changes=changes),self.assertRaises(ExecutionBlocked):
                self.enter(manual_confirmation=replace(valid,**changes))
        engine=SimulationEngine(self.ledger,self.broker,synthetic_policy(fee_per_contract=Decimal('.66')))
        with self.assertRaisesRegex(ExecutionBlocked,'COST_CHANGED'):
            self.enter(engine=engine,manual_confirmation=valid)
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_manual_quantity_above_risk_cap_is_blocked_not_reduced(self):
        with self.assertRaises(ExecutionBlocked):
            self.enter(manual_confirmation=self.confirmation(quantity=6))
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_entry_methodology_cannot_be_bypassed_by_loose_risk_policy(self):
        # AMZN saved optimal1.40-2.30; wider minimum/maximum are not entry gates.
        for bid,ask,code in ((1.91,2.,'SPREAD'),(1.34,1.39,'OPTIMAL'),
                             (2.26,2.31,'OPTIMAL')):
            with self.subTest(bid=bid,ask=ask),self.assertRaisesRegex(ExecutionBlocked,code):
                self.enter(contract=synthetic_contract(bid=bid,ask=ask))
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_rounded_limit_cannot_escape_optimal_range(self):
        contract=replace(synthetic_contract(bid=2.25,ask=2.29),price_increment=Decimal('.50'))
        with self.assertRaisesRegex(ExecutionBlocked,'OUTSIDE_OPTIMAL'):
            self.enter(contract=contract)
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_selected_ask_is_entry_limit_even_when_bid_is_outside_range(self):
        key=self.enter(contract=synthetic_contract(bid=1.35,ask=1.40))
        order=self.ledger.order(key)['order']
        self.assertEqual(Decimal(order['limit']),Decimal('1.40'))
        self.assertEqual(Decimal(self.broker.snapshot()[0]['order']['limit']),Decimal('1.40'))

    def test_off_tick_ask_is_not_silently_increased_even_inside_range(self):
        with self.assertRaisesRegex(ExecutionBlocked,'ASK_NOT_ON_VERIFIED_TICK'):
            self.enter(contract=synthetic_contract(bid=1.96,ask=2.01))
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_missing_range_blocks_without_any_claim(self):
        with patch('schwab_simulation.optimal_option_premium',side_effect=ValueError('OPTIMAL_PREMIUM_RANGE_MISSING')):
            with self.assertRaisesRegex(ExecutionBlocked,'RANGE_MISSING'):self.enter()
        self.assertEqual(self.ledger.orders(),[])

    def test_wrong_or_missing_expiration_calendar_blocks_before_claim(self):
        for dates,code in ((None,'CALENDAR_REQUIRED'),
                ((date(2026,10,16),date(2026,10,23)),'EXPIRATION_NOT_SELECTED')):
            with self.subTest(dates=dates),self.assertRaisesRegex(ExecutionBlocked,code):
                self.enter(listed_expirations=dates)
        self.assertEqual(self.ledger.orders(),[])
        self.assertEqual(self.broker.snapshot(),[])

    def test_after_two_accepts_next_listed_expiration_when_tomorrow_is_absent(self):
        stamp=NOW.replace(hour=18,minute=0,second=1)
        signal=json.loads(json.dumps(self.signal))
        for field in ('source_timestamp','received_at','checked_at'):signal[field]=stamp.isoformat()
        signal['signal']['candle']=stamp.replace(second=0).isoformat()
        self.runtime['heartbeat']=stamp.isoformat()
        key=self.enter(contract=synthetic_contract(now=stamp),signal=signal,now=stamp,
            listed_expirations=(date(2026,10,16),date(2026,10,23)))
        self.assertEqual(self.ledger.order(key)['status'],'WORKING')
        self.assertEqual(len(self.broker.snapshot()),1)

    def test_same_day_contract_is_allowed_before_two_but_rechecked_at_entry_after_two(self):
        policy=replace(self.policy,min_dte=0,risk=replace(self.policy.risk,min_days_to_expiration=0))
        engine=SimulationEngine(self.ledger,self.broker,policy)
        #October16 is EDT:18:00UTC ==14:00ET. Re-evaluate using entry clock.
        for stamp,allowed in ((NOW.replace(hour=18,minute=0,second=1),False),
                              (NOW.replace(hour=17,minute=59,second=59),True)):
            signal=json.loads(json.dumps(self.signal))
            for field in ('source_timestamp','received_at','checked_at'):signal[field]=stamp.isoformat()
            signal['signal']['candle']=stamp.replace(minute=15*(stamp.minute//15),second=0).isoformat()
            self.runtime['heartbeat']=stamp.isoformat()
            contract=synthetic_contract(now=stamp)
            contract=replace(contract,snapshot=replace(contract.snapshot,
                symbol='AMZN  261016C00100000',expiration=date(2026,10,16)))
            if not allowed:
                with self.assertRaisesRegex(ExecutionBlocked,'EXPIRATION_NOT_SELECTED'):
                    self.enter(engine=engine,contract=contract,signal=signal,now=stamp,
                        listed_expirations=(date(2026,10,16),date(2026,10,17)))
                self.assertEqual(self.ledger.orders(),[])
            else:
                key=self.enter(engine=engine,contract=contract,signal=signal,now=stamp,
                    listed_expirations=(date(2026,10,16),date(2026,10,17)))
                self.assertEqual(self.ledger.order(key)['status'],'WORKING')

    def test_exit_is_not_vetoed_by_entry_range_or_spread(self):
        key=self.enter();self.fill(key);self.ledger.set_paused(True)
        stamp=NOW+timedelta(seconds=2)
        # Above AMZN2.30 entry ceiling and wider than approved entry spread.
        result=self.engine.manage_exit(synthetic_contract(stamp,bid=2.45,ask=2.70),self.controls,stamp)
        self.assertEqual(result['reason'],'TARGET')
        self.assertEqual(result['quantity'],3)

    def test_paused_entries_do_not_disable_existing_position_loss_or_time_management(self):
        key=self.enter();self.fill(key);self.ledger.set_paused(True)
        stamp=NOW+timedelta(seconds=2)
        exit=self.engine.manage_exit(synthetic_contract(stamp,bid=1.75,ask=1.8),self.controls,stamp)
        self.assertEqual(exit['reason'],'LOSS_LIMIT');self.assertEqual(exit['quantity'],3)
        with self.assertRaises(ExecutionBlocked):self.enter()

    def test_time_exit_uses_first_real_fill_and_not_intended_entry_timestamp(self):
        key=self.enter();self.fill(key,offset=20)
        stamp=NOW+timedelta(minutes=30,seconds=19)
        self.assertEqual(self.engine.manage_exit(synthetic_contract(stamp),self.controls,stamp)['status'],'HOLD')
        stamp+=timedelta(seconds=1)
        self.assertEqual(self.engine.manage_exit(synthetic_contract(stamp),self.controls,stamp)['reason'],'TIME_LIMIT')

    def test_one_pending_exit_only_and_unfilled_remainder_survives(self):
        key=self.enter();self.fill(key)
        stamp=NOW+timedelta(seconds=2);q=synthetic_contract(stamp,bid=2.45,ask=2.5)
        first=self.engine.manage_exit(q,self.controls,stamp)
        second=self.engine.manage_exit(q,self.controls,stamp)
        self.assertEqual(second['status'],'EXIT_ALREADY_PENDING')
        self.assertEqual(second['client_key'],first['client_key'])
        self.fill(first['client_key'],quantity=1,bid=2.45,ask=2.5,offset=3,identity='sale')
        self.assertEqual(self.ledger.portfolio()[q.snapshot.symbol]['quantity'],2)

    def test_fills_do_not_reuse_same_quote_liquidity_and_are_idempotent(self):
        key=self.enter();q=synthetic_contract(NOW+timedelta(seconds=1),ask_size=1)
        identity=self.ledger.order(key)['broker_id']
        self.assertEqual(self.broker.match_quote(identity,q,now=q.snapshot.quote_timestamp,execution_id='one'),1)
        self.assertEqual(self.broker.match_quote(identity,q,now=q.snapshot.quote_timestamp,execution_id='two'),0)
        self.assertEqual(self.broker.match_quote(identity,q,now=q.snapshot.quote_timestamp,execution_id='one'),0)
        alias=replace(q,snapshot=replace(q.snapshot,quote_timestamp=q.snapshot.quote_timestamp.astimezone(ZoneInfo('America/New_York'))))
        self.assertEqual(self.broker.match_quote(identity,alias,now=q.snapshot.quote_timestamp,execution_id='alias'),0)
        self.engine.reconcile(NOW+timedelta(seconds=1));self.assertEqual(self.ledger.order(key)['filled_quantity'],1)

    def test_no_fill_before_submission_or_outside_day_order_session(self):
        key=self.enter();identity=self.ledger.order(key)['broker_id']
        for stamp in (NOW-timedelta(microseconds=1),NOW.replace(hour=20)):
            with self.subTest(stamp=stamp),self.assertRaises(ExecutionBlocked):
                self.broker.match_quote(identity,synthetic_contract(stamp),now=max(NOW,stamp),execution_id='invalid')

    def test_foreign_database_rejected_without_changes_and_components_not_interchangeable(self):
        foreign=self.root/'foreign.db'
        with closing(sqlite3.connect(foreign)) as db,db:db.execute('CREATE TABLE historical_notifications(id INTEGER)')
        before=hashlib.sha256(foreign.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):SimulationLedger(foreign)
        self.assertEqual(hashlib.sha256(foreign.read_bytes()).hexdigest(),before)
        with self.assertRaises(ValueError):LocalPaperBroker(self.ledger.path)
        with self.assertRaises(TypeError):SimulationEngine(self.ledger,object(),self.policy)

    def test_missing_broker_fill_does_not_erase_position_and_blocks_next_entries(self):
        key=self.enter();self.fill(key)
        with self.broker.transaction() as db:db.execute('DELETE FROM paper_fills')
        result=self.engine.reconcile(NOW+timedelta(seconds=2))
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('BROKER_STATE_REGRESSION',result['issues'])
        self.assertEqual(self.ledger.portfolio()[synthetic_contract().snapshot.symbol]['quantity'],3)

    def test_unbounded_risk_and_noninteger_liquidity_do_not_create_orders(self):
        engine=SimulationEngine(self.ledger,self.broker,synthetic_policy(risk=RiskLimits(float('inf'),30.,10.,1,1000.)))
        with self.assertRaises(ValueError):self.enter(engine=engine)
        for size in (float('nan'),float('inf'),True,1.5):
            with self.subTest(size=size),self.assertRaises(ValueError):
                self.enter(contract=synthetic_contract(ask_size=size))
        self.assertEqual(self.ledger.orders(),[])


if __name__=='__main__':unittest.main()
