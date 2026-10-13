"""Descriptive closed-bar MA context, never an entry or notification gate."""
from functools import lru_cache
import math
import sqlite3

import pandas as pd
from live_market import aggregate_minute_bars
from market_store import MarketBarStore
from moving_average_rules import pair_history, level_role, hour_confirmation, touch_episodes
from bollinger_price_levels import price_levels, price_levels_text

PERIODS=(20,40,100,200)


def context_from_bars(bars, *, price, side, available_at, ma_type='SMA'):
    if ma_type not in ('SMA','EMA'):
        raise ValueError('Tipo de media inválido')
    available=pd.Timestamp(available_at)
    # Filter before aggregating: future intraday values cannot enter a daily close.
    known=bars[pd.to_datetime(bars['date'],utc=True)+pd.Timedelta(minutes=1)<=available]
    if known.empty:
        return {'state':'SIN_DATOS','ma_type':ma_type,'provisional':False,'frames':[], 'nearest_ahead':None}
    datasets={tf:aggregate_minute_bars(known,tf) for tf in ('1H','1D')}
    return context_from_aggregates(datasets,price=price,side=side,available_at=available,ma_type=ma_type)


def context_from_aggregates(datasets, *, price, side, available_at, ma_type='SMA'):
    if ma_type not in ('SMA','EMA') or side not in ('SUPERIOR','INFERIOR') or not math.isfinite(price) or price<=0:
        raise ValueError('Contexto de medias inválido')
    available=pd.Timestamp(available_at)
    local_date=available.tz_convert('America/New_York').date()
    frames=[]
    levels=[]
    hourly=datasets['1H'].copy()
    hourly=hourly[pd.to_datetime(hourly.date,utc=True)+pd.Timedelta(hours=1)<=available]
    latest_hour=hourly.iloc[-1] if len(hourly) else None
    for timeframe in ('1H','1D'):
        data=datasets[timeframe]
        dates=pd.to_datetime(data['date'],utc=True)
        # Partial hours and the current day's daily candle are excluded.
        mask=(dates+pd.Timedelta(hours=1)<=available) if timeframe=='1H' else (dates.dt.tz_convert('America/New_York').dt.date<local_date)
        closed=data[mask].copy()
        closes=closed['close'].astype(float)
        values={}
        slopes={}
        series={}
        for period in PERIODS:
            ma=closes.rolling(period,min_periods=period).mean() if ma_type=='SMA' else closes.ewm(span=period,adjust=False,min_periods=period).mean()
            series[period]=ma
            value=float(ma.iloc[-1]) if len(ma) and pd.notna(ma.iloc[-1]) else None
            previous=float(ma.iloc[-2]) if len(ma)>1 and pd.notna(ma.iloc[-2]) else None
            values[str(period)]=value
            slopes[str(period)]=value-previous if value is not None and previous is not None else None
            if value is not None and math.isfinite(value):
                ahead=value>price if side=='SUPERIOR' else value<price
                levels.append({'timeframe':timeframe,'period':period,'value':value,
                               'distance_pct':abs(value-price)/price*100,'ahead':ahead})
        pairs=[]
        for fast,slow in ((20,40),(100,200)):
            a,b=values[str(fast)],values[str(slow)]
            direction='SIN_DATOS' if a is None or b is None else 'ALCISTA' if a>b else 'BAJISTA' if a<b else 'IGUALES'
            location='SIN_DATOS' if a is None or b is None else 'POR_ENCIMA' if price>max(a,b) else 'POR_DEBAJO' if price<min(a,b) else 'ENTRE_MEDIAS'
            history=pair_history(series[fast],series[slow],closed['date'])
            pairs.append({'periods':[fast,slow],'direction':direction,'price_location':location,**history,
                          'aligned':direction==('ALCISTA' if side=='SUPERIOR' else 'BAJISTA') if direction in ('ALCISTA','BAJISTA') else None})
        for level in [l for l in levels if l['timeframe']==timeframe]:
            pair=pairs[0 if level['period'] in (20,40) else 1]
            level['role']=level_role(pair['direction'],pair['validated'],level['value'],price,side)
            level['relative_weight']=level['period']
            period=level['period']
            reference=None
            if timeframe=='1H':
                previous_ma=series[period].shift(1)
                reference=float(previous_ma.iloc[-1]) if len(previous_ma) and pd.notna(previous_ma.iloc[-1]) else None
                level['touch_episodes_last_20_hours']=touch_episodes(closed,previous_ma)
            elif latest_hour is not None:
                hour_date=pd.Timestamp(latest_hour['date']).tz_convert('America/New_York').date()
                before_hour=closed[pd.to_datetime(closed.date,utc=True).dt.tz_convert('America/New_York').dt.date<hour_date]['close'].astype(float)
                past_ma=before_hour.rolling(period,min_periods=period).mean() if ma_type=='SMA' else before_hour.ewm(span=period,adjust=False,min_periods=period).mean()
                reference=float(past_ma.iloc[-1]) if len(past_ma) and pd.notna(past_ma.iloc[-1]) else None
                level['touch_episodes_last_20_hours']=None
            level['hour_confirmation']=hour_confirmation(latest_hour,reference) if latest_hour is not None else 'SIN_DATOS'
            level['confirmation_reference']=reference
            level['confirmation_hour_at']=str(latest_hour['date']) if latest_hour is not None else None
        frames.append({'timeframe':timeframe,'closed_bars':len(closed),'last_closed_at':str(closed.iloc[-1]['date']) if len(closed) else None,
                       'averages':values,'slopes':slopes,'pairs':pairs})
    ahead=[l for l in levels if l['ahead']]
    potential_limits=[l for l in ahead if l['role'] in ('POSIBLE_PISO','POSIBLE_TECHO')]
    unknown=[l for l in ahead if l['role']=='TENDENCIA_NO_VALIDADA']
    references=price_levels(datasets['1D'],price=price,side=side,available_at=available)
    barriers=[{'label':f"SMA{level['period']} {level['timeframe']}",**level} for level in potential_limits]
    barriers.extend(level for level in references['levels'] if level['ahead'])
    return {'state':'DESCRIPTIVO' if levels or references['levels'] else 'SIN_DATOS','ma_type':ma_type,'provisional':False,
            'available_at':available.isoformat(),'price':price,'frames':frames,'levels':levels,
            'price_levels':references,
            'nearest_barrier':min(barriers,key=lambda level:level['distance_pct']) if barriers else None,
            'nearest_ahead':min(ahead,key=lambda l:l['distance_pct']) if ahead else None,
            'nearest_possible_limit':min(potential_limits,key=lambda l:l['distance_pct']) if potential_limits else None,
            'assessment':'POSIBLE_LIMITE_POR_DELANTE' if potential_limits else 'TENDENCIA_PENDIENTE' if unknown else 'SIN_LIMITE_IDENTIFICADO',
            'pending_rules':['Tolerancia de contacto','Separación saludable','Umbral de cruces para lateralidad','Debilitamiento por rebotes','Espacio mínimo'],
            'complete':all(f['averages']['200'] is not None for f in frames),
            'caveat':'Calculado con barras recibidas; no certifica cobertura completa. Una media por delante no demuestra bloqueo. SMA confirmada por Joan en TC2000.'}


