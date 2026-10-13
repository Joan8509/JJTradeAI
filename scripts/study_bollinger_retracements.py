"""Fixed, chronological research of underlying retracements and executable exit hypotheses.

No live filters, orders, option returns, or dashboard changes.
"""
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from bollinger_phone_worker import STRATEGY_VERSION,bands_at_open
from bollinger_strategy_study import replay_events
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE,MarketBarStore
from watchlist_config import load_watchlist

PLANS=('TIME_1','TIME_2','TIME_3','TIME_5','TIME_10','TIME_15',
       'TP010_STOP010_MAX5','TP020_STOP010_MAX5','TP020_STOP010_MAX10',
       'TRAIL010_MAX10','REENTRY_MAX15')


def exit_plan(closes,opens,inside,sign,reference,plan):
    """A rule observed at minute close exits at the following minute open."""
    best=0.
    limit=int(plan.split('_')[-1]) if plan.startswith('TIME_') else int(plan.split('MAX')[-1])
    reason='TIME'
    for i in range(limit):
        change=sign*(closes[i]/reference-1)*100
        best=max(best,change)
        trigger=False
        if plan.startswith('TP'):
            target=.1 if plan.startswith('TP010') else .2
            if change>=target:trigger=True;reason='TARGET_CLOSE'
            elif change<=-.1:trigger=True;reason='STOP_CLOSE'
        elif plan.startswith('TRAIL') and best-change>=.1:
            trigger=True;reason='TRAIL_CLOSE'
        elif plan.startswith('REENTRY') and inside[i]:
            trigger=True;reason='REENTRY_CLOSE'
        if trigger or i==limit-1:
            return {'return_pct':sign*(opens[i+1]/reference-1)*100,
                    'held_minutes':i+1,'reason':reason}


def path_metrics(closes,inside,sign,reference):
    best=before_inside=0.
    previous=reference
    first_pullback=None
    pullback_advance=None
    first_inside=None
    worst=0.
    for i,close in enumerate(closes):
        change=sign*(close/reference-1)*100
        if first_pullback is None and sign*(close-previous)<0:
            first_pullback=i+1;pullback_advance=best
        if first_inside is None:
            if inside[i]:first_inside=i+1
            else:before_inside=max(before_inside,change)
        best=max(best,change);worst=min(worst,change);previous=close
    return {'first_pullback_minutes':first_pullback,'advance_before_pullback_pct':pullback_advance if first_pullback else best,
            'pullback_censored':first_pullback is None,'first_reentry_minutes':first_inside,
            'advance_before_reentry_pct':before_inside,'max_close_advance_pct':best,'max_close_adverse_pct':-worst}


def feature_profile(event,indexed,records,positions):
    stamp=pd.Timestamp(event['source_timestamp']);position=positions[stamp.floor('15min')]
    prior=[r['close'] for r in records[position-19:position]]
    upper,lower=bands_at_open(prior,event['price'])
    previous=records[position-1];width=upper-lower
    exposure=(event['price']-upper if event['side']=='SUPERIOR' else lower-event['price'])/width*100
    partial=indexed.loc[stamp.floor('15min'):stamp]
    opening=float(partial.iloc[0].open)
    span=float(partial.high.max()-partial.low.min())
    body=abs(event['price']-opening)/span if span else 0.
    return {'exposure_pct_bandwidth':exposure,'expansion_pct':(width/(previous['bollinger_upper']-previous['bollinger_lower'])-1)*100,
            'body_fraction':body,'candle_minute':stamp.minute%15,
            'exposure_group':'SMALL_LT1' if exposure<1 else 'MID_1_TO3' if exposure<3 else 'LARGE_GE3',
            'body_group':'BODY_LT_HALF' if body<.5 else 'BODY_GE_HALF',
            'age_group':'EARLY_0_TO4' if stamp.minute%15<5 else 'MID_5_TO9' if stamp.minute%15<10 else 'LATE_10_TO14'}


