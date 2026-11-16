"""Pure research features and summaries. No trading decisions or live I/O."""
from datetime import datetime,timedelta,timezone
from statistics import fmean,median
from collections import defaultdict
from ma_price_outlook import outlook
from ma_price_outlook import number


def features(event):
    """Use only the context known for the original signal, never its outcome."""
    context=event.get('ma_context')
    if not isinstance(context,dict):return dict(state='SIN_DATOS')
    try:
        source=datetime.fromisoformat(event['source_timestamp'].replace('Z','+00:00'))
        decision=datetime.fromisoformat(event['detected_at'].replace('Z','+00:00'))
        known=datetime.fromisoformat(context['available_at'].replace('Z','+00:00'))
        allowance=timedelta() if event.get('source_kind')=='TRADE' else timedelta(minutes=1)
        if (any(s.tzinfo is None for s in (source,decision,known)) or known>source+allowance
            or known>decision or context.get('price')!=event.get('price')):
            return dict(state='CONTEXTO_NO_CAUSAL')
    except (TypeError,ValueError,KeyError):return dict(state='CONTEXTO_NO_CAUSAL')
    value=outlook(context,event['side'])
    if value['state']!='DESCRIPTIVO':return dict(state='SIN_DATOS')
    wanted='ALCISTA' if event['side']=='SUPERIOR' else 'BAJISTA'
    frames={f['timeframe']:f for f in context.get('frames',[])}
    def pair(periods):
        rows=[]
        for tf in ('1H','1D'):
            frame=frames.get(tf,{})
            a=number(frame.get('averages',{}).get(str(periods[0])))
            b=number(frame.get('averages',{}).get(str(periods[1])))
            if a is None or b is None:return None
            rows.append(a>b if wanted=='ALCISTA' else a<b)
        return all(rows)
    distance=value['route'][0]['distance_pct'] if value['route'] else None
    bucket=('SIN_MEDIA_DELANTE_COMPLETO' if value['complete'] else 'INCOMPLETO') if distance is None else (
        'CERCA_MENOS_010' if distance<.1 else 'ENTRE_010_050' if distance<.5 else 'LEJOS_050_O_MAS')
    limit=value['nearest_limit']
    slope_alignment=[]
    for tf in ('1H','1D'):
        frame=frames.get(tf,{})
        a=number(frame.get('averages',{}).get('20'));b=number(frame.get('averages',{}).get('40'))
        x=number(frame.get('slopes',{}).get('20'));y=number(frame.get('slopes',{}).get('40'))
        if any(v is None for v in (a,b,x,y)):slope_alignment.append(None)
        else:slope_alignment.append(a>b and x>0 and y>0 if wanted=='ALCISTA' else a<b and x<0 and y<0)
    both_slope=None if None in slope_alignment else all(slope_alignment)
    return dict(state='DESCRIPTIVO',reading=value['reading'],complete=value['complete'],
        order20_both_aligned=pair([20,40]),order100_both_aligned=pair([100,200]),
        slope20_both_aligned=both_slope,
        crosses20_both_validated=value['crosses_validated'],
        nearest_ma_distance_pct=distance,distance_bucket=bucket,
        nearest_limit_distance_pct=limit['distance_pct'] if limit else None,
        unknown_forward_roles=any(r['role']=='TENDENCIA_NO_VALIDADA' for r in value['route']))


def selected(row,candidate):
    """Return None for unknown; never interpret missing data as a losing trade."""
    f=row['features']
    if candidate=='BASE':return True
    if f.get('state')!='DESCRIPTIVO':return None
    if candidate=='ORDEN_20_HORA_DIARIO':return f['order20_both_aligned']
    if candidate=='ORDEN_Y_PENDIENTE_20_HORA_DIARIO':return f['slope20_both_aligned']
    if candidate=='ORDEN_100_HORA_DIARIO':return f['order100_both_aligned']
    if candidate=='ESPACIO_MEDIA_010':
        if not f['complete']:return None
        return f['nearest_ma_distance_pct'] is None or f['nearest_ma_distance_pct']>=.1
    if candidate=='LIMITE_VALIDADO_010':
        if not f['complete'] or f['unknown_forward_roles']:return None
        return f['nearest_limit_distance_pct'] is None or f['nearest_limit_distance_pct']>=.1
    raise ValueError('UNKNOWN_RESEARCH_CANDIDATE')


def nonoverlap(rows,seconds=60):
    ends={};result=[]
    for row in sorted(rows,key=lambda r:r['source_timestamp']):
        key=(row['symbol'],row['cohort']);t=datetime.fromisoformat(row['source_timestamp'])
        if t<ends.get(key,t):continue
        result.append(row);ends[key]=t+timedelta(seconds=seconds)
    return result


def summarize(rows,metric):
    values=[r['outcomes'].get(metric) for r in rows]
    known=[v for v in values if v is not None]
    return dict(signals=len(rows),covered=len(known),missing=len(values)-len(known),
        positive=sum(v>0 for v in known),negative=sum(v<0 for v in known),flat=sum(v==0 for v in known),
        positive_pct=100*fmean(v>0 for v in known) if known else None,
        mean_pct=fmean(known) if known else None,median_pct=median(known) if known else None)


def policies(rows,candidates,metric):
    result={}
    for candidate in candidates:
        kept=[];dropped=[];unknown=[]
        for row in rows:
            decision=selected(row,candidate)
            (kept if decision is True else dropped if decision is False else unknown).append(row)
        result[candidate]=dict(retained=summarize(kept,metric),discarded=summarize(dropped,metric),
            unknown=summarize(unknown,metric))
    return result


def paired_day_difference(rows,candidate,metric):
    """Equal weight per symbol/day, then paired day bootstrap (descriptive)."""
    import numpy as np
    all_values=defaultdict(list);keep_values=defaultdict(list)
    for row in rows:
        value=row['outcomes'].get(metric)
        if value is None:continue
        key=(row['day'],row['symbol']);all_values[key].append(value)
        if selected(row,candidate) is True:keep_values[key].append(value)
    differences=defaultdict(list)
    for key,keep in keep_values.items():differences[key[0]].append(fmean(keep)-fmean(all_values[key]))
    daily=[fmean(v) for v in differences.values()]
    if len(daily)<5:return dict(common_days=len(daily),confidence_interval=None,insufficient_days=True)
    values=np.array(daily);rng=np.random.default_rng(20261109)
    samples=values[rng.integers(0,len(values),size=(2000,len(values)))].mean(axis=1)
    return dict(common_days=len(daily),mean_difference_pct=float(values.mean()),
        confidence_interval=[float(np.quantile(samples,.025)),float(np.quantile(samples,.975))],
        meaning='Descriptive paired session bootstrap; not independent prospective validation.')
