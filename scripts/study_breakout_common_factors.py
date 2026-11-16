"""Offline multi-resolution playback; no market writes, broker, notices or gates."""
from collections import defaultdict,Counter
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from statistics import fmean,median
from zoneinfo import ZoneInfo
import gzip,hashlib,json,math,sqlite3,sys,time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from breakout_quality_research import CANDIDATES,geometry_features,comparison,day_difference,rank_on_training,summarize
from bollinger_phone_worker import bands_at_open,detect_values,STRATEGY_VERSION
from scripts.build_impulse_study import evaluate as labels,epoch
from movement_strength import evaluate as strength,stamp

NY=ZoneInfo('America/New_York');UTC=timezone.utc
OUT=ROOT/'exports/trade_review/2026-11-11_common_factors'
OLD=ROOT/'exports/trade_review/2026-11-01_opening_three_candles'
ARCHIVE=ROOT/'exports/trade_review/2026-11-06_impulse_study/impulse_evidence.sqlite3'
MARKET=ROOT/'exports/market_data.db'


def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')


def readonly(path,seconds=5):
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)
    db.execute('PRAGMA query_only=ON');deadline=time.monotonic()+seconds
    db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
    return db


def no_overlap(rows,seconds):
    result=[];ends={}
    for r in sorted(rows,key=lambda r:r['at']):
        key=(r['cohort'],r['symbol'])
        if r['at']<ends.get(key,-math.inf):continue
        result.append(r);ends[key]=r['at']+seconds
    return result


def volume_ratio(minutes,at):
    previous=at-60;local=datetime.fromtimestamp(previous,NY)
    if not (570<=local.hour*60+local.minute<960):return None
    current=minutes.get(previous)
    prior=[minutes.get(int((local-timedelta(days=d)).timestamp())) for d in range(1,46)]
    prior=[r[5] for r in prior if r is not None][:20]
    return current[5]/median(prior) if current and len(prior)>=10 and median(prior)>0 else None