def evaluate(event,indexed,records,positions,session_close,as_of,delay):
    start=pd.Timestamp(event['source_timestamp'])+pd.Timedelta(minutes=1+delay)
    expected=pd.date_range(start,periods=16,freq='min')
    if expected[-1]+pd.Timedelta(minutes=1)>session_close:return None,'SESSION_END'
    if expected[-1]+pd.Timedelta(minutes=1)>as_of:return None,'PENDING'
    if not expected.isin(indexed.index).all():return None,'MISSING_MINUTES'
    window=indexed.loc[expected]
    if not all(math.isfinite(float(v)) and float(v)>0 for v in window[['open','high','low','close']].to_numpy().flat):return None,'INVALID'
    if not ((window.low<=window[['open','close']].min(axis=1)) & (window.high>=window[['open','close']].max(axis=1))).all():return None,'INVALID'
    closes=window.close.iloc[:15].tolist();opens=window.open.tolist()
    reference=opens[0];sign=1 if event['side']=='SUPERIOR' else -1
    inside=[]
    for stamp,close in zip(expected[:15],closes):
        position=positions.get(stamp.floor('15min'),0)
        if position<19:return None,'WARMUP'
        upper,lower=bands_at_open([r['close'] for r in records[position-19:position]],close)
        inside.append(close<=upper if sign==1 else close>=lower)
    return {'entry_time':start.isoformat(),'entry_reference':reference,'delay_minutes':delay,
            **path_metrics(closes,inside,sign,reference),
            'plans':{p:exit_plan(closes,opens,inside,sign,reference,p) for p in PLANS}},None


def stats(rows):
    n=len(rows)
    if not n:return {'n':0}
    values=pd.Series([r['advance_before_pullback_pct'] for r in rows])
    pullbacks=[r['first_pullback_minutes'] for r in rows if r['first_pullback_minutes'] is not None]
    return {'n':n,'sessions':len({pd.Timestamp(r['source_timestamp']).date() for r in rows}),
            'no_close_advance_before_pullback_pct':100*sum(v==0 for v in values)/n,
            'advance_before_pullback_p25':float(values.quantile(.25)),'advance_before_pullback_median':float(values.median()),
            'advance_before_pullback_p75':float(values.quantile(.75)),
            'pullback_within_2min_pct':100*sum(r['first_pullback_minutes'] is not None and r['first_pullback_minutes']<=2 for r in rows)/n,
            'reentry_within_2min_pct':100*sum(r['first_reentry_minutes'] is not None and r['first_reentry_minutes']<=2 for r in rows)/n,
            'pullback_median_minutes':float(pd.Series(pullbacks).median()) if pullbacks else None,
            'no_pullback_observed_15m':sum(r['pullback_censored'] for r in rows),
            'reach_before_pullback_pct':{str(t):100*sum(v>=t for v in values)/n for t in (.05,.1,.2,.3)},
            'plans':{p:{'mean_return_pct':sum(r['plans'][p]['return_pct'] for r in rows)/n,
                        'positive_pct':100*sum(r['plans'][p]['return_pct']>0 for r in rows)/n,
                        'median_return_pct':float(pd.Series([r['plans'][p]['return_pct'] for r in rows]).median()),
                        'mean_hold_minutes':sum(r['plans'][p]['held_minutes'] for r in rows)/n} for p in PLANS}}


