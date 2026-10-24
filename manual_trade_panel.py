"""Mobile read-only Schwab review. No fabricated quotes or order submission."""
from datetime import datetime, timedelta, timezone
import sqlite3
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE
from bounded_market_history import load_history
from price_ranges import optimal_option_premium
from watchlist_config import load_watchlist


from option_contract_selection import itm_candidates, MAX_ENTRY_SPREAD
from option_position_sizing import manual_entry_cost
from option_exit_plan import PROFIT_PERCENT_CHOICES, load_global_exit_policy
from manual_trade_service import (ManualDataError, owner_market_data, read_manual_state,
    current_manual_signal, manual_candidates)


def render_quantity_review(symbol, side, *, quote=None, fee_per_contract=None, as_of=None, observed_practice=False):
    """Quantity/cost preview only; never confirms or dispatches an order."""
    now=as_of or datetime.now(timezone.utc)
    current=(quote is not None and quote.underlying_symbol==symbol and quote.option_type==side
        and quote.quote_timestamp is not None and quote.quote_timestamp.tzinfo is not None
        and timedelta(0)<=now-quote.quote_timestamp<=timedelta(seconds=30))
    key='manual_quantity_'+symbol+'_'+side+'_'+(quote.symbol if quote is not None else 'waiting')
    quantity=st.number_input('Cantidad de contratos que quieres comprar',
        min_value=1,value=None,step=1,key=key,disabled=not current,
        placeholder='Indica la cantidad después de revisar el contrato')
    if not current:
        st.info('Falta seleccionar un contrato con bid/ask vigentes para revisar la cantidad y el costo.')
        return None
    st.caption(f'{quote.symbol} · Strike {quote.strike:g} · Vence {quote.expiration:%Y-%m-%d}')
    st.write(f'Bid: ${quote.bid:g} · Ask: ${quote.ask:g}')
    if quantity is None:
        return None
    try:
        premium=manual_entry_cost(quote.ask,quantity,0)  #Premium only, not zero assumed fees.
        st.metric('Prima por la cantidad elegida',f'${premium:,.2f} USD')
        if fee_per_contract is None:
            st.info('Costos no verificados. Solo importe de primas y resultado bruto en el ensayo.' if observed_practice
                    else 'Faltan los costos de entrada para completar el total estimado.')
            if not observed_practice:
                return None
        total=premium if observed_practice else manual_entry_cost(quote.ask,quantity,fee_per_contract)
    except ValueError:
        st.warning('La cantidad o los costos no son válidos; entrada bloqueada.')
        return None
    st.metric('Total estimado de entrada',f'${total:,.2f} USD')
    st.caption('Revisa cantidad, ask y total antes de confirmar. La cotización puede cambiar.')
    return {'quantity':quantity,'ask':quote.ask,'entry_cost':total,'contract_symbol':quote.symbol}


def render_exit_target_review(symbol, side, contract_symbol, signal_candle):
    """Draft only. A selected return never arms an exit or confirms a purchase."""
    st.markdown('#### Plan de salida')
    try:
        exit_policy=load_global_exit_policy()
    except ValueError:
        st.warning('No se pudo verificar la política global de salidas. La operación permanece bloqueada.')
        return None
    st.caption(f'Stop loss global: {exit_policy.stop_loss_pct}% de la prima realmente ejecutada. '
        'Se evalúa con el Bid del contrato, antes de comisiones. Cierre manual conservado en todas las modalidades.')
    target=st.selectbox('Objetivo de ganancia del contrato',(*PROFIT_PERCENT_CHOICES,'MANUAL'),
        index=None,key='manual_profit_'+symbol+'_'+side+'_'+contract_symbol+'_'+signal_candle,
        format_func=lambda value:'Cierre manual' if value=='MANUAL' else f'{value}% bruto',
        placeholder='Elige el objetivo de esta operación')
    st.caption('El objetivo se calcula sobre el precio realmente pagado por el contrato. '
        'Las comisiones reducen la ganancia neta; alcanzar el umbral no garantiza la venta.')
    if target=='MANUAL':
        st.caption('Tú decides cuándo cerrar. No hay un objetivo automático de ganancia; '
            f'el stop loss global del {exit_policy.stop_loss_pct}% se mantiene en el plan de salida.')
    st.info('Plan preparado para simulación. Esta selección es una revisión; '
        'no hay salidas ni compras activadas.')
    return target


@st.cache_data(ttl=60,max_entries=64,show_spinner=False)
def _manual_chart_bars(database,symbol):
    now=datetime.now(timezone.utc)
    return load_history(database,symbol=symbol,provider='ALPACA',feed='iex',
        start=now-timedelta(days=7),end=now-timedelta(minutes=1))


