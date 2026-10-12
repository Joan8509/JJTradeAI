"""Descriptive closed-bar MA context, never an entry or notification gate."""
from functools import lru_cache
import math

import pandas as pd
from live_market import aggregate_minute_bars
from market_store import MarketBarStore

PERIODS=(20,40,100,200)


def context_from_bars(bars, *, price, side, available_at, ma_type='SMA'):
    if ma_type not in ('SMA','EMA'):
        raise ValueError('Tipo de media inválido')
    available=pd.Timestamp(available_at)
    # Filter before aggregating: future intraday values cannot enter a daily close.
    known=bars[pd.to_datetime(bars['date'],utc=True)+pd.Timedelta(minutes=1)<=available]
    if known.empty:
        return {'state':'SIN_DATOS','ma_type':ma_type,'provisional':True,'frames':[], 'nearest_ahead':None}
    datasets={tf:aggregate_minute_bars(known,tf) for tf in ('1H','1D')}
    return context_from_aggregates(datasets,price=price,side=side,available_at=available,ma_type=ma_type)


def context_from_aggregates(datasets, *, price, side, available_at, ma_type='SMA'):
    if ma_type not in ('SMA','EMA') or side not in ('SUPERIOR','INFERIOR') or not math.isfinite(price) or price<=0:
        raise ValueError('Contexto de medias inválido')
    available=pd.Timestamp(available_at)
    local_date=available.tz_convert('America/New_York').date()
    frames=[]
    levels=[]
    for timeframe in ('1H','1D'):
        data=datasets[timeframe]
        dates=pd.to_datetime(data['date'],utc=True)
        # Partial hours and the current day's daily candle are excluded.
        mask=(dates+pd.Timedelta(hours=1)<=available) if timeframe=='1H' else (dates.dt.tz_convert('America/New_York').dt.date<local_date)
        closed=data[mask].copy()
        closes=closed['close'].astype(float)
        values={}
        slopes={}
        for period in PERIODS:
            ma=closes.rolling(period,min_periods=period).mean() if ma_type=='SMA' else closes.ewm(span=period,adjust=False,min_periods=period).mean()
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
            pairs.append({'periods':[fast,slow],'direction':direction,'price_location':location,
                          'aligned':direction==('ALCISTA' if side=='SUPERIOR' else 'BAJISTA') if direction in ('ALCISTA','BAJISTA') else None})
        frames.append({'timeframe':timeframe,'closed_bars':len(closed),'last_closed_at':str(closed.iloc[-1]['date']) if len(closed) else None,
                       'averages':values,'slopes':slopes,'pairs':pairs})
    ahead=[l for l in levels if l['ahead']]
    return {'state':'DESCRIPTIVO' if levels else 'SIN_DATOS','ma_type':ma_type,'provisional':True,
            'available_at':available.isoformat(),'price':price,'frames':frames,'levels':levels,
            'nearest_ahead':min(ahead,key=lambda l:l['distance_pct']) if ahead else None,
            'complete':all(f['averages']['200'] is not None for f in frames),
            'caveat':'Calculado con barras recibidas; no certifica cobertura completa. Una media por delante no demuestra bloqueo. SMA provisional, pendiente confirmar la clase.'}


@lru_cache(maxsize=40)
def _history(database,symbol,provider,feed,hour_key):
    available=pd.Timestamp(hour_key)
    # Only closed aggregate context is cached; signal price is never cached.
    bars=MarketBarStore(database).load_frame(symbol=symbol,provider=provider,feed=feed,
        start=(available-pd.Timedelta(days=480)).to_pydatetime(),end=available.to_pydatetime())
    if bars.empty:
        return None
    return {tf:aggregate_minute_bars(bars,tf) for tf in ('1H','1D')}


def live_context(database, symbol, provider, feed, source_time, signal):
    available=pd.Timestamp(source_time)+pd.Timedelta(minutes=1)
    # Hour buckets are anchored at :30, as are the market's hourly candles.
    key=((available-pd.Timedelta(minutes=30)).floor('h')+pd.Timedelta(minutes=30)).isoformat()
    data=_history(str(database),symbol,provider,feed,key)
    if data is None:
        return {'state':'SIN_DATOS','ma_type':'SMA','provisional':True,'frames':[],'nearest_ahead':None}
    return context_from_aggregates(data,price=signal['price'],side=signal['side'],available_at=available)


def context_text(context):
    if not context or context.get('state')!='DESCRIPTIVO':
        return 'Medias Hora/Diario: contexto no disponible.'
    lines=['Medias SMA provisionales · Hora/Diario:']
    for frame in context['frames']:
        pairs=frame['pairs']
        lines.append(f"{frame['timeframe']}: orden 20/40 {pairs[0]['direction'].lower()} · 100/200 {pairs[1]['direction'].lower()}.")
    nearest=context.get('nearest_ahead')
    if nearest:
        lines.append(f"Media por delante: {nearest['timeframe']} {nearest['period']} a {nearest['value']:.2f} ({nearest['distance_pct']:.3f}%). Posible zona a revisar.")
    else:
        lines.append('Sin medias por delante entre las disponibles; no significa camino libre.')
    if not context.get('complete'):
        lines.append('Historial insuficiente para algunas medias, incluida la diaria de 200.')
    lines.append('Contexto descriptivo con barras recibidas; no confirma rebote ni ruptura.')
    return '\n'.join(lines)
