"""Instant descriptive notice context from already observed radar snapshots.

No I/O, entry decision, confidence score, new threshold or waiting. Rates are
between radar observations, not every exchange trade or a forecast of profit.
"""
from collections import OrderedDict
from datetime import datetime
import math

REVISION=2


def number(value):
    if isinstance(value,bool):return None
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None


def clock(value):
    value=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return value


def describe_bands(expansion,price=None):
    if not isinstance(expansion,dict):return None
    upper,lower=number(expansion.get('upper')),number(expansion.get('lower'))
    if upper is None or lower is None or lower<=0 or upper<=lower:return None
    middle=(upper+lower)/2;pu=number(expansion.get('previous_upper'));pl=number(expansion.get('previous_lower'))
    result=dict(revision=REVISION,upper=upper,lower=lower,width_usd=upper-lower,bandwidth_pct=100*(upper-lower)/middle,
                price=number(price),width_growth_pct=None,phase='SIN_MUESTRAS',
                width_speed=None,acceleration=None)
    if pu is not None and pl is not None and pu>pl:
        result['width_growth_pct']=100*((upper-lower)/(pu-pl)-1)
    return result


class NoticeBandCache:
    """Bounded O(1) memory; repeated/out-of-order snapshots never fake speed."""
    def __init__(self,limit=128):
        self.limit=limit;self.samples=OrderedDict()

    def observe(self,database,payload,now):
        g=payload.get('geometry');result=describe_bands(g)
        if result is None:return None
        try:
            at=clock(payload['source_timestamp']);candle=clock(payload['candle'])
            if (payload.get('source_kind')!='TRADE' or now.tzinfo is None or
                not 0<=(now-at).total_seconds()<=3 or not 0<=(at-candle).total_seconds()<900):return None
            if not all(payload.get(k) for k in ('provider','feed','symbol','version','reference_scope')):return None
            key=(str(database),*(payload[k] for k in ('provider','feed','symbol','version','reference_scope')),
                 candle.isoformat(),number(g.get('previous_upper')),number(g.get('previous_lower')))
            current=dict(at=at,upper=float(g['upper']),lower=float(g['lower']),
                         price=number(g.get('price')),result=result,rate=None,midpoint=None)
            result.update(source_timestamp=at.isoformat(),price=current['price'],interval_seconds=None)
            previous=self.samples.get(key)
            if previous:
                dt=(at-previous['at']).total_seconds()
                if dt==0:
                    return dict(previous['result']) if all(current[k]==previous[k] for k in ('upper','lower','price')) else result
                if dt<0:return result  # Never use a later observation at an earlier source time.
                if dt<.25:return result  # Keep earlier anchor; this is not a wait for a signal.
                width=key[-2]-key[-1] if key[-2] is not None and key[-1] is not None else 0
                if dt<=3 and width>0:
                    upper=100*(current['upper']-previous['upper'])/width/dt
                    lower=100*(previous['lower']-current['lower'])/width/dt
                    rate=upper+lower;midpoint=(at.timestamp()+previous['at'].timestamp())/2
                    result.update(width_speed=rate,upper_speed=upper,lower_speed=lower,interval_seconds=dt,
                                  interval_started_at=previous['at'].isoformat())
                    if rate>1e-8:
                        result['phase']='ABRIENDO' if min(upper,lower)>0 else 'AUMENTA_ANCHO_UNA_BANDA_RETROCEDE'
                    elif rate < -1e-8:result['phase']='ESTRECHANDOSE'
                    else:result['phase']='ESTABLE'
                    if previous['rate'] is not None and midpoint>previous['midpoint']:
                        acceleration=(rate-previous['rate'])/(midpoint-previous['midpoint'])
                        result['acceleration']=acceleration
                        tolerance=1e-6*max(1,abs(rate),abs(previous['rate']))
                        if min(upper,lower)>0:
                            result['phase']=('APERTURA_ACELERANDO' if acceleration>tolerance else
                                             'APERTURA_A_RITMO_MENOR' if acceleration < -tolerance else
                                             'APERTURA_RITMO_ESTABLE')
                    current.update(rate=rate,midpoint=midpoint)
            self.samples[key]=current;self.samples.move_to_end(key)
            while len(self.samples)>self.limit:self.samples.popitem(last=False)
            return dict(result)
        except (KeyError,ValueError,TypeError,OverflowError):return None


def text_for(signal,context=None,source_time=None):
    """A failed optional context never suppresses a valid notice."""
    value=describe_bands(signal.get('band_expansion'),signal.get('price'))
    if value is None:return ''
    # Context must describe exactly this observed price/time/geometry.
    if isinstance(context,dict):
        try:
            if (source_time is not None and clock(context['source_timestamp'])==clock(source_time)
                and context.get('price')==number(signal.get('price'))
                and context.get('upper')==value['upper'] and context.get('lower')==value['lower']
                and abs(context.get('width_usd',0)-value['width_usd'])<1e-9):
                value=context
        except (KeyError,ValueError,TypeError):pass
    phases={'SIN_MUESTRAS':'todavía no se puede medir si se abren más rápido o más lento',
            'ABRIENDO':'se están separando',
            'APERTURA_ACELERANDO':'se están separando cada vez más rápido',
            'APERTURA_A_RITMO_MENOR':'siguen separándose, pero más despacio',
            'APERTURA_RITMO_ESTABLE':'se siguen separando al mismo ritmo',
            'ESTRECHANDOSE':'se están acercando',
            'ESTABLE':'la separación se mantiene',
            'AUMENTA_ANCHO_UNA_BANDA_RETROCEDE':'aumenta la separación, pero una banda retrocede'}
    return ' · Bandas: '+phases.get(value.get('phase'),phases['SIN_MUESTRAS'])
