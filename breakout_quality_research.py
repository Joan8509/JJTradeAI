"""Experimental causal candidates for playback. No I/O or live authority."""
import math
from statistics import fmean, median
from collections import defaultdict
import random
from datetime import datetime,timedelta

CANDIDATES = ('BASE','OPPOSITE_5','OPPOSITE_8','BOTH_5','VOLUME_15',
              'EXPOSURE_1','WIDTH_ABOVE_MEDIAN','POSITIVE_PACE',
              'OPPOSITE_5_VOLUME_15','OPPOSITE_5_POSITIVE_PACE')


def number(value):
    if isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None


def geometry_features(event):
    e=event.get('band_expansion') or {};side=event.get('side')
    values={k:number(e.get(k)) for k in ('upper','lower','previous_upper','previous_lower','upper_pct','lower_pct')}
    p=number(event.get('price'));op=number(event.get('opening'))
    result=dict(opposite=None,minimum=None,exposure=None,width_pct=None,body_width_pct=None)
    if side not in ('SUPERIOR','INFERIOR'):return result
    d=1 if side=='SUPERIOR' else -1
    result['opposite']=values['lower_pct' if d==1 else 'upper_pct']
    if values['upper_pct'] is not None and values['lower_pct'] is not None:
        result['minimum']=min(values['upper_pct'],values['lower_pct'])
    if p is not None and p>0 and values['previous_upper'] is not None and values['previous_lower'] is not None:
        width=values['previous_upper']-values['previous_lower']
        if width>0:
            result['width_pct']=100*width/p
            edge=values['upper' if d==1 else 'lower']
            if edge is not None:result['exposure']=100*d*(p-edge)/width
            if op is not None:result['body_width_pct']=100*d*(p-op)/width
    return result


def selected(features,candidate):
    if callable(candidate):return candidate(features)
    def compare(key,threshold):
        value=number(features.get(key))
        return None if value is None else value>=threshold
    if candidate=='BASE':return True
    if candidate=='OPPOSITE_5':return compare('opposite',5)
    if candidate=='OPPOSITE_8':return compare('opposite',8)
    if candidate=='BOTH_5':return compare('minimum',5)
    if candidate=='VOLUME_15':return compare('volume_ratio',1.5)
    if candidate=='EXPOSURE_1':return compare('exposure',1)
    if candidate=='WIDTH_ABOVE_MEDIAN':return compare('width_ratio',1)
    if candidate=='POSITIVE_PACE':
        v=number(features.get('pace'))
        return None if v is None else v>0
    if candidate in ('OPPOSITE_5_VOLUME_15','OPPOSITE_5_POSITIVE_PACE'):
        a=selected(features,'OPPOSITE_5')
        b=selected(features,'VOLUME_15' if candidate.endswith('VOLUME_15') else 'POSITIVE_PACE')
        return False if a is False or b is False else None if a is None or b is None else True
    raise ValueError(candidate)


def summarize(rows,metric):
    values=[number(r.get('outcomes',{}).get(metric)) for r in rows]
    values=[v for v in values if v is not None]
    return dict(signals=len(rows),covered=len(values),missing=len(rows)-len(values),
        positive=sum(v>0 for v in values),negative=sum(v<0 for v in values),flat=sum(v==0 for v in values),
        positive_pct=100*sum(v>0 for v in values)/len(values) if values else None,
        strong_010=sum(v>=.1 for v in values),mean=fmean(values) if values else None,
        median=median(values) if values else None)


def comparison(rows,candidate,metric):
    yes=[];no=[];unknown=[]
    for row in rows:
        flag=selected(row['features'],candidate)
        (yes if flag is True else no if flag is False else unknown).append(row)
    # Compare on the same known-feature coverage, not against a different sample.
    return dict(retained=summarize(yes,metric),discarded=summarize(no,metric),
                unknown=summarize(unknown,metric),known_baseline=summarize(yes+no,metric),
                unknown_pass=summarize(yes+unknown,metric),baseline=summarize(rows,metric))


def day_difference(rows,candidate,metric,iterations=2000):
    by=defaultdict(list)
    for r in rows:
        value=number(r.get('outcomes',{}).get(metric))
        flag=selected(r['features'],candidate)
        if value is not None and flag is not None:by[(r['day'],r['symbol'])].append((value,flag))
    days=defaultdict(list)
    for (day,symbol),samples in by.items():
        kept=[v for v,f in samples if f]
        if kept:days[day].append(fmean(kept)-fmean(v for v,f in samples))
    diffs=[fmean(v) for v in days.values()]
    if not diffs:return dict(days=0,mean=None,ci95=None)
    result=dict(days=len(diffs),mean=fmean(diffs),ci95=None)
    if len(diffs)>=5:
        rng=random.Random(20261111)
        values=sorted(fmean(rng.choices(diffs,k=len(diffs))) for _ in range(iterations))
        result['ci95']=[values[int(iterations*.025)],values[min(iterations-1,int(iterations*.975))]]
    return result


