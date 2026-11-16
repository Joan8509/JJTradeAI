"""Offline study of a 10% option target; never connects to a broker or changes gates."""
from collections import Counter,defaultdict
from contextlib import closing
from datetime import datetime,timedelta,timezone
from decimal import Decimal,ROUND_CEILING
from hashlib import sha256
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo
import argparse,json,re,sqlite3,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
NY=ZoneInfo('America/New_York')

def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
def dec(value):return Decimal(str(value))
def quote_hurdle(ask,bid,*,target='10',quantity=1,buy_fee='0',sell_fee='0',increment='.01'):
    """Arithmetic scenario, not a quote or a promised execution."""
    a,b,t,inc=map(dec,(ask,bid,target,increment));n=dec(quantity)*100
    if not a>=b>0 or inc<=0 or t<0 or n<=0:raise ValueError('INVALID_SCENARIO')
    premium=a*n;investment=premium+dec(buy_fee)
    gross=a*(1+t/100)
    gross_limit=(gross/inc).to_integral_value(rounding=ROUND_CEILING)*inc
    net=((investment*(1+t/100)+dec(sell_fee))/n/inc).to_integral_value(rounding=ROUND_CEILING)*inc
    return dict(ask=str(a),bid=str(b),spread=str(a-b),spread_pct=float(100*(a-b)/a),
        gross_target_price=str(gross),gross_target_limit=str(gross_limit),bid_rise_to_gross_target_pct=float(100*(gross_limit/b-1)),
        net_target_price=str(net),gross_target_dollars=str(premium*t/100),
        net_return_at_gross_target_pct=float(100*(gross_limit*n-dec(sell_fee)-investment)/investment))

def weighted(fills):
    quantity=sum(f['quantity'] for f in fills)
    return quantity,sum(dec(f['price'])*f['quantity'] for f in fills)/quantity if quantity else None

def execution_rows(rows):
    result=[]
    for buy in rows:
        if buy['instruction']!='BUY_TO_OPEN' or not buy.get('fills'):continue
        fills=list(buy['fills'].values());quantity,price=weighted(fills)
        children=[r for r in rows if r.get('parent_id')==buy['id']]
        sales=[f for r in children for f in (r.get('fills') or {}).values()]
        sold,sell=weighted(sales)
        closed=sold==quantity
        if sold>quantity:raise ValueError('OVER_CLOSED_EVIDENCE')
        start=min(stamp(f['time']) for f in fills)
        native=any(r.get('exit_role')=='BROKER_TARGET' and r.get('fills') for r in children)
        result.append(dict(symbol=re.match(r'[A-Z0-9.]+',buy['contract']).group(),contract=buy['contract'],
            day=start.astimezone(NY).date().isoformat(),entry_at=start.isoformat(),entry_price=str(price),quantity=quantity,
            fully_closed=closed,exit_average=str(sell) if sell is not None else None,
            gross_return_pct=float(100*(sell/price-1)) if closed else None,
            buy_to_full_exit_seconds=(max(stamp(f['time']) for f in sales)-start).total_seconds() if closed else None,
            target=(buy.get('exit_plan') or {}).get('target'),native_target_fill=native,
            target_order_delay_seconds=min(((stamp(r['created_at'])-start).total_seconds() for r in children
                if r.get('exit_role')=='BROKER_TARGET'),default=None),
            fees_verified=False,net_return_pct=None,first_target_touch_seconds=None,
            target_before_stop=None,mae_before_target=None))
    return result

def execution_summary(rows):
    closed=[r for r in rows if r['fully_closed']]
    reached=[r for r in closed if r['gross_return_pct']>=10-1e-10]
    return dict(trades=len(rows),closed=len(closed),gross_at_least_10=len(reached),
        closed_negative=sum(r['gross_return_pct']<0 for r in closed),
        observed_execution_with_10_by_seconds={str(h):sum(r['buy_to_full_exit_seconds']<=h for r in reached)
            for h in (10,30,60,300,900)},
        median_winning_hold_seconds=median(r['buy_to_full_exit_seconds'] for r in reached) if reached else None,
        target_before_stop_covered=0,net_profit_covered=0,
        limitation='Execution endpoints do not reveal first target touch, earlier stop touch or full path.')