@st.cache_resource(show_spinner=False)
def _shared_market_data():
    return owner_market_data()


_MESSAGES={
    'OUTSIDE_OFFICIAL_SESSION':'Fuera de la sesión regular. El historial no autoriza una entrada.',
    'COLLECTOR_NOT_CURRENT':'Esperando conexión y precios recientes del colector.',
    'NO_CURRENT_SIGNAL':'No hay señal actual. Abre un aviso entregado para preparar la entrada manual por ese aviso.',
    'DELIVERED_ALERT_REQUIRED':'Falta verificar un aviso entregado de esta compañía y dirección.',
    'ALERT_WINDOW_ENDED':'Terminó la vela de este aviso. Abre el aviso actual.',
    'ALERT_REFERENCE_QUARANTINED':'Hay una corrección de los datos de referencia que requiere revisión.',
    'SIGNAL_STATE_UNAVAILABLE':'No se pudo comprobar el estado actual de la señal.',
    'SIGNAL_DIRECTION_CHANGED':'La dirección actual cambió. Revisa la señal vigente en el radar.',
    'PRIVATE_MARKET_CONFIG_UNAVAILABLE':'La conexión privada de datos de Schwab no está disponible bajo esta identidad.',
    'AUTHORIZATION_REQUIRED':'Falta autorizar la conexión de datos de Schwab en la consola de la VPS.',
    'REAUTHORIZATION_REQUIRED':'Schwab requiere renovar la autorización en la consola de la VPS.',
    'RATE_LIMITED':'Schwab solicitó una pausa; se respetará antes de consultar de nuevo.',
    'MARKET_DATA_COOLDOWN':'Esperando antes de volver a consultar Schwab.',
    'NO_ELIGIBLE_EXPIRATION_OR_RANGE':'No hay vencimiento o rango válido para preparar esta entrada.',
    'OPTION_CHAIN_NOT_CURRENT':'Los contratos necesitan datos actualizados.',
}


@st.fragment(run_every='1s')
def render_live_manual_ticket(symbol,side,alert_candle=None):
    """Live read-only route shared by Telegram and the dashboard. No order IO."""
    try:
        state=read_manual_state(DEFAULT_MARKET_DATABASE,symbol,datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date())
        if alert_candle is not None:
            from manual_execution_panel import shared_manual_workflow
            from manual_alert_entry import validate_reference,alert_candidates
            workflow=shared_manual_workflow()
            if workflow is None or not callable(getattr(workflow,'alert_reader',None)):
                raise ManualDataError('DELIVERED_ALERT_REQUIRED')
            reference=workflow.alert_reader(symbol,side,alert_candle)
            validate_reference(reference,workflow._controls(state),datetime.now(timezone.utc))
        else:
            tick=current_manual_signal(state,symbol,datetime.now(timezone.utc))
            actual='CALL' if tick['signal']['side']=='SUPERIOR' else 'PUT'
            if side!=actual:raise ManualDataError('SIGNAL_DIRECTION_CHANGED')
        service=_shared_market_data()
        market=service.get_chain(symbol,side,datetime.now(timezone.utc))
        #Release SQL before REST; re-read after lookup, then take the clock.
        state=read_manual_state(DEFAULT_MARKET_DATABASE,symbol,datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date())
        now=datetime.now(timezone.utc)
        if alert_candle is not None:
            reference=workflow.alert_reader(symbol,side,alert_candle)
            _,expiry,contracts=alert_candidates(reference,state,market,now,workflow._controls(state))
            ticket_candle=alert_candle;ticket_price=market.chain.underlying_price
        else:
            tick,expiry,contracts=manual_candidates(state,market,symbol,side,now)
            ticket_candle=tick['signal']['candle'];ticket_price=tick['signal']['price']
    except (ManualDataError,ValueError,RuntimeError) as error:
        st.info(_MESSAGES.get(str(error),'No se pudieron verificar los contratos de Schwab. La entrada permanece bloqueada.'))
        st.button('Comprar '+side,disabled=True,key='manual_buy_'+symbol)
        return
    st.success(symbol+' · '+side+(' · Entrada manual por aviso detectado' if alert_candle else ' · Estrategia vigente'))
    st.caption(f"Precio actual de referencia ({'Schwab' if alert_candle else 'IEX'}): ${ticket_price:.2f} · "
        f"Vela: {datetime.fromisoformat(ticket_candle).astimezone(ZoneInfo('America/New_York')):%H:%M} ET")
    st.caption(f'Vencimiento elegido: {expiry:%Y-%m-%d} · ITM u OTM hasta 5.º strike · Ask dentro del óptimo · Spread máximo ${MAX_ENTRY_SPREAD:.2f}')
    low,high=optimal_option_premium(symbol)
    st.caption(f'Prima óptima de la opción: ${low:.2f} – ${high:.2f} USD')
    if not contracts:
        st.info('No hay contratos con cotizaciones vigentes que cumplan todas las reglas de selección.')
        st.button('Comprar '+side,disabled=True,key='manual_buy_'+symbol)
        return
    by_symbol={c.snapshot.symbol:c for c in contracts}
    key='manual_contract_'+symbol+'_'+side+'_'+ticket_candle
    if key in st.session_state and st.session_state[key] not in by_symbol:
        del st.session_state[key]
    selected=st.selectbox('Contrato que quieres revisar',list(by_symbol),index=None,key=key,
        placeholder='Selecciona un contrato ITM u OTM (hasta 5.º)',format_func=lambda code:
            f"{'ITM' if (by_symbol[code].snapshot.strike<ticket_price if side=='CALL' else by_symbol[code].snapshot.strike>ticket_price) else 'OTM'} · Strike {by_symbol[code].snapshot.strike:g} · Ask ${by_symbol[code].snapshot.ask:g} · "
            f"Bid ${by_symbol[code].snapshot.bid:g} · {code}")
    if selected is not None:
        contract=by_symbol[selected]
        from manual_execution_panel import shared_manual_workflow,render_entry_actions
        from schwab_simulation import practice_policy
        workflow=shared_manual_workflow()
        observed=workflow is not None and practice_policy(workflow.engine.policy)
        quantity_review=render_quantity_review(symbol,side,quote=contract.snapshot,
            fee_per_contract=service.fee_per_contract,as_of=now,observed_practice=observed)
        target=render_exit_target_review(symbol,side,contract.snapshot.symbol,ticket_candle)
        render_entry_actions(symbol,side,contract,quantity_review,target,ticket_candle,workflow=workflow)
        if contract.price_increment is None:
            st.caption('Ensayo a precios observados; incremento bursátil no verificado para órdenes reales.' if observed
                       else 'Falta verificar el incremento de precio permitido para este contrato antes de operar.')
    st.info('Revisión de contratos y cantidad. Las órdenes reales siguen deshabilitadas.')
    st.button('Comprar '+side,disabled=True,key='manual_buy_'+symbol)


