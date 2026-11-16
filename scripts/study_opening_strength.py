"""Offline opening comparison on frozen minutes and independently archived ticks.

Never connects to providers, writes production DBs, or changes live rules.
Minute evidence cannot certify a 30-second first-breakout clock or option P&L.
"""
from collections import defaultdict, Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
from zoneinfo import ZoneInfo
import gzip
import hashlib
import importlib.util
import json
import math
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bollinger_phone_worker import detect_values
from bollinger_expansion import MINIMUM_BAND_EXPANSION_PCT
from bollinger_breakout_clock import observe_breakout
from scripts.build_impulse_study import evaluate, epoch

NY=ZoneInfo('America/New_York')
OLD=ROOT/'exports/trade_review/2026-11-01_opening_three_candles'
ARCHIVE=ROOT/'exports/trade_review/2026-11-06_impulse_study/impulse_evidence.sqlite3'


def group(stamp):
    local=datetime.fromtimestamp(stamp,NY)
    minute=local.hour*60+local.minute
    if not 570<=minute<960:return None
    return 'C1' if minute<585 else 'C2' if minute<600 else 'C3' if minute<615 else 'LATER'


def current_side(g):
    # previous_close is only checked for finiteness by the current predicate;
    # the recorded previous_mid supplies that redundant finite argument.
    return detect_values(g['previous_mid'],g['previous_upper'],g['previous_lower'],
        g['previous_mid'],g['price'],g['upper'],g['lower'],g['mid'],
        opening=g['opening'],opening_upper=g['initial_opening_upper'],
        opening_lower=g['initial_opening_lower'])


def aggregate_minutes(events):
    result={}
    for name in ('C1','C2','C3','C2_C3','LATER'):
        selected=[e for e in events if e['group']==name or name=='C2_C3' and e['group'] in ('C2','C3')]
        horizons={}
        for horizon in ('1','3','5'):
            valid=[e['future'][horizon] for e in selected if e['future'][horizon]['available']]
            horizons[horizon]=dict(n=len(valid),missing=len(selected)-len(valid),
                positive_pct=100*fmean(r['return_pct']>0 for r in valid) if valid else None,
                mean_return_pct=fmean(r['return_pct'] for r in valid) if valid else None,
                mean_mfe_pct=fmean(r['mfe_pct'] for r in valid) if valid else None,
                mean_mae_pct=fmean(r['mae_pct'] for r in valid) if valid else None)
        result[name]=dict(signals=len(selected),days=len({e['day'] for e in selected}),horizons=horizons)
    return result