def main():
    now=pd.Timestamp(datetime.now(timezone.utc));cut=now-pd.Timedelta(days=180)
    validation=now-pd.Timedelta(days=60);recent=now-pd.Timedelta(days=30)
    allowed=load_watchlist()['symbols']
    with sqlite3.connect(DEFAULT_MARKET_DATABASE) as db:
        sources=db.execute('SELECT DISTINCT symbol,provider,feed FROM minute_bars WHERE timestamp>=?',(cut.isoformat(),)).fetchall()
        sessions={date:pd.Timestamp(close) for date,close in db.execute('SELECT session_date,closes_at FROM market_sessions')}
    observations=[];coverage=[]
    for symbol,provider,feed in sources:
        if symbol not in allowed:continue
        print('Procesando',symbol,flush=True)
        bars=MarketBarStore().load_frame(symbol=symbol,provider=provider,feed=feed,start=cut-pd.Timedelta(days=7),end=now-pd.Timedelta(minutes=1))
        records=prepare_market_frame(aggregate_minute_bars(bars,'15m')).to_dict('records')
        positions={pd.Timestamp(r['date']):i for i,r in enumerate(records)};indexed=bars.set_index('date')
        events=[e for e in replay_events(bars,symbol=symbol,provider=provider,feed=feed) if pd.Timestamp(e['detected_at'])>=cut]
        excluded=Counter();last_end=None;count=0
        for event in events:
            stamp=pd.Timestamp(event['source_timestamp']);available=stamp+pd.Timedelta(minutes=1)
            session_close=sessions.get(stamp.tz_convert('America/New_York').date().isoformat())
            if session_close is None:excluded['NO_SESSION']+=1;continue
            period='TRAIN' if available<validation else 'VALIDATION' if available<recent else 'RECENT'
            boundary=validation if period=='TRAIN' else recent if period=='VALIDATION' else now
            if available+pd.Timedelta(minutes=17)>=boundary:excluded['PERIOD_BOUNDARY']+=1;continue
            if last_end is not None and available<=last_end:excluded['OVERLAP']+=1;continue
            outcomes=[]
            for delay in (0,1):
                result,error=evaluate(event,indexed,records,positions,session_close,now,delay)
                if error:break
                outcomes.append(result)
            if error:excluded[error]+=1;continue
            last_end=available+pd.Timedelta(minutes=16)
            feature=feature_profile(event,indexed,records,positions)
            observations.extend({**event,**feature,**result,'period':period} for result in outcomes)
            count+=1
        coverage.append({'symbol':symbol,'detected':len(events),'matched_independent_cases':count,'excluded':dict(excluded)})
        print(symbol,'casos',count,flush=True)
    summary=[{'period':period,'delay':delay,**stats([r for r in observations if r['delay_minutes']==delay and (period=='TOTAL' or r['period']==period)])}
             for period in ('TRAIN','VALIDATION','RECENT','TOTAL') for delay in (0,1)]
    groups=[]
    for feature in ('exposure_group','body_group','age_group'):
        for value in sorted({r[feature] for r in observations}):
            for period in ('TRAIN','VALIDATION','RECENT'):
                groups.append({'feature':feature,'group':value,'period':period,
                    **stats([r for r in observations if r[feature]==value and r['period']==period and r['delay_minutes']==0])})
    by_symbol=[{'symbol':s,'side':side,'period':period,**stats([r for r in observations if r['symbol']==s and (side=='BOTH' or r['side']==side) and (period=='TOTAL' or r['period']==period) and r['delay_minutes']==0])}
               for s in allowed for side in ('BOTH','SUPERIOR','INFERIOR') for period in ('TOTAL','TRAIN','VALIDATION','RECENT')]
    payload={'as_of':now.isoformat(),'days':180,'version':STRATEGY_VERSION,'plans_fixed_before_run':list(PLANS),
             'entry_and_exit':'Underlying theoretical minute open after observable rule; close-only targets/stops; paired zero/one-minute delay; not options fills. Complete 16/17-minute paths and matched nonoverlapping cohorts. No costs.',
             'limitations':'First pullback is a directional decrease between minute closes, not every intraminute wick. Maxima are retrospective. IEX omissions bias complete-case sample. Recent history already explored, not independent future validation. SMA/levels previously studied, not newly matched here. No live modifications.',
             'coverage':coverage,'summary':summary,'groups':groups,'by_symbol':by_symbol,'observations':observations}
    output=Path('exports/bollinger_playback')/now.strftime('retracements_%Y%m%d_%H%M%S');output.mkdir(parents=True,exist_ok=True)
    import gzip
    with gzip.open(output/'report.json.gz','wt',encoding='utf-8') as handle:json.dump(payload,handle,ensure_ascii=False)
    (output/'summary.json').write_text(json.dumps({k:v for k,v in payload.items() if k!='observations'},indent=2),encoding='utf-8')
    print('OUTPUT',output,flush=True)


if __name__=='__main__':main()