@lru_cache(maxsize=40)
def _history(database,symbol,provider,feed,hour_key):
    available=pd.Timestamp(hour_key)
    # Only closed aggregate context is cached; signal price is never cached.
    bars=MarketBarStore(database).load_frame(symbol=symbol,provider=provider,feed=feed,
        start=(available-pd.Timedelta(days=480)).to_pydatetime(),end=available.to_pydatetime())
    if bars.empty:
        return None
    data={tf:aggregate_minute_bars(bars,tf) for tf in ('1H','1D')}
    local=pd.to_datetime(bars.date,utc=True).dt.tz_convert('America/New_York')
    minute_of_day=local.dt.hour*60+local.dt.minute
    regular=bars[(minute_of_day>=570) & (minute_of_day<960)].copy()
    regular['session_date']=pd.to_datetime(regular.date,utc=True).dt.tz_convert('America/New_York').dt.date.astype(str)
    data['1D'].attrs['last_minute_by_session']={key:pd.Timestamp(value).isoformat() for key,value in regular.groupby('session_date').date.max().items()}
    with sqlite3.connect(database) as db:
        sessions=db.execute('SELECT session_date,closes_at FROM market_sessions').fetchall()
    data['1D'].attrs['session_closes']=dict(sessions)
    previous=[date for date,_ in sessions if date<available.tz_convert('America/New_York').date().isoformat()]
    data['1D'].attrs['expected_previous_session']=max(previous) if previous else None
    return data


