"""Compact mobile results. Viewing history cannot submit, close or cancel orders."""
from datetime import datetime,timezone
import streamlit as st

from mobile_layout import MOBILE_STYLE
from operation_results import LEDGER,NY,read_operation_results,results_for_period


@st.fragment
def render_operation_results(*,path=LEDGER,now=None,title='Operaciones y resultados',default_period='Hoy',show_manage=False):
    st.markdown(MOBILE_STYLE,unsafe_allow_html=True)
    st.markdown('## '+title)
    st.caption('Simulación local · Resultados brutos en USD, antes de comisiones.')
    period=st.radio('Período',['Hoy','Todo el historial'],index=1 if default_period=='Todo el historial' else 0,horizontal=True,key='results_period',label_visibility='collapsed')
    now=now or datetime.now(timezone.utc)
    try:
        history=read_operation_results(path,now=now)
        summary=results_for_period(history,day=now.astimezone(NY).date() if period=='Hoy' else None)
    except Exception:
        st.warning('El historial no está disponible o requiere conciliación. Vuelve a consultarlo en unos momentos.')
        return
    if not history['available']:
        st.info('Todavía no hay operaciones simuladas guardadas.');return
    st.metric('Resultado cerrado',f"${summary['gross']:+,.2f}")
    st.write(f"**Ganadas {summary['wins']}** · **Perdidas {summary['losses']}** · Sin cambio {summary['flat']} · En curso {summary['open']}")
    if show_manage and (summary['open'] or summary['pending_requests']):
        if st.button('Ver posiciones / cerrar',key='results_manage',width='stretch'):
            st.query_params.clear();st.query_params['operaciones']='1';st.rerun()
    if summary['pending_requests']:
        st.caption(f"Solicitudes pendientes de compra: {summary['pending_requests']}. Aún no cuentan como operaciones realizadas.")
    from trade_learning import render_trade_learning
    render_trade_learning(history,as_of=now)
    if not summary['entries']:
        st.info('Todavía no hay compras ejecutadas en este período.');return
    st.caption('Los cierres se agrupan por su fecha ET. Las operaciones abiertas se muestran aparte del resultado cerrado.')
    # Reuse the existing passive publication; never request market data to paint history.
    from queue_position_cards import read_card_snapshot
    cards=read_card_snapshot(now=now)
    limit=st.session_state.get('results_visible',20)
    for item in summary['entries'][:limit]:
        report=item['report'];closed=item['status']=='CLOSED'
        st.markdown(f"**{item['symbol']} · {item['side']} · {item['quantity']} {'contrato' if item['quantity']==1 else 'contratos'}**")
        if closed:
            st.write(f"Cerrada · **${report['gross_pnl']:+,.2f} ({report['gross_pct']:+.2f}%)**")
            st.caption(f"{item['closed_at'].astimezone(NY):%d/%m %H:%M} ET · Entrada ${item['entry_average']:.2f} → Salida ${report['exit_average']:.2f}")
        else:
            if report:
                st.write(f"Venta parcial · Realizado ${report['gross_pnl']:+,.2f} · Quedan {item['remaining']}")
            else:st.write(f"Abierta · {item['remaining']} contratos")
            mark=(cards.get(item['key']) or {}).get('mark')
            if mark and mark['status']=='LIVE' and mark['quantity']==item['remaining'] and mark['average_fill']==item['entry_average']:
                st.write(f"Resultado abierto estimado: ${mark['gross_pnl']:+,.2f} ({mark['gross_pct']:+.2f}%)")
            else:st.caption('Resultado abierto: esperando cotización vigente.')
            st.caption(f"{item['opened_at'].astimezone(NY):%d/%m %H:%M} ET · Entrada media ${item['entry_average']:.2f}")
        st.divider()
    if len(summary['entries'])>limit and st.button('Ver más',key='results_more'):
        st.session_state['results_visible']=limit+20;st.rerun()
    st.button('Actualizar',key='results_refresh',width='stretch')