def read_only(path,seconds=5):
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)
    db.execute('PRAGMA query_only=ON');deadline=time.monotonic()+seconds
    db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    return db

def simulation_snapshot(path):
    with closing(read_only(path)) as db:
        orders=db.execute('SELECT client_key,payload,status,created_at FROM simulated_orders').fetchall()
        fills=db.execute('SELECT client_key,quantity,price,time FROM simulated_fills').fetchall()
    decoded={key:dict(json.loads(raw),_key=key,status=status,created_at=at) for key,raw,status,at in orders}
    by_key=defaultdict(list)
    for key,q,price,at in fills:by_key[key].append(dict(quantity=q,price=price,time=at))
    rows=[];ambiguous=0
    for key,buy in decoded.items():
        if buy['instruction']!='BUY_TO_OPEN' or not by_key[key]:continue
        identity=(buy.get('signal_key'),buy['contract'])
        matches=[v for v in decoded.values() if v['instruction']=='BUY_TO_OPEN'
            and (v.get('signal_key'),v['contract'])==identity]
        if len(matches)!=1:ambiguous+=1;continue
        children=[v for v in decoded.values() if v['instruction']=='SELL_TO_CLOSE'
            and (v.get('signal_key'),v['contract'])==identity]
        b=dict(id=key,instruction='BUY_TO_OPEN',contract=buy['contract'],fills={str(i):v for i,v in enumerate(by_key[key])},
            exit_plan=dict(target=buy.get('plan',{}).get('target_pct')))
        cs=[dict(id=v['_key'],parent_id=key,instruction='SELL_TO_CLOSE',created_at=v['created_at'],
            fills={str(i):f for i,f in enumerate(by_key[v['_key']])}) for v in children]
        row=execution_rows([b,*cs])[0];row['historical_policy']=buy.get('plan',{});rows.append(row)
    return dict(source='SYNTHETIC_FILLS_NOT_REAL_OR_CURRENT_V7',rows=rows,ambiguous_entries_excluded=ambiguous,
        target10=execution_summary([r for r in rows if r['target']=='10']),all_policies=execution_summary(rows),
        limitation='A 20% target loss might previously have reached 10%; without quote path this is unknown.')