@st.fragment(run_every='30s')
def _render_manual_chart(symbol,*,chart_key=None):
    st.markdown('#### Gráfico de referencia de la acción')
    now=datetime.now(timezone.utc)
    try:
        bars=_manual_chart_bars(str(DEFAULT_MARKET_DATABASE),symbol)
    except (sqlite3.Error,OSError,ValueError):
        st.info('El gráfico de referencia no está disponible ahora.')
        return
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
        st.vega_lite_chart(data,{'height':280,'layer':layers},width='stretch',key=chart_key)
        latest=pd.Timestamp(bars.iloc[-1].date).to_pydatetime()
        st.caption(f"Acción: ${float(bars.iloc[-1].close):.2f} · Última barra: {latest.astimezone(ZoneInfo('America/New_York')):%I:%M %p ET}")
        if now-latest>timedelta(minutes=3):
            st.info('El gráfico muestra historial. La ficha superior comprueba la señal y los precios vigentes por separado.')


def render_manual_trade(symbol, side='CALL', signal_time=None):
    if symbol not in load_watchlist()['symbols'] or side not in ('CALL','PUT'):
        st.error('La compañía o dirección no pertenece a una propuesta válida del radar.')
        return
    st.subheader(symbol+' · Operación manual')
    alert_candle=None
    if signal_time:
        try:
            stamp=datetime.fromisoformat(signal_time).astimezone(ZoneInfo('America/New_York'))
            alert_candle=stamp.replace(minute=15*(stamp.minute//15),second=0,microsecond=0).astimezone(timezone.utc).isoformat()
            st.caption(f'Aviso original: {stamp:%m/%d %I:%M:%S %p} ET. La entrada manual usa el aviso verificado y cotizaciones actuales.')
        except ValueError:
            st.caption('Se comprueba la señal actual; la fecha del enlace no autoriza una compra.')
    if alert_candle:render_live_manual_ticket(symbol,side,alert_candle=alert_candle)
    else:render_live_manual_ticket(symbol,side)
    from manual_execution_panel import render_manual_positions
    render_manual_positions()
    _render_manual_chart(symbol)