def live_context(database, symbol, provider, feed, source_time, signal, *, available_at=None):
    available=pd.Timestamp(available_at) if available_at is not None else pd.Timestamp(source_time)+pd.Timedelta(minutes=1)
    # Hour buckets are anchored at :30, as are the market's hourly candles.
    key=((available-pd.Timedelta(minutes=30)).floor('h')+pd.Timedelta(minutes=30)).isoformat()
    data=_history(str(database),symbol,provider,feed,key)
    if data is None:
        return {'state':'SIN_DATOS','ma_type':'SMA','provisional':False,'frames':[],'nearest_ahead':None}
    return context_from_aggregates(data,price=signal['price'],side=signal['side'],available_at=available)


def context_text(context):
    if not context or context.get('state')!='DESCRIPTIVO':
        return 'Medias Hora/Diario: contexto no disponible.'
    lines=['Medias SMA · Hora/Diario:']
    for frame in context['frames']:
        pairs=frame['pairs']
        lines.append(f"{frame['timeframe']}: orden 20/40 {pairs[0]['direction'].lower()} · 100/200 {pairs[1]['direction'].lower()}.")
        for pair in pairs:
            periods='/'.join(map(str,pair['periods']))
            if pair.get('validated'):
                lines.append(f"{frame['timeframe']} {periods}: {pair['sessions_since_cross']} sesiones desde el cruce, {pair['phase'].lower().replace('_',' ')}.")
            else:
                lines.append(f"{frame['timeframe']} {periods}: tendencia aún no validada desde el cruce.")
    nearest=context.get('nearest_ahead')
    if nearest:
        lines.append(f"Media por delante: {nearest['timeframe']} {nearest['period']} a {nearest['value']:.2f} ({nearest['distance_pct']:.3f}%). Posible zona a revisar.")
        roles={'POSIBLE_PISO':'posible piso','POSIBLE_TECHO':'posible techo','POSIBLE_CONTINUIDAD_ALCISTA':'posible continuidad alcista','POSIBLE_CONTINUIDAD_BAJISTA':'posible continuidad bajista','TENDENCIA_NO_VALIDADA':'papel pendiente: tendencia no validada'}
        lines.append('Lectura: '+roles.get(nearest.get('role'),'revisar contexto')+'.')
    else:
        lines.append('Sin medias por delante entre las disponibles; no significa camino libre.')
    limit=context.get('nearest_possible_limit')
    if limit and (not nearest or (limit['timeframe'],limit['period'])!=(nearest['timeframe'],nearest['period'])):
        lines.append(f"Otro posible límite: {limit['timeframe']} SMA{limit['period']} a {limit['distance_pct']:.3f}%.")
    if nearest and nearest.get('hour_confirmation') not in (None,'SIN_DATOS','SIN_CONTACTO'):
        stamp=pd.Timestamp(nearest['confirmation_hour_at']).tz_convert('America/New_York')
        lines.append(f"Última vela de Hora cerrada ({stamp:%m/%d %H:%M} ET): {nearest['hour_confirmation'].lower().replace('_',' ')}.")
    if not context.get('complete'):
        lines.append('Historial insuficiente para algunas medias, incluida la diaria de 200.')
    if context.get('price_levels'):
        lines.append(price_levels_text(context['price_levels']))
    barrier=context.get('nearest_barrier')
    if barrier:
        lines.append(f"Próxima barrera candidata: {barrier['label']} a {barrier['distance_pct']:.3f}%. No garantiza rechazo.")
    lines.append('Contexto descriptivo con barras recibidas; no confirma rebote ni ruptura.')
    return '\n'.join(lines)