def signal_study(frozen,out):
    from bollinger_phone_worker import STRATEGY_VERSION
    with closing(read_only(ROOT/'exports/market_data.db')) as db:
        raw=db.execute('SELECT event_key,detected_at,payload_json FROM bollinger_live_events WHERE detected_at>=? ORDER BY detected_at',('2026-11-06',)).fetchall()
    events=[]
    for key,at,payload in raw:
        e=json.loads(payload)
        if (e.get('version')==STRATEGY_VERSION and e.get('source_kind')=='TRADE' and e.get('feed')=='iex'
            and e.get('reference_scope')=='REGULAR' and e.get('band_expansion')
            and stamp(at)<=frozen and stamp(e['source_timestamp'])<=frozen-timedelta(seconds=65)):
            events.append(e|dict(event_key=key,detected_at=at))
    archive=ROOT/'exports/trade_review/2026-11-06_impulse_study/impulse_evidence.sqlite3'
    rows=[];evidence=[];errors=[]
    with closing(read_only(archive,seconds=100)) as db:
        db.execute('BEGIN');gaps=db.execute('SELECT count(*) FROM gaps').fetchone()[0]
        for e in events:
            t0=stamp(e['source_timestamp']);end=t0+timedelta(seconds=62)
            try:
                data=db.execute('SELECT received,source_time,message FROM ticks WHERE symbol=? AND source_time>=? AND source_time<? ORDER BY source_time',
                    (e['symbol'],t0.strftime('%Y-%m-%dT%H:%M:%S'),end.strftime('%Y-%m-%dT%H:%M:%S'))).fetchall()
            except sqlite3.Error:
                errors.append(e['event_key']);continue
            ticks=[]
            for received,at,message in data:
                m=json.loads(message)
                if (m.get('T')=='t' and isinstance(m.get('_jjtrade',{}).get('geometry'),dict)
                        and stamp(at)>=t0 and stamp(received)<=frozen):
                    ticks.append(dict(at=at,received=received,price=m['p']))
            direction=1 if e['side']=='SUPERIOR' else -1
            row=dict(symbol=e['symbol'],day=t0.astimezone(NY).date().isoformat(),at=t0.isoformat(),side=e['side'],
                window='OPENING_15M' if (t0.astimezone(NY).hour,t0.astimezone(NY).minute)<(9,45) else 'LATER',outcomes={})
            for h in (10,30,60):
                target=t0+timedelta(seconds=h)
                q=min(ticks,key=lambda x:abs((stamp(x['at'])-target).total_seconds()),default=None)
                row['outcomes'][str(h)]=100*direction*(q['price']/e['price']-1) if q and abs((stamp(q['at'])-target).total_seconds())<=1 else None
            rows.append(row);evidence.append(dict(event=e,ticks=ticks))
        db.rollback()
    (out/'signal_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False),encoding='utf-8')
    def summary(rs):
        return {str(h):dict(signals=len(rs),covered=sum(r['outcomes'][str(h)] is not None for r in rs),
            favorable=sum(r['outcomes'][str(h)] is not None and r['outcomes'][str(h)]>0 for r in rs),
            median_directional_return_pct=median(r['outcomes'][str(h)] for r in rs if r['outcomes'][str(h)] is not None)
                if any(r['outcomes'][str(h)] is not None for r in rs) else None) for h in (10,30,60)}
    return dict(strategy=STRATEGY_VERSION,events=len(events),rows=rows,days=dict(Counter(r['day'] for r in rows)),
        archive_retention_gaps=gaps,read_errors=errors,all=summary(rows),
        windows={w:summary([r for r in rows if r['window']==w]) for w in ('OPENING_15M','LATER')},
        option_target_coverage=0,limitation='Underlying return is not option 10% success. Missing observations stay unknown.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',default='exports/trade_review/2026-11-16_target10')
    parser.add_argument('--reuse-evidence',action='store_true',help='Recompute reports from already frozen evidence only')
    args=parser.parse_args()
    out=ROOT/args.folder;out.mkdir(parents=True,exist_ok=True)
    existing=json.loads((out/'report.json').read_text(encoding='utf-8')) if args.reuse_evidence else None
    frozen=stamp(existing['plan']['frozen_at']) if existing else datetime.now(timezone.utc)
    plan=dict(frozen_at=frozen.isoformat(),research_only=True,target='10',stop='20',
        question='How often and how fast can the existing valid strategy yield 10% on an executable option?',
        no_new_filters=True,option_first_touch='UNKNOWN without continuous same-contract Bid/Ask',
        actual_scope='All local real filled buys; recent cohort starts Nov9 by date, not selected by winning outcome',
        endpoint_horizons_seconds=[10,30,60],today_partial=True)
    (out/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    real=json.loads((out/'real_frozen.json').read_text(encoding='utf-8'))
    actual=execution_rows(real['rows'])
    sim=existing['simulation'] if existing else simulation_snapshot(ROOT/'exports/trade_review/manual_simulation/observed_manual_v1/ledger.db')
    signals=existing['signals'] if existing else signal_study(frozen,out)
    scenarios=[quote_hurdle(a,b,buy_fee='.65',sell_fee='.65') for a,b in
        [('.30','.22'),('.63','.55'),('.63','.61'),('.70','.68')]]
    report=dict(plan=plan,real_trades=actual,real_all=execution_summary(actual),
        real_since_nov09=execution_summary([r for r in actual if r['day']>='2026-11-09']),
        simulation=sim,signals=signals,arithmetic_scenarios=scenarios,
        scenario_fees='Illustration only: $0.65 each side, excludes extra fees; not verified actual trade fees.',
        orders_sent=0,previews_sent=0,production_changes=0)
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'SHA256SUMS.txt').write_text(''.join(sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
        for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'),encoding='utf-8')
    print(json.dumps(dict(real_all=report['real_all'],real_since_nov09=report['real_since_nov09'],
        actual=actual,sim_target10=sim['target10'],signals=dict(events=signals['events'],days=signals['days'],
        all=signals['all'],windows=signals['windows'],gaps=signals['archive_retention_gaps']),scenarios=scenarios),indent=2))
if __name__=='__main__':main()