def rank_on_training(rows,metric,min_covered=30):
    """Never sees validation/test rows. Default abstention if none clears gates."""
    candidates=[]
    for candidate in CANDIDATES[1:]:
        c=comparison(rows,candidate,metric);kept=c['unknown_pass'];base=c['baseline']
        if (kept['covered']>=min_covered and base['covered'] and
            kept['covered']/base['covered']>=.4 and c['unknown']['signals']<=.2*len(rows) and
            kept['mean']>base['mean'] and kept['positive_pct']>=base['positive_pct']+5):
            candidates.append((kept['mean']-base['mean'],candidate))
    return max(candidates)[1] if candidates else None


def fit_tree(rows,metric,keys,max_depth=2,min_leaf=50):
    """Small exploratory tree: training only, fixed depth and minimum support.

    No future labels are consulted at prediction. Missing split features cause
    abstention, preserving normal entry in an eventual unknown-pass comparison.
    """
    rows=[r for r in rows if number(r.get('outcomes',{}).get(metric)) is not None]
    def build(samples,depth):
        values=[r['outcomes'][metric] for r in samples]
        rate=fmean(v>0 for v in values) if values else None
        node=dict(samples=len(samples),positive_fraction=rate,mean_return=fmean(values) if values else None)
        if depth>=max_depth or len(samples)<2*min_leaf:return node
        best=None
        for key in keys:
            available=[r for r in samples if number(r['features'].get(key)) is not None]
            xs=sorted(r['features'][key] for r in available)
            if len(xs)<2*min_leaf:continue
            thresholds=sorted({xs[int((len(xs)-1)*q/10)] for q in range(1,10)})
            p=fmean(r['outcomes'][metric]>0 for r in available)
            for threshold in thresholds:
                left=[r for r in available if r['features'][key]<=threshold]
                right=[r for r in available if r['features'][key]>threshold]
                if min(len(left),len(right))<min_leaf:continue
                a=fmean(r['outcomes'][metric]>0 for r in left)
                b=fmean(r['outcomes'][metric]>0 for r in right)
                gain=(p*(1-p)-(len(left)*a*(1-a)+len(right)*b*(1-b))/len(available))*len(available)/len(samples)
                if best is None or gain>best[0]:best=(gain,key,threshold,left,right)
        if best is None or best[0]<.002:return node
        gain,key,threshold,left,right=best
        return node|dict(feature=key,threshold=threshold,gain=gain,
                         left=build(left,depth+1),right=build(right,depth+1))
    return build(rows,0)


def tree_prediction(features,tree):
    node=tree
    while 'feature' in node:
        value=number(features.get(node['feature']))
        if value is None:return None
        node=node['left' if value<=node['threshold'] else 'right']
    # Only flag weakness when the training leaf has negative average movement
    # AND <=40% favorable outcomes. All other leaves preserve normal entry.
    if node['positive_fraction'] is None:return None
    return not (node['positive_fraction']<=.4 and node['mean_return']<0)


def initial_rates(event,ticks):
    """Rate at the FIRST signal, not a wait for a larger future expansion."""
    def time(value):
        t=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if t.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
        return t
    result=dict(opposite_rate=None,trigger_age=None)
    try:
        source,decision=time(event['source_timestamp']),time(event['detected_at'])
        if source>decision:return result
        first=time(event['first_breakout_at'])
        if first<=source:result['trigger_age']=(source-first).total_seconds()
    except (TypeError,KeyError,ValueError):
        try:source,decision=time(event['source_timestamp']),time(event['detected_at'])
        except (TypeError,KeyError,ValueError):return result
    if event.get('side') not in ('SUPERIOR','INFERIOR'):return result
    e=event.get('band_expansion') or {};pu=number(e.get('previous_upper'));pl=number(e.get('previous_lower'))
    if pu is None or pl is None or pu<=pl:return result
    edge='lower' if event['side']=='SUPERIOR' else 'upper';current=number(e.get(edge))
    d=-1 if edge=='lower' else 1;choices=[]
    if current is None:return result
    for row in ticks:
        try:
            t=time(row['time']);value=number(row.get(edge))
            if (source-timedelta(seconds=3)<=t<source and time(row['received'])<=decision
                and time(row['processed'])<=decision and value is not None
                and row.get('previous_upper')==pu and row.get('previous_lower')==pl):
                choices.append((t,value))
        except (TypeError,KeyError,ValueError):continue
    if choices:
        at=max(t for t,v in choices);values={v for t,v in choices if t==at}
        if len(values)==1:
            result['opposite_rate']=100*d*(current-values.pop())/(pu-pl)/(source-at).total_seconds()
    return result
