"""Frozen causal feature and delay study. No broker, orders or production writes."""
from pathlib import Path
from collections import Counter
from contextlib import closing
from datetime import datetime,timedelta,timezone
from statistics import mean,median
from hashlib import sha256
import json,sys,sqlite3,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from breakout_quality_research import geometry_features,initial_rates,comparison,rank_on_training,day_difference
from movement_strength import evaluate as strength,stamp
from movement_strength_store import identity
from scripts.study_target_ten import read_only

SOURCE=ROOT/'exports/trade_review/2026-11-16_target10'
OUT=ROOT/'exports/trade_review/2026-11-16_target_certainty'
CANDIDATES=['BASE','OPPOSITE_5','OPPOSITE_8','BOTH_5','VOLUME_15','EXPOSURE_1','POSITIVE_PACE']

def primary_outcomes(event,ticks):
    start=stamp(event['source_timestamp']);direction=1 if event['side']=='SUPERIOR' else -1
    rows=[r for r in ticks if stamp(r['time'])>=start];result={}
    for h in (10,30,60):
        target=start+timedelta(seconds=h)
        match=min(rows,key=lambda r:abs((stamp(r['time'])-target).total_seconds()),default=None)
        result['return_'+str(h)+'s']=100*direction*(match['price']/event['price']-1) if match and abs((stamp(match['time'])-target).total_seconds())<=1 else None
    return result

def delay_comparison(event,ticks,delay,horizon=10):
    start=stamp(event['source_timestamp']);d=1 if event['side']=='SUPERIOR' else -1
    target=start+timedelta(seconds=horizon);entry=start+timedelta(seconds=delay)
    candidates=[r for r in ticks if entry<=stamp(r['time'])<=entry+timedelta(seconds=1)]
    q=min(candidates,key=lambda r:stamp(r['time']),default=None)
    ends=[r for r in ticks if start<=stamp(r['time'])]
    end=min(ends,key=lambda r:abs((stamp(r['time'])-target).total_seconds()),default=None)
    if not q or not end or abs((stamp(end['time'])-target).total_seconds())>1:return None
    baseline=100*d*(end['price']/event['price']-1)
    delayed=100*d*(end['price']/q['price']-1)
    return dict(baseline=baseline,delayed=delayed,entry_displacement_pct=100*d*(q['price']/event['price']-1),
        difference_pp=baseline-delayed)

