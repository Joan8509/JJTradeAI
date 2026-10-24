"""Mobile position marks and charts. No order, broker or notification transport."""
from zoneinfo import ZoneInfo
from decimal import Decimal
import streamlit as st

from position_monitor import position_mark,append_bid_observation


def _money(value):
    return '—' if value is None else f'${value:,.2f}'


def _premium(value):
    """Unit prices can be fractional after partial fills; flag any rounding."""
    if value is None:
        return '—'
    formatted=f'{value:,.6f}'
    whole,fraction=formatted.split('.')
    shown='$'+whole+'.'+fraction.rstrip('0').ljust(2,'0')
    return ('≈' if Decimal(formatted.replace(',',''))!=value else '')+shown


def render_empty_position_monitor():
    """Visible layout without inventing a position, price or P&L."""
    a,b=st.columns(2)
    a.metric('Prima media ejecutada','—');b.metric('Bid del contrato','—')
    a,b=st.columns(2)
    a.metric('Ganancia / pérdida bruta estimada','—');b.metric('Valor estimado al Bid','—')
    a,b=st.columns(2)
    a.metric('Objetivo de venta','—');b.metric('Umbral del stop','—')
    st.caption('Las métricas y el gráfico del contrato aparecerán al tener una posición simulada ejecutada y datos aptos.')


def render_position_monitor(workflow,position):
    key='position_view_'+position['entry_client_key']
    unavailable=False
    try:
        market=workflow.position_market(position['contract'])
        st.session_state[key+'_quote']=market
    except Exception:
        market=st.session_state.get(key+'_quote');unavailable=True
    try:
        mark=position_mark(position,market,now=workflow.clock(),unavailable=unavailable)
    except (ValueError,TypeError,KeyError):
        st.warning('No se pudo verificar el resultado de esta posición. El cierre conserva sus comprobaciones.');return
    live=mark['status']=='LIVE'
    a,b=st.columns(2)
    a.metric('Prima media ejecutada',_premium(mark['average_fill']))
    b.metric('Bid actual' if live else 'Último Bid · no vigente',_premium(mark['bid']))
    if mark['ask'] is not None:
        st.caption('Ask: '+_premium(mark['ask'])+' · Spread: '+_premium(mark['ask']-mark['bid']))
    if mark['quote_timestamp'] is not None:
        stamp=mark['quote_timestamp'].astimezone(ZoneInfo('America/New_York'))
        age=mark['age_seconds']
        st.caption(f'OPRA · Cotización: {stamp:%m/%d %H:%M:%S} ET · '
            +(f'Antigüedad: {age:.1f} s' if age>=0 else 'Reloj de cotización futuro: dato no válido'))
    notices={
        'CLOSED':'Mercado cerrado. Los precios anteriores no representan un resultado actual.',
        'STALE':'Cotización anterior: esperando datos vigentes para actualizar el resultado.',
        'FUTURE':'Cotización con fecha futura: resultado actual no disponible.',
        'INVALID':'Cotización no válida: resultado actual no disponible.',
        'UNAVAILABLE':'Actualización no disponible. Las observaciones anteriores no autorizan un cierre.'}
    if not live:
        st.info(notices[mark['status']])
    a,b=st.columns(2)
    a.metric('Ganancia / pérdida bruta estimada',_money(mark['gross_pnl']),
        delta=None if not live else f"{mark['gross_pct']:+.2f}%",delta_color='normal')
    b.metric('Valor estimado al Bid',_money(mark['value']))
    st.caption('Resultado de los contratos que siguen abiertos, antes de comisiones. '
        'Se calcula con el Bid; el precio final de venta puede variar.')
    if mark['net_estimate'] is not None:
        st.metric('Resultado neto estimado',_money(mark['net_estimate']),delta=f"{mark['net_pct']:+.2f}%")
        st.caption('Descuenta costos de entrada ejecutados y costos estimados de salida; aún no es un resultado realizado.')
    elif live:
        st.caption('Resultado neto pendiente: faltan costos verificados. No se asumen comisiones cero.')
    a,b=st.columns(2)
    a.metric('Objetivo de venta',_premium(mark['target']) if mark['target'] is not None else 'Cierre manual')
    b.metric('Umbral del stop',_premium(mark['stop']))
    st.caption('Objetivo y stop sobre la prima ejecutada. ≈ indica redondeo visual; el cálculo conserva la precisión. '
        'Son umbrales; no garantizan precio de ejecución.')
    if mark['underlying_price'] is not None:
        st.metric('Acción · referencia Schwab',_money(mark['underlying_price']))
        stamp=mark['underlying_timestamp'].astimezone(ZoneInfo('America/New_York'))
        st.caption(f"Referencia {'reciente' if mark['underlying_current'] else 'anterior'} del proveedor · {stamp:%m/%d %H:%M:%S} ET. "
            'El resultado de la opción se calcula por separado con su Bid.')
    points=append_bid_observation(st.session_state.get(key+'_history',[]),mark)
    st.session_state[key+'_history']=points
    if points:
        rules=[{'level':float(mark['average_fill']),'name':'Prima ejecutada'},
               {'level':float(mark['stop']),'name':'Stop'}]
        if mark['target'] is not None:
            rules.append({'level':float(mark['target']),'name':'Objetivo'})
        st.vega_lite_chart(spec={'height':210,'data':{'values':points},'layer':[
            {'mark':{'type':'line','point':True,'color':'#38bdf8'},'encoding':{
                'x':{'field':'time','type':'temporal','axis':{'title':None}},
                'y':{'field':'bid','type':'quantitative','scale':{'zero':False},'axis':{'title':'Bid USD'}},
                'detail':{'field':'segment','type':'nominal'},
                'tooltip':[{'field':'time','type':'temporal'},{'field':'bid','type':'quantitative'}]}},
            {'data':{'values':rules},'mark':{'type':'rule','strokeDash':[5,4]},'encoding':{
                'y':{'field':'level','type':'quantitative'},'color':{'field':'name','type':'nominal','title':None},
                'tooltip':[{'field':'name'},{'field':'level','type':'quantitative'}]}}
            ]},width='stretch',key=key+'_bid_chart')
        st.caption('Bid observado desde que abriste esta vista. Niveles actuales; huecos de más de 30 s sin unir. '
            'Hasta 300 observaciones en esta sesión, sin reconstruir precios anteriores.')
    else:
        st.caption('El gráfico del contrato comenzará al recibir cotizaciones vigentes.')
    if st.checkbox('Mostrar gráfico de la acción',key=key+'_stock_chart_visible'):
        from manual_trade_panel import _render_manual_chart
        _render_manual_chart.__wrapped__(position['symbol'],chart_key=key+'_stock_chart')
