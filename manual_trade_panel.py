"""Mobile signal review. No broker connection, fabricated quotes or order submission."""
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore
from price_ranges import load_option_price_ranges
from watchlist_config import load_watchlist


def itm_candidates(chain, *, underlying_price, underlying_stamp, side, as_of):
    """Read-only contract eligibility. Real quotes must be refreshed before any order."""
    if side not in ('CALL','PUT') or not math.isfinite(underlying_price) or underlying_price<=0:
        return []
    if not timedelta(0)<=as_of-underlying_stamp<=timedelta(seconds=30):
        return []
    today=as_of.astimezone(ZoneInfo('America/New_York')).date()
    result=[]
    for quote in chain:
        if quote.option_type.upper()!=side or quote.expiration<today or quote.feed!='opra':
            continue
        if quote.quote_timestamp is None or not timedelta(0)<=as_of-quote.quote_timestamp<=timedelta(seconds=30):
            continue
        if not all(math.isfinite(value) for value in (quote.strike,quote.bid,quote.ask)):
            continue
        if quote.bid<=0 or quote.ask<quote.bid or min(quote.bid_size,quote.ask_size)<=0:
            continue
        if side=='CALL' and quote.strike>=underlying_price or side=='PUT' and quote.strike<=underlying_price:
            continue
        result.append(quote)
    return sorted(result,key=lambda q:(q.expiration,abs(q.strike-underlying_price)))


@st.fragment(run_every='15s')
def render_manual_trade(symbol, side='CALL', signal_time=None):
    if symbol not in load_watchlist()['symbols']:
        st.error('Esta compañía no pertenece al radar.')
        return
    st.subheader(symbol+' · Operación manual')
    if signal_time:
        try:
            stamp=datetime.fromisoformat(signal_time).astimezone(ZoneInfo('America/New_York'))
            st.caption(f'Aviso recibido para la barra del {stamp:%m/%d %I:%M %p} ET')
        except ValueError:
            pass
    now=datetime.now(timezone.utc)
    bars=MarketBarStore().load_frame(symbol=symbol,provider='ALPACA',feed='iex',
        start=now-timedelta(days=7),end=now-timedelta(minutes=1))
    if bars.empty:
        st.info('Esperando datos de esta compañía.')
    else:
        frame=prepare_market_frame(aggregate_minute_bars(bars,'15m')).tail(40)
        data=frame[['date','open','high','low','close','bollinger_upper','bollinger_lower','bollinger_mid']].copy()
        data['date']=pd.to_datetime(data.date,utc=True).map(lambda v:v.isoformat())
        data=data.where(pd.notnull(data),None)
        x={'field':'date','type':'temporal','axis':{'title':None}}
        y=lambda field:{'field':field,'type':'quantitative','scale':{'zero':False},'axis':{'title':None}}
        color={'condition':{'test':'datum.close >= datum.open','value':'#34d399'},'value':'#fb7185'}
        layers=[{'mark':'rule','encoding':{'x':x,'y':y('low'),'y2':{'field':'high'},'color':color}},
            {'mark':{'type':'bar','size':6},'encoding':{'x':x,'y':y('open'),'y2':{'field':'close'},'color':color,
                'tooltip':[{'field':f,'type':'quantitative'} for f in ('open','high','low','close')]}}]
        for field in ('bollinger_upper','bollinger_lower','bollinger_mid'):
            layers.append({'mark':{'type':'line','color':'#70a9ff','opacity':.6,'strokeWidth':1},
                'encoding':{'x':x,'y':y(field)}})
        st.vega_lite_chart(data,{'height':280,'layer':layers},width='stretch')
        latest=pd.Timestamp(bars.iloc[-1].date).to_pydatetime()
        st.caption(f"Acción: ${float(bars.iloc[-1].close):.2f} · Última barra: {latest.astimezone(ZoneInfo('America/New_York')):%I:%M %p ET}")
        if now-latest>timedelta(minutes=3):
            st.info('El gráfico muestra historial; no hay un precio reciente para preparar una compra.')
    selected=st.radio('Tipo de opción',['CALL','PUT'],index=0 if side=='CALL' else 1,horizontal=True,key='manual_option_side_'+symbol)
    reference=load_option_price_ranges().get(symbol)
    if reference:
        st.caption(f"Referencia de tu listado: ${reference['optimal_low']:g} – ${reference['optimal_high']:g}. No es una cotización del contrato.")
    st.info('Falta conectar Schwab para cargar contratos in the money, bid/ask actualizados y tu posición.')
    columns=st.columns(2)
    columns[0].button('Comprar '+selected,disabled=True,key='manual_buy_'+symbol)
    columns[1].button('Vender posición',disabled=True,key='manual_sell_'+symbol)