def causal_features(event,ticks,volume=None):
    f=geometry_features(event);f.update(initial_rates(event,ticks))
    source,decision=stamp(event['source_timestamp']),stamp(event['detected_at'])
    f.update(pace=None,volume_ratio=None,width_ratio=None)
    width=event['band_expansion']['previous_upper']-event['band_expansion']['previous_lower']
    target=source-timedelta(seconds=3)
    available=[r for r in ticks if target-timedelta(seconds=1)<=stamp(r['time'])<=target
        and stamp(r['received'])<=decision and stamp(r['processed'])<=decision]
    if available and width>0:
        at=max(stamp(r['time']) for r in available)
        prices={r['price'] for r in available if stamp(r['time'])==at}
        if len(prices)==1:f['pace']=(1 if event['side']=='SUPERIOR' else -1)*(event['price']-prices.pop())/width
    st=strength(event,ticks,volume)
    f['strength_components']=st['components'];f['strength_metrics']=st['metrics']
    v=st['metrics'].get('volume_previous_closed_minute')
    if v:f['volume_ratio']=v['ratio']
    return f

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source_report=json.loads((SOURCE/'report.json').read_text(encoding='utf-8'))
    frozen=source_report['plan']['frozen_at']
    old_rows={(r['at'],r['symbol']):r for r in source_report['signals']['rows']}
    original=json.loads((SOURCE/'signal_evidence.json').read_text(encoding='utf-8'))
    plan=dict(frozen_at=frozen,created_at=datetime.now(timezone.utc).isoformat(),research_only=True,
        source_signals=132,primary='return_10s',secondary=['return_30s','return_60s'],
        train=['2026-11-09','2026-11-10','2026-11-11'],validation=['2026-11-12','2026-11-13'],test=['2026-11-16'],
        temporal_split='Retrospective, these historical days were already examined. Not independent prospective validation.',
        candidates=CANDIDATES+['FIRST_1S','OPPOSITE_RATE_POSITIVE','EFFICIENT_PRIOR_PATH','OPENING_15M'],
        thresholds='Reuse existing thresholds from research before Nov16; no outcome-guided threshold search.',
        gate_selection='Existing rank_on_training: >=30 covered, >=40% retained coverage, <=20% unknown, +5pp and positive mean improvement.',
        delays_seconds=[1,3,5],delay_label='Underlying price sensitivity, not option PnL or execution simulation.',
        no_activation=True)
    (OUT/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    archive=ROOT/'exports/trade_review/2026-11-06_impulse_study/impulse_evidence.sqlite3'
    rows=[];evidence=[]
    with closing(read_only(archive,seconds=100)) as db, closing(read_only(ROOT/'exports/movement_strength.sqlite3',seconds=100)) as scores:
        db.execute('BEGIN');scores.execute('BEGIN')
        for item in original:
            e=item['event'];source=stamp(e['source_timestamp']);start=source-timedelta(seconds=12);end=source+timedelta(seconds=62)
            data=db.execute('SELECT received,source_time,message FROM ticks WHERE symbol=? AND source_time>=? AND source_time<? ORDER BY source_time',
                (e['symbol'],start.strftime('%Y-%m-%dT%H:%M:%S'),end.strftime('%Y-%m-%dT%H:%M:%S'))).fetchall()
            ticks=[]
            for received,at,raw in data:
                m=json.loads(raw);ex=m.get('_jjtrade',{});g=ex.get('geometry')
                if m.get('T')!='t' or not isinstance(g,dict) or stamp(received)>stamp(frozen):continue
                ticks.append(dict(time=at,received=received,processed=ex['processed_at'],price=m['p'],
                    **{k:g.get(k) for k in ('upper','lower','previous_upper','previous_lower')}))
            value=scores.execute('SELECT payload FROM strength WHERE event_key=?',(identity(e),)).fetchone()
            volume=(json.loads(value[0]).get('metrics',{}).get('volume_previous_closed_minute') if value else None)
            features=causal_features(e,ticks,volume)
            old=old_rows[(source.isoformat(),e['symbol'])]
            features['opening_15m']=old['window']=='OPENING_15M'
            partition='TRAIN' if old['day'] in plan['train'] else 'VALIDATION' if old['day'] in plan['validation'] else 'TEST'
            row=dict(symbol=e['symbol'],at=source.timestamp(),day=old['day'],partition=partition,
                features=features,outcomes=primary_outcomes(e,ticks),delays={str(d):delay_comparison(e,ticks,d) for d in plan['delays_seconds']})
            rows.append(row);evidence.append(dict(event=e,ticks=ticks,volume=volume))
        db.rollback();scores.rollback()
    predicates={c:c for c in CANDIDATES}
    predicates.update(FIRST_1S=lambda f:None if f.get('trigger_age') is None else f['trigger_age']<=1,
        OPPOSITE_RATE_POSITIVE=lambda f:None if f.get('opposite_rate') is None else f['opposite_rate']>0,
        EFFICIENT_PRIOR_PATH=lambda f:f.get('strength_components',{}).get('continuity'),
        OPENING_15M=lambda f:f['opening_15m'])
    metrics=[plan['primary'],*plan['secondary']]
    parts={}
    for partition in ('TRAIN','VALIDATION','TEST','LATER','ALL'):
        rs=rows if partition=='ALL' else [r for r in rows if r['partition']==partition or partition=='LATER' and r['partition']!='TRAIN']
        comparisons={metric:{name:comparison(rs,pred,metric) for name,pred in predicates.items()} for metric in metrics}
        delays={}
        for d in plan['delays_seconds']:
            covered=[r['delays'][str(d)] for r in rs if r['delays'][str(d)] is not None]
            delays[str(d)]=dict(paired_covered=len(covered),missing=len(rs)-len(covered),
                mean_entry_displacement_pct=mean(r['entry_displacement_pct'] for r in covered) if covered else None,
                median_difference_pp=median(r['difference_pp'] for r in covered) if covered else None,
                mean_difference_pp=mean(r['difference_pp'] for r in covered) if covered else None,
                helped_by_earlier_entry=sum(r['difference_pp']>0 for r in covered),
                helped_by_later_entry=sum(r['difference_pp']<0 for r in covered))
        parts[partition]=dict(signals=len(rs),comparison=comparisons,delays=delays)
    chosen=rank_on_training([r for r in rows if r['partition']=='TRAIN'],plan['primary'])
    report=dict(plan=plan,rows=rows,partitions=parts,chosen_on_training=chosen,
        feature_coverage={k:sum(r['features'].get(k) is not None for r in rows) for k in ('opposite','pace','volume_ratio','opposite_rate','trigger_age')},
        option_target_outcomes_available=0,orders_sent=0,previews_sent=0,production_changes=0)
    (OUT/'evidence.json').write_text(json.dumps(evidence),encoding='utf-8')
    (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(chosen=chosen,coverage=report['feature_coverage'],parts={p:dict(signals=v['signals'],
        results={name:{k:v['comparison']['return_10s'][name][k] for k in ('retained','discarded','unknown')} for name in predicates},delays=v['delays']) for p,v in parts.items()}),indent=2))
if __name__=='__main__':main()