def minute_study(plan):
    # Original current-predicate replay already excludes missing references.
    source=ROOT/'exports/trade_review/2026-11-09_opening_strength/minute_events.json'
    events=json.loads(source.read_text());manifest=json.loads((OLD/'source_manifest.json').read_text())
    sessions=json.loads((OLD/'calendar.json').read_text())
    periods=[int(datetime.fromisoformat(a).timestamp())+offset for d,a,b in sessions
        for offset in range(0,int((datetime.fromisoformat(b)-datetime.fromisoformat(a)).total_seconds()),900)]
    indices={p:i for i,p in enumerate(periods)};rows=[];sources=[];exclusions=Counter()
    for item in manifest:
        path=OLD/'source'/(item['symbol']+'.json.gz');sha=hashlib.sha256(path.read_bytes()).hexdigest()
        assert sha==item['source_sha256']
        sources.append(dict(symbol=item['symbol'],sha256=sha))
        with gzip.open(path,'rt',encoding='utf-8') as f:data=json.load(f)
        bounds={d:(int(datetime.fromisoformat(a).timestamp()),int(datetime.fromisoformat(b).timestamp())) for d,a,b in sessions}
        minutes={};slots=defaultdict(list)
        for r in data:
            t=int(datetime.fromisoformat(r[0]).timestamp());local=datetime.fromtimestamp(t,NY);day=local.date().isoformat()
            if day in bounds and bounds[day][0]<=t<bounds[day][1] and t%60==0:
                minutes[t]=r;slots[t//900*900].append((t,r))
        for rs in slots.values():rs.sort()
        closes={p:r[-1][1][4] for p,r in slots.items()}
        for e in (e for e in events if e['symbol']==item['symbol']):
            at,start=e['at'],e['candle'];i=indices[start]
            previous=[closes.get(p) for p in periods[i-20:i]]
            if len(previous)!=20 or any(p is None for p in previous):
                exclusions['REFERENCE_MISSING']+=1;continue
            p=e['price'];opening=minutes[start][1]
            pu,pl=bands_at_open(previous[:-1],previous[-1]);u,l=bands_at_open(previous[1:],p)
            ou,ol=bands_at_open(previous[1:],opening)
            previous_mid=fmean(previous);mid=fmean(previous[1:]+[p])
            side=detect_values(previous[-1],pu,pl,previous_mid,p,u,l,mid,
                opening=opening,opening_upper=ou,opening_lower=ol)
            if side!=e['side']:
                exclusions['PREDICATE_MISMATCH']+=1;continue
            width=pu-pl;event=dict(side=side,price=p,opening=opening,band_expansion=dict(
                upper=u,lower=l,previous_upper=pu,previous_lower=pl,
                upper_pct=100*(u-pu)/width,lower_pct=100*(pl-l)/width))
            features=geometry_features(event);features['volume_ratio']=volume_ratio(minutes,at)
            direction=1 if side=='SUPERIOR' else -1
            # Minute-only proxy explicitly distinct from second-level pace.
            anchor=minutes.get(at-60)
            features['pace']=direction*(p-anchor[1])/width if anchor else None
            widths=[]
            for j in range(max(20,i-20),i):
                values=[closes.get(p) for p in periods[j-20:j]]
                if len(values)==20 and all(v is not None for v in values):
                    a,b=bands_at_open(values[:-1],values[-1]);widths.append(100*(a-b)/values[-1])
            features['width_ratio']=features['width_pct']/median(widths) if len(widths)>=10 and median(widths)>0 else None
            row=dict(symbol=e['symbol'],day=e['day'],at=at,cohort='MINUTE_PROXY_CURRENT_GEOMETRY_NO_30S_CLOCK',
                window=e['group'],age_seconds=at-start,features=features,
                partition=plan['minute_partition'][e['day']],outcomes={})
            for h in ('1','3','5'):
                outcome=e['future'][h]
                for source_key,key in (('return_pct','return'),('mfe_pct','mfe'),('mae_pct','mae')):
                    row['outcomes'][key+'_'+h+'m']=outcome.get(source_key) if outcome['available'] else None
            rows.append(row)
    rows=no_overlap(rows,300);save('minute_rows.json',rows);save('minute_sources.json',sources)
    return rows,dict(exclusions)


def tick_study(plan):
    with closing(readonly(MARKET)) as db:
        events=[]
        for key,detected,raw in db.execute('SELECT event_key,detected_at,payload_json FROM bollinger_live_events WHERE detected_at>=? ORDER BY detected_at',('2026-11-05',)):
            event=json.loads(raw)
            if event.get('source_kind')=='TRADE' and event.get('band_expansion'):
                events.append(event|dict(event_key=key,detected_at=detected))
    save('original_trade_signals.json',events)
    frozen={};rows=[];errors=[]
    with closing(readonly(ARCHIVE,seconds=120)) as db:
        db.execute('BEGIN')
        gap_count=db.execute('SELECT count(*) FROM gaps').fetchone()[0]
        for event in events:
            source=stamp(event['source_timestamp']);decision=stamp(event['detected_at'])
            begin=(source-timedelta(seconds=12)).strftime('%Y-%m-%dT%H:%M:%S')
            end=(source+timedelta(seconds=62)).strftime('%Y-%m-%dT%H:%M:%S')
            observations=[];raw_ticks=[]
            for received,at,raw in db.execute('SELECT received,source_time,message FROM ticks WHERE symbol=? AND source_time>=? AND source_time<? ORDER BY source_time',
                                            (event['symbol'],begin,end)):
                try:
                    m=json.loads(raw);extra=m['_jjtrade'];g=extra['geometry']
                    if m.get('T')!='t' or not isinstance(g,dict):continue
                    price=float(m['p'])
                    if not math.isfinite(price) or price<=0:continue
                    row=dict(time=at,received=received,processed=extra['processed_at'],price=price,
                        **{k:g.get(k) for k in ('upper','lower','previous_upper','previous_lower')})
                    raw_ticks.append(row)
                    observations.append(dict(time=epoch(at),received=epoch(received),price=price))
                except (KeyError,TypeError,ValueError):continue
            # The original signal itself proves its own entry reference price.
            # This is marked separately, never invented as a raw market trade.
            observations.append(dict(time=source.timestamp(),received=decision.timestamp(),price=event['price'],origin='ORIGINAL_SIGNAL_REFERENCE'))
            features=geometry_features(event)
            st=strength(event,raw_ticks)
            features['pace']=None
            cutoff=source-timedelta(seconds=3)
            anchors=[r for r in raw_ticks if cutoff-timedelta(seconds=1)<=stamp(r['time'])<=cutoff
                and stamp(r['received'])<=decision and stamp(r['processed'])<=decision]
            if anchors:
                anchor=max(anchors,key=lambda r:stamp(r['time']));d=1 if event['side']=='SUPERIOR' else -1
                features['pace']=d*(event['price']-anchor['price'])/(event['band_expansion']['previous_upper']-event['band_expansion']['previous_lower'])
            features['strength_components']=st['components'];features['strength_metrics']=st['metrics']
            features['volume_ratio']=None;features['width_ratio']=None
            # Original causal volume snapshots, if previously recorded, take
            # precedence over a retroactively revised minute volume.
            with closing(sqlite3.connect((ROOT/'exports/movement_strength.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=.1)) as scores:
                from movement_strength_store import identity
                score=scores.execute('SELECT payload FROM strength WHERE event_key=?', (identity(event),)).fetchone()
            if score:
                v=json.loads(score[0]).get('metrics',{}).get('volume_previous_closed_minute',{})
                if v and stamp(v['closed_at'])<=source and stamp(v['known_at'])<=decision:
                    features['volume_ratio']=v['ratio']
            result=labels(event,observations);outcomes={}
            for h in ('1','3','5','10','30','60'):
                outcomes['return_'+h+'s']=result['future_underlying_labels'][h]['directional_return_pct']
            # Relaxed endpoints are reported separately, never used to select.
            for h in (30,60):
                xs=[r for r in observations if source.timestamp()<r['time']<=source.timestamp()+h]
                last=max(xs,key=lambda r:r['time']) if xs else None
                outcomes['sensitivity_return_'+str(h)+'s']=100*(1 if event['side']=='SUPERIOR' else -1)*(last['price']/event['price']-1) if last and source.timestamp()+h-last['time']<=3 else None
            day=source.astimezone(NY).date().isoformat()
            row=dict(symbol=event['symbol'],at=source.timestamp(),day=day,cohort=event['version']+'|'+str(event.get('feed'))+'|'+str(event.get('reference_scope')),
                partition=plan['tick_partition'].get(day,'OLD_DIFFERENT_RULE'),window=result['window'],
                features=features,outcomes=outcomes,source_event_key=event['event_key'])
            rows.append(row);frozen[event['event_key']]=dict(ticks=raw_ticks,entry_reference=observations[-1],path30=result['path_30s'])
        db.rollback()
    rows=no_overlap(rows,60);save('tick_rows.json',rows);save('frozen_tick_evidence.json',frozen)
    return rows,dict(retention_gaps=gap_count,errors=errors)


def evaluate_groups(rows,metric,*,current=False):
    if current:rows=[r for r in rows if r['cohort'].startswith(STRATEGY_VERSION+'|')]
    result={}
    for partition in ('TRAIN','VALIDATION','TEST','ALL'):
        selected=rows if partition=='ALL' else [r for r in rows if r['partition']==partition]
        result[partition]=dict(signals=len(selected),days=sorted({r['day'] for r in selected}),
            candidates={c:comparison(selected,c,metric) for c in CANDIDATES},
            bootstrap={c:day_difference(selected,c,metric) for c in CANDIDATES[1:]})
    train=[r for r in rows if r['partition']=='TRAIN']
    choice=rank_on_training(train,metric)
    result['chosen_on_training']=choice
    result['common_factors']={}
    for name,key,bins in (
        ('opposite','opposite',[(3,5),(5,8),(8,math.inf)]),
        ('volume','volume_ratio',[(0,1),(1,1.5),(1.5,math.inf)]),
        ('exposure','exposure',[(0,1),(1,3),(3,math.inf)]),
        ('width','width_ratio',[(0,1),(1,math.inf)])):
        result['common_factors'][name]={str(lo)+'_'+str(hi):summarize([r for r in rows if r['features'].get(key) is not None and lo<=r['features'][key]<hi],metric) for lo,hi in bins}
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    days=json.loads((OLD/'analysis_plan.json').read_text())['days']
    plan=dict(created_at=datetime.now(UTC).isoformat(),mode='RESEARCH_ONLY_NO_ACTIVATION',
        candidates=CANDIDATES,minute_primary='return_1m',tick_primary='return_30s',
        minute_partition={d:'TRAIN' if i<22 else 'VALIDATION' if i<42 else 'TEST' for i,d in enumerate(days)},
        tick_partition={'2026-11-09':'TRAIN','2026-11-10':'VALIDATION','2026-11-11':'TEST'},
        selection='Training only; >=30 covered, >=40% kept, <=20% missing features; positive fraction gain >=5pp AND mean return higher. Missing feature means pass, not veto.',
        activation='No live activation from this research. Need confirmation in current-second cohort, adequate session clusters and execution/option impact before trading changes.',
        limitations=['Historical minutes already studied: chronological descriptive check, not pristine prospective test.',
            'Minute geometry cannot recover 30s first-cross expiry; separate proxy, never merged with live V7.',
            '10/30/60s signed underlying returns are not contract P&L or target/stop touches.',
            'No entry waiting, no looking at future candle close for features.',
            'Multiple exploratory comparisons; report all candidates, unknowns and discarded favorable cases.'])
    save('plan.json',plan)
    minutes,minute_exclusions=minute_study(plan)
    print(json.dumps(dict(stage='MINUTES_FROZEN',events=len(minutes))),flush=True)
    ticks,tick_evidence=tick_study(plan)
    report=dict(created_at=datetime.now(UTC).isoformat(),plan=plan,minute_exclusions=minute_exclusions,
        tick_evidence=tick_evidence,minute_results=evaluate_groups(minutes,'return_1m'),
        minute_secondary={m:evaluate_groups(minutes,m) for m in ('return_5m','mfe_1m','mae_1m')},
        current_tick_results=evaluate_groups(ticks,'return_30s',current=True),
        current_tick_secondary={m:evaluate_groups(ticks,m,current=True) for m in ('return_10s','return_60s','sensitivity_return_30s')},
        tick_cohorts=dict(Counter(r['cohort'] for r in ticks)))
    save('report.json',report)
    print(json.dumps(dict(stage='COMPLETE',minute_events=len(minutes),tick_events=len(ticks),
        selected_minute=report['minute_results']['chosen_on_training'],selected_tick=report['current_tick_results']['chosen_on_training'])),flush=True)


if __name__=='__main__':main()
