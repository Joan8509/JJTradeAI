"""End-to-end SYNTHETIC Schwab rehearsal using the unchanged actual detector.

No network, Telegram, account access, operational activation or real orders.
Creates three databases only inside a brand-new directory.
"""
from dataclasses import replace
from datetime import datetime,date,timedelta,timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from bollinger_tick_stream import TickGeometry
from market_calendar import MarketSession, MarketSessionRepository
from market_store import MarketBarStore
from option_market_data import OptionSnapshot
from option_position_sizing import ManualQuantityConfirmation, manual_entry_cost
from risk_engine import RiskLimits
from schwab_contracts import SchwabContract
from schwab_simulation import (AutomationPolicy,DataControls,SimulationLedger,LocalPaperBroker,
    SimulationEngine,ExecutionBlocked,limit_payload_for_review,validated_signal)

START=datetime(2026,10,16,14,tzinfo=timezone.utc)


def run_synthetic_rehearsal(directory):
    root=Path(directory)
    root.mkdir(parents=True,exist_ok=False)
    market=root/'synthetic_market.db'
    sessions=[MarketSession(date(2026,10,day),START.replace(day=day,hour=13,minute=30),
                            START.replace(day=day,hour=20)) for day in (15,16)]
    MarketSessionRepository(market).upsert(sessions)
    rows=[]
    for session in sessions:
        point=session.opens_at
        while point<min(START,session.closes_at):
            price=99. if int((point-session.opens_at).total_seconds()//900)%2==0 else 101.
            rows.append(dict(date=point,open=price,high=price,low=price,close=price,volume=100))
            point+=timedelta(minutes=1)
    MarketBarStore(market).upsert_frame(pd.DataFrame(rows),symbol='AMZN',provider='ALPACA',feed='iex')
    now=[START+timedelta(seconds=1)]
    geometry=TickGeometry(market,'iex',now=lambda:now[0]);geometry.status('CONECTADO',START-timedelta(seconds=1))
    def trade(price,identity):
        return dict(T='t',S='AMZN',p=price,s=100,c=['@'],z='C',x='V',i=identity,t=now[0].isoformat())
    geometry.observe(trade(100.,1),now[0]);now[0]+=timedelta(seconds=1)
    snapshot,reason=geometry.observe(trade(104.,2),now[0])
    if reason!='EXIT':raise AssertionError('Synthetic production-detector exit expected')
    policy=AutomationPolicy(account_alias='SYNTHETIC_ONLY',entry_sizing_mode='MANUAL_CONFIRMATION',min_dte=1,max_dte=14,
        min_bid_size=1,min_ask_size=1,max_open_positions=2,max_entries_per_day=4,
        max_daily_entry_cost=Decimal('4000'),max_daily_loss=Decimal('4000'),stop_loss_pct=Decimal('10'),
        max_holding_minutes=30,fee_per_contract=Decimal('.65'),entry_limit_rule='AT_ASK_LIMIT',
        risk=RiskLimits(.5,30.,10.,1,1000.))
    ledger=SimulationLedger(root/'synthetic_ledger.db');broker=LocalPaperBroker(root/'synthetic_broker.db')
    engine=SimulationEngine(ledger,broker,policy)
    controls=DataControls(True,True,True,sessions[-1].opens_at,sessions[-1].closes_at)
    runtime=dict(state='CONECTADO',feed='iex',heartbeat=now[0].isoformat())
    quote=OptionSnapshot('AMZN  261023C00100000','AMZN','CALL',100.,date(2026,10,23),
        1.95,2.,10,10,now[0],None,None,.6,None,None,None,'opra')
    contract=SchwabContract(quote,100,True,Decimal('.05'))
    confirmation=ManualQuantityConfirmation(policy.account_alias,'AMZN',quote.symbol,
        validated_signal(snapshot,runtime,controls,now[0])['key'],3,Decimal('2'),
        manual_entry_cost(2,3,policy.fee_per_contract),now[0])  #Synthetic user review.
    key=engine.enter(snapshot,runtime,controls,contract,now[0],now[0],lose_ack=True,
                     listed_expirations=(date(2026,10,23),),manual_confirmation=confirmation)
    lost_ack_persisted=ledger.order(key)['status']=='UNKNOWN'
    # Reconstruct both components from independent files after a synthetic restart.
    engine=SimulationEngine(SimulationLedger(ledger.path),LocalPaperBroker(broker.path),policy)
    broker,ledger=engine.broker,engine.ledger
    recovered=engine.reconcile(now[0])['status']=='RECONCILED'
    now[0]+=timedelta(seconds=1)
    quote=replace(quote,quote_timestamp=now[0]);contract=replace(contract,snapshot=quote)
    bought=broker.match_quote(ledger.order(key)['broker_id'],contract,now=now[0],
                             execution_id='SYNTHETIC_BUY_1',max_quantity=1)
    engine.reconcile(now[0])
    blocked=False
    try:engine.manage_exit(replace(contract,snapshot=replace(quote,bid=2.45,ask=2.5)),controls,now[0])
    except ExecutionBlocked:blocked=True
    broker.acknowledge_cancel(ledger.order(key)['broker_id']);engine.reconcile(now[0])
    ledger.set_paused(True)
    now[0]+=timedelta(seconds=1)
    sell_quote=replace(quote,bid=2.45,ask=2.5,quote_timestamp=now[0])
    exit=engine.manage_exit(replace(contract,snapshot=sell_quote),controls,now[0])
    sold=broker.match_quote(ledger.order(exit['client_key'])['broker_id'],replace(contract,snapshot=sell_quote),
        now=now[0],execution_id='SYNTHETIC_SELL_1')
    reconciliation=engine.reconcile(now[0])
    with ledger.transaction() as db:positions,realized=ledger._portfolio(db)
    checks={'unchanged_actual_detector_used':reason=='EXIT','lost_ack_persisted':lost_ack_persisted,
        'restart_reconciled_without_resubmit':recovered and len(broker.snapshot())==2,
        'partial_entry_requires_cancel_ack':blocked,'exit_only_filled_quantity':bought==sold==1,
        'gross_20_percent_target_from_actual_fill':Decimal(exit['limit'])==Decimal('2.40'),
        'pause_kept_position_management':exit['reason']=='TARGET','no_remaining_position':not positions,
        'final_reconciliation':reconciliation['status']=='RECONCILED'}
    report={'mode':'LOCAL_SYNTHETIC_REHEARSAL','synthetic':True,'real_orders_enabled':False,
        'schwab_connection_verified':False,'live_market_verified':False,'strategy_profitability_validated':False,
        'test_policy_is_user_approved':False,'messages_sent':0,'checks':checks,
        'status':'OK' if all(checks.values()) else 'BLOCKED','simulated_order_count':len(ledger.orders()),
        'simulated_bought_contracts':bought,'simulated_sold_contracts':sold,
        'synthetic_realized_net_pnl':str(sum(value for _,value in realized)),
        'entry_template_for_review':limit_payload_for_review(ledger.order(key)['order']),
        'exit_template_for_review':limit_payload_for_review(ledger.order(exit['client_key'])['order'])}
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',help='New isolated directory; existing paths are rejected')
    args=parser.parse_args()
    if args.directory:report=run_synthetic_rehearsal(args.directory)
    else:
        with TemporaryDirectory(prefix='jjtrade-schwab-synthetic-') as temp:
            report=run_synthetic_rehearsal(Path(temp)/'rehearsal')
    print(json.dumps({key:value for key,value in report.items() if not key.endswith('_template_for_review')},indent=2))
    return 0 if report['status']=='OK' else 1


if __name__=='__main__':raise SystemExit(main())
