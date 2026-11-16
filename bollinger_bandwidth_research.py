"""Total current Bollinger width, distinct from per-band expansion. Pure research."""
from statistics import median
import math


def bandwidth(upper,lower,price=None):
    try:
        if isinstance(upper,bool) or isinstance(lower,bool):return None
        upper,lower=float(upper),float(lower)
        middle=(upper+lower)/2
        if not all(math.isfinite(v) for v in (upper,lower,middle)) or lower<=0 or upper<=lower:return None
        result=dict(width_usd=upper-lower,middle=middle,bandwidth_pct=100*(upper-lower)/middle)
        if price is not None:
            p=float(price)
            if math.isfinite(p) and p>0 and not isinstance(price,bool):result['price_width_pct']=100*(upper-lower)/p
        return result
    except (ValueError,TypeError,OverflowError):return None


def measurements(event,prior_bandwidths=()):
    edges=event.get('band_expansion') or {}
    current=bandwidth(edges.get('upper'),edges.get('lower'),event.get('price'))
    old=bandwidth(edges.get('previous_upper'),edges.get('previous_lower'))
    if current is None:return dict(state='SIN_DATOS')
    result=current|dict(state='DESCRIPTIVO',previous_bandwidth_pct=old['bandwidth_pct'] if old else None,
                        total_width_growth_pct=None,relative_to_prior20=None,baseline_count=0)
    if old:result['total_width_growth_pct']=100*(current['width_usd']/old['width_usd']-1)
    values=[]
    for value in prior_bandwidths:
        try:
            n=float(value)
            if not isinstance(value,bool) and math.isfinite(n) and n>0:values.append(n)
        except (ValueError,TypeError):pass
    values=values[-20:];result['baseline_count']=len(values)
    if len(values)>=10:result['relative_to_prior20']=current['bandwidth_pct']/median(values)
    return result


def cutpoints(values,min_samples=8):
    xs=sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if len(xs)<min_samples:return None
    return [xs[int((len(xs)-1)*q)] for q in (.25,.5,.75)]


def quartile(value,edges):
    if value is None or edges is None:return 'SIN_REFERENCIA'
    try:
        if isinstance(value,bool) or not math.isfinite(float(value)):return 'SIN_REFERENCIA'
        value=float(value)
    except (ValueError,TypeError):return 'SIN_REFERENCIA'
    return 'Q'+str(1+sum(value>edge for edge in edges))
