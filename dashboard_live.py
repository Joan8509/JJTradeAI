"""Small live strategy view, using the existing fast detector and its exact gates."""
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import json,sqlite3,time
from zoneinfo import ZoneInfo
import streamlit as st

from market_store import DEFAULT_MARKET_DATABASE
from manual_trade_service import current_manual_signal,ManualDataError
from watchlist_config import load_watchlist

NY=ZoneInfo('America/New_York')


def read_live_strategies(database=DEFAULT_MARKET_DATABASE,*,now=None,symbols=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('AWARE_CLOCK_REQUIRED')
    symbols=tuple(symbols if symbols is not None else load_watchlist()['symbols'])
    begun=time.monotonic()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        db.set_progress_handler(lambda:time.monotonic()-begun>2,1000)
        session=db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',(now.astimezone(NY).date().isoformat(),)).fetchone()
        runtime=db.execute('SELECT state,heartbeat,feed,symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()
        rows=db.execute('SELECT symbol,payload_json FROM bollinger_tick_latest LIMIT 257').fetchall()
        if len(rows)>256:raise ValueError('LIVE_VIEW_LIMIT')
    runtime=dict(zip(('state','heartbeat','feed','symbols'),runtime)) if runtime else {}
    if runtime:runtime['symbols']=json.loads(runtime['symbols'])
    ticks={symbol:json.loads(raw) for symbol,raw in rows};entries=[];recent=0;reasons=[]
    for symbol in symbols:
        try:
            tick=current_manual_signal(dict(session=session,runtime=runtime,tick=ticks.get(symbol)),symbol,now)
            entries.append(tick);recent+=1
        except ManualDataError as error:
            reason=str(error);reasons.append(reason)
            if reason=='NO_CURRENT_SIGNAL':recent+=1
    state='LIVE' if entries else 'OUTSIDE_SESSION' if not session or 'OUTSIDE_OFFICIAL_SESSION' in reasons else 'WAITING_DATA' if not recent else 'NO_SIGNAL'
    return dict(state=state,entries=sorted(entries,key=lambda r:r['symbol']),recent=recent,total=len(symbols))


@st.fragment(run_every='3s')
def render_live_strategies():
    st.markdown('## Estrategia en Vivo')
    st.caption('Solo compañías donde se cumple la estrategia con datos vigentes.')
    now=datetime.now(timezone.utc)
    try:view=read_live_strategies(now=now)
    except Exception:
        st.warning('No se pudieron comprobar las señales actuales.');return
    if view['state']=='OUTSIDE_SESSION':st.info('Sesión regular cerrada. Aquí aparecerán las señales vigentes al abrir el mercado.')
    elif view['state']=='WAITING_DATA':st.info('Esperando datos recientes del mercado.')
    elif not view['entries']:st.info('En este momento no hay compañías con la estrategia vigente.')
    for tick in view['entries']:
        signal=tick['signal'];side='CALL' if signal['side']=='SUPERIOR' else 'PUT'
        with st.container(border=True):
            st.markdown(f"**{tick['symbol']} · {side}**")
            st.write(('Salida superior' if side=='CALL' else 'Salida inferior')+f" · Precio ${signal['price']:.2f}")
            candle=datetime.fromisoformat(signal['candle']).astimezone(NY)
            stamp=datetime.fromisoformat(tick['source_timestamp'].replace('Z','+00:00')).astimezone(NY)
            st.caption(f'Vela {candle:%H:%M} ET · Último precio {stamp:%H:%M:%S} ET')
    if view['state']!='OUTSIDE_SESSION':st.caption(f"Datos recientes: {view['recent']} de {view['total']} compañías. Una señal puede retraerse.")
