"""Observable MA methodology: crosses, session duration, roles and hour closes."""
import pandas as pd


def pair_history(fast, slow, dates):
    difference=fast-slow
    valid=difference.dropna()
    if valid.empty:
        return {'cross_at':None,'sessions_since_cross':None,'validated':False,'phase':'SIN_DATOS','crosses_last_20':0,'separation_pct':None}
    signs=valid.map(lambda value:1 if value>0 else -1 if value<0 else 0)
    nonzero=signs[signs!=0]
    transitions=nonzero[nonzero.ne(nonzero.shift()) & nonzero.shift().notna()]
    recent=signs.iloc[-20:]
    recent_nonzero=recent[recent!=0]
    crosses=int((recent_nonzero.ne(recent_nonzero.shift()) & recent_nonzero.shift().notna()).sum())
    current=int(signs.iloc[-1])
    if current==0 or transitions.empty:
        return {'cross_at':None,'sessions_since_cross':None,'validated':False,
                'phase':'ENTRELAZADAS' if current==0 else 'CRUCE_NO_OBSERVADO','crosses_last_20':crosses,
                'separation_pct':abs(float(difference.iloc[-1]))/abs(float(slow.iloc[-1]))*100 if slow.iloc[-1] else None}
    cross_index=transitions.index[-1]
    cross_at=pd.Timestamp(dates.loc[cross_index])
    observed_dates=pd.to_datetime(dates.loc[cross_index:],utc=True).dt.tz_convert('America/New_York').dt.date
    # Conservative count: complete observed session transitions since the cross.
    sessions=max(0,len(set(observed_dates))-1)
    validated=sessions>=2
    phase='EN_FORMACION' if sessions<2 else 'CORTO_PLAZO' if sessions<5 else 'MEDIANO_PLAZO' if sessions<=15 else 'LARGO_PLAZO'
    return {'cross_at':cross_at.isoformat(),'sessions_since_cross':sessions,'validated':validated,'phase':phase,
            'crosses_last_20':crosses,'separation_pct':abs(float(difference.iloc[-1]))/abs(float(slow.iloc[-1]))*100 if slow.iloc[-1] else None}


def level_role(direction, validated, value, price, side):
    if not validated:
        return 'TENDENCIA_NO_VALIDADA'
    if value==price:
        return 'EN_NIVEL'
    if direction=='ALCISTA':
        if price>value:
            return 'POSIBLE_PISO' if side=='INFERIOR' else 'APOYO_POR_DETRAS'
        return 'POSIBLE_CONTINUIDAD_ALCISTA' if side=='SUPERIOR' else 'MEDIA_POR_DETRAS'
    if direction=='BAJISTA':
        if price<value:
            return 'POSIBLE_TECHO' if side=='SUPERIOR' else 'APOYO_POR_DETRAS'
        return 'POSIBLE_CONTINUIDAD_BAJISTA' if side=='INFERIOR' else 'MEDIA_POR_DETRAS'
    return 'TENDENCIA_NO_VALIDADA'


def hour_confirmation(bar, reference):
    if reference is None or not all(key in bar for key in ('open','high','low','close')):
        return 'SIN_DATOS'
    opening,high,low,close=(float(bar[key]) for key in ('open','high','low','close'))
    if not low<=reference<=high:
        return 'SIN_CONTACTO'
    if close>opening and close>reference:
        return 'REBOTE_ALCISTA_OBSERVADO' if opening>reference else 'RUPTURA_ALCISTA_OBSERVADA'
    if close<opening and close<reference:
        return 'RECHAZO_BAJISTA_OBSERVADO' if opening<reference else 'RUPTURA_BAJISTA_OBSERVADA'
    return 'CONTACTO_SIN_CONFIRMACION'


def touch_episodes(closed, references, lookback=20):
    """Count contiguous contact episodes; not a calibrated weakening score."""
    if not {'low','high'}.issubset(closed.columns):
        return None
    contacts=((closed.low<=references)&(closed.high>=references)&references.notna()).iloc[-lookback:]
    return int((contacts & ~contacts.shift(1,fill_value=False)).sum())
