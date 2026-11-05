"""Compact REAL won/lost history. No execution controls or broker requests."""
from datetime import datetime
from decimal import Decimal
import streamlit as st

from real_operation_results import load_operation_results,ET

LABELS={'WON':'Ganada','LOST':'Perdida','FLAT':'Sin cambio','OPEN':'En curso','REVIEW':'Por revisar'}
FILTERS={'Todas':None,'Ganadas':'WON','Perdidas':'LOST','Sin cambio':'FLAT','En curso':'OPEN','Por revisar':'REVIEW'}


def _money(value):return '—' if value is None else '$'+format(Decimal(value),',.2f')
def _percent(value):return '—' if value is None else format(Decimal(value),'+.2f')+'%'
def _time(value):
    if not value:return 'Por verificar'
    try:
        stamp=datetime.fromisoformat(value)
        if stamp.tzinfo is None:return 'Por verificar'
        return stamp.astimezone(ET).strftime('%d/%m/%Y %H:%M:%S ET')
    except (ValueError,TypeError):return 'Por verificar'


def render_real_results(binding,*,go_account,go_queue):
    st.subheader('Operaciones y resultados reales')
    if binding is None:
        st.info('Selecciona tu cuenta en «Cuenta» para consultar sus operaciones reales.')
        st.button('Consultar mi cuenta',on_click=go_account,key='real_results_account',width='stretch');return
    st.caption('Solo operaciones iniciadas por JJTradeAI en la cuenta seleccionada, incluidos cierres manuales conciliados. Importes brutos, antes de comisiones y cargos.')
    st.button('Volver a la cola real',on_click=go_queue,key='real_results_back',width='stretch')
    _results(binding)


@st.fragment(run_every='5s')
def _results(binding):
    period=st.radio('Período',['Hoy','Todo el historial'],key='real_results_period',horizontal=True)
    st.button('Actualizar resultados reales',key='real_results_refresh',width='stretch')
    try:report=load_operation_results(binding,period=period)
    except Exception:
        st.error('No se pudo leer el historial real. Actualiza esta vista; no se muestra un resultado cero sin confirmar.');return
    st.metric('Resultado cerrado bruto',_money(report['gross_result']))
    cols=st.columns(3)
    for col,label,key in zip(cols,('Ganadas','Perdidas','Sin cambio'),('won','lost','flat')):
        col.metric(label,report['counts'][key])
    counts=report['counts'];rate=report['win_rate']
    st.caption('Cerradas: '+str(report['closed'])+' · En curso: '+str(counts['open'])+
        ' · Por revisar: '+str(counts['review'])+(' · Ganadas: '+format(Decimal(rate),'.1f')+'%' if rate is not None else ''))
    if counts['review']:st.warning('Las operaciones pendientes de conciliación no se incluyen en el resultado cerrado.')
    st.caption('«Hoy» usa la fecha de cierre en Nueva York. Las abiertas y pendientes de conciliación permanecen visibles. Las ventas parciales no cuentan como ganadas o perdidas hasta cerrar la operación.')
    choice=st.selectbox('Ver operaciones',list(FILTERS),key='real_results_filter')
    selected=FILTERS[choice]
    rows=[r for r in report['operations'] if selected is None or r['state']==selected]
    if not rows:st.info('No hay operaciones para este período y filtro.');return
    pages=(len(rows)+19)//20
    page=st.selectbox('Página',list(range(1,pages+1)),format_func=lambda n:str(n)+' / '+str(pages),
        key='real_results_page_'+period+'_'+choice) if pages>1 else 1
    for row in rows[(page-1)*20:page*20]:
        with st.container(border=True):
            st.write('**'+row['symbol']+' '+row['side']+' · '+LABELS[row['state']]+'**')
            if row['gross_result'] is not None:
                st.write('**'+_money(row['gross_result'])+' · '+_percent(row['return_pct'])+' bruto**')
            elif row.get('reason'):st.warning(row['reason'])
            elif row['realized_partial'] is not None:
                st.caption('Resultado realizado parcial: '+_money(row['realized_partial'])+' bruto; operación aún abierta.')
            st.caption(row['contract'])
            sizes={key:str(row[key]) if row[key] is not None else '—' for key in ('bought','sold','remaining')}
            st.write('Contratos comprados: '+sizes['bought']+' · Vendidos: '+sizes['sold']+
                ' · Restantes: '+sizes['remaining'])
            st.write('Compra media: '+_money(row['entry_average'])+' · Venta media: '+_money(row['exit_average']))
            st.caption('Compra: '+_time(row['entered_at']))
            if row['closed_at']:st.caption('Cierre: '+_time(row['closed_at']))
            if row['manual_close']:st.caption('Incluye cierre manual conciliado desde Schwab/thinkorswim.')