def minutes_replay():
    spec=importlib.util.spec_from_file_location('frozen_opening_helpers',OLD/'study.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    plan=json.loads((OLD/'analysis_plan.json').read_text())
    sessions=[(d,int(datetime.fromisoformat(a).timestamp()),int(datetime.fromisoformat(b).timestamp()))
        for d,a,b in json.loads((OLD/'calendar.json').read_text())]
    bounds={d:(a,b) for d,a,b in sessions}
    periods=[(d,t,min(t+900,b)) for d,a,b in sessions for t in range(a,b,900)]
    manifest=json.loads((OLD/'source_manifest.json').read_text());events=[];checks=0;coverage=Counter()
    for item in manifest:
        path=OLD/'source'/(item['symbol']+'.json.gz')
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item['source_sha256']
        with gzip.open(path,'rt',encoding='utf-8') as f:raw=json.load(f)
        minutes={};slots=defaultdict(list)
        for r in raw:
            stamp=datetime.fromisoformat(r[0]);t=int(stamp.timestamp());day=stamp.date().isoformat()
            if day not in bounds or not bounds[day][0]<=t<bounds[day][1]:continue
            if t%60 or not all(math.isfinite(float(v)) for v in r[1:]) or min(r[1:5])<=0:continue
            if r[2]<max(r[1],r[3],r[4]) or r[3]>min(r[1],r[4]):continue
            minutes[t]=r;slots[t//900*900].append((t,r))
        for rows in slots.values():rows.sort()
        for i,(day,start,end) in enumerate(periods):
            if day not in plan['days']:continue
            coverage['candidate_candles']+=1
            prior=periods[max(0,i-20):i];refs=[slots.get(a,[]) for _,a,b in prior]
            if len(refs)!=20 or any(not r or r[-1][0]!=p[2]-60 for r,p in zip(refs,prior)):
                coverage['incomplete_prior_history']+=1;continue
            if start not in minutes:coverage['missing_official_open']+=1;continue
            coverage['eligible_candles']+=1
            prices=[r[-1][1][4] for r in refs];opening=minutes[start][1]
            pm=fmean(prices);variance=fmean((p-pm)**2 for p in prices)
            half=2*math.sqrt(variance);pu,pl=pm+half,pm-half
            base=fmean(prices[1:]);s=sum((p-base)**2 for p in prices[1:])
            def bands(price):
                mid=base+(price-base)/20
                distance=2*math.sqrt(max(0,(s+(price-base)*(price-mid))/20))
                return mid+distance,mid-distance,mid
            ou,ol,_=bands(opening);found=set()
            for t,r in slots.get(start,[]):
                price=r[1];u,l,mid=bands(price)
                side=detect_values(prices[-1],pu,pl,pm,price,u,l,mid,
                    opening=opening,opening_upper=ou,opening_lower=ol)
                checks+=1
                if side is None or side in found:continue
                found.add(side)
                events.append(dict(symbol=item['symbol'],day=day,at=t,candle=start,
                    group=group(t),side=side,price=price,
                    future={str(h):helper.outcome(minutes,t,1 if side=='SUPERIOR' else -1,
                        pu-pl,h,bounds[day][1]) for h in (1,3,5)}))
    latest=set(plan['days'][-20:])
    # Paired day bootstrap from existing helper, balancing symbols within day.
    paired={}
    for label,selected in [('ALL62',events),('LAST20',[e for e in events if e['day'] in latest])]:
        a=helper.summarize([e for e in selected if e['group']=='C1'])
        b=helper.summarize([e for e in selected if e['group'] in ('C2','C3')])
        paired[label]={key:helper.difference(a,b,key) for key in ('positive','mfe','mae')}
    return dict(mode='MINUTE_PROXY_3PCT_INITIAL_OPEN_INSIDE_NOT_V7_TIMING',
        symbols=len(manifest),sessions=len(plan['days']),start=plan['days'][0],end=plan['days'][-1],
        samples=checks,coverage=dict(coverage),all62=aggregate_minutes(events),
        last20=aggregate_minutes([e for e in events if e['day'] in latest]),paired_bootstrap=paired),events


def ticks_replay():
    ticks=defaultdict(list);events=[];seen=set();clocks={};coverage=Counter();counts=Counter();days=set()
    with closing(sqlite3.connect(ARCHIVE.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        gaps=db.execute('select count(*) from gaps').fetchone()[0]
        for received,symbol,source,raw in db.execute('select received,symbol,source_time,message from ticks order by id'):
            stamp=datetime.fromisoformat(source.replace('Z','+00:00'));t=stamp.timestamp()
            if stamp.astimezone(NY).date().isoformat()!='2026-11-06':continue
            gname=group(t)
            if gname is None:continue
            msg=json.loads(raw);extra=msg.get('_jjtrade',{});g=extra.get('geometry')
            if not isinstance(g,dict):continue
            coverage[gname]+=1;days.add(stamp.astimezone(NY).date().isoformat())
            ticks[symbol].append(dict(time=t,received=epoch(received),price=g['price']))
            candle=int(t//900)*900;key=(symbol,candle)
            if key not in clocks:clocks[key]=dict(verified=t-candle<=3,firsts={})
            clock=clocks[key]
            evidence=observe_breakout(clock['firsts'],g['price'],g['upper'],g['lower'],stamp,
                allow_new=clock['verified'])
            try:side=current_side(g)
            except (KeyError,ValueError,TypeError):counts['missing_geometry']+=1;continue
            if not side:continue
            if evidence is None or not evidence['current']:
                counts['clock_expired_or_unavailable']+=1;continue
            decision=extra.get('processing_started_at',received)
            if not 0<=epoch(decision)-t<=3:counts['stale_at_processing']+=1;continue
            identity=(symbol,candle,side)
            if identity in seen:continue
            seen.add(identity);width=g['previous_upper']-g['previous_lower']
            events.append(dict(symbol=symbol,version='OFFLINE_V7_RECONSTRUCTED',
                feed='iex',reference_scope='REGULAR',source_timestamp=stamp.isoformat(),
                detected_at=decision,side=side,price=g['price'],window=gname,
                first_breakout_at=evidence['first_at'],age_seconds=evidence['age_seconds'],
                band_expansion=dict(previous_upper=g['previous_upper'],previous_lower=g['previous_lower'],
                    upper=g['upper'],lower=g['lower'],required_pct=3,
                    upper_pct=100*(g['upper']-g['previous_upper'])/width,
                    lower_pct=100*(g['previous_lower']-g['lower'])/width)))
        db.rollback()
    for rows in ticks.values():rows.sort(key=lambda t:t['time'])
    detail=[]
    for e in events:
        data=evaluate(e,ticks[e['symbol']]);data['window']=e['window'];data['age_seconds']=e['age_seconds']
        detail.append(data)
    summary={}
    for name in ('C1','C2','C3','LATER'):
        rows=[r for r in detail if r['window']==name];horizons={}
        for h in ('1','3','5','10','30','60'):
            values=[r['future_underlying_labels'][h]['directional_return_pct'] for r in rows
                if r['future_underlying_labels'][h]['endpoint_covered']]
            horizons[h]=dict(n=len(values),missing=len(rows)-len(values),
                positive_pct=100*fmean(v>0 for v in values) if values else None,
                mean_return_pct=fmean(values) if values else None,
                median_return_pct=median(values) if values else None)
        summary[name]=dict(signals=len(rows),horizons=horizons,
            continuous_30s=sum(r['path_30s']['continuous_one_second_coverage'] for r in rows))
    return dict(mode='CAUSAL_REPLAY_OF_RECORDED_GEOMETRY_NOT_LIVE_ORDERS',days=sorted(days),
        archive_gaps=gaps,tick_counts=dict(coverage),exclusions=dict(counts),summary=summary),detail


def main():
    assert MINIMUM_BAND_EXPANSION_PCT==3
    folder=ROOT/'exports/trade_review/2026-11-09_opening_strength'
    folder.mkdir(parents=True,exist_ok=True)
    minutes,minute_detail=minutes_replay()
    ticks,tick_detail=ticks_replay()
    report=dict(created_at=datetime.now(timezone.utc).isoformat(),research_only=True,
        minute_study=minutes,tick_study=ticks,
        limitations=['No historical option BBO/fills: underlying percentages are not contract returns.',
            'Frozen minutes cannot resolve intraminute first exit, 30s expiry or seconds of retracement.',
            'Tick reconstruction has one full session, no independent validation and IEX geometry.',
            'Known first clock means first archived print within 3s of candle; does not establish all-market first trade.',
            'Tick endpoints require sample within 1s; missing is not a loss.',
            'No live gates, stop, targets, queues, processes or orders changed.'])
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (folder/'minute_events.json').write_text(json.dumps(minute_detail),encoding='utf-8')
    (folder/'tick_events.json').write_text(json.dumps(tick_detail,indent=2),encoding='utf-8')
    paths=[Path(__file__),OLD/'source_manifest.json',OLD/'calendar.json',folder/'report.json',
        folder/'minute_events.json',folder/'tick_events.json']
    (folder/'checksums.json').write_text(json.dumps({str(p.relative_to(ROOT)):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
