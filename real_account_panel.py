"""Explicit account selection and observation. Never arms a queue or an order."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import streamlit as st
from real_account_readonly import AccountReadOnlySession

MESSAGES={
    'ACCOUNT_APP_SETUP_REQUIRED':'Falta configurar la aplicación separada de acceso a cuentas.',
    'ACCOUNT_READ_ONLY_PROFILE_REQUIRED':'La configuración de cuentas necesita revisión; solo se admite lectura.',
    'AUTHORIZATION_REQUIRED':'La aplicación de cuentas todavía no está autorizada.',
    'REAUTHORIZATION_REQUIRED':'Hay que renovar la autorización de la aplicación de cuentas.',
    'ACCOUNT_ACCESS_NOT_AUTHORIZED':'Schwab no autorizó esta consulta. Revisa el producto Accounts and Trading Production y la vinculación.',
    'RATE_LIMITED':'Schwab pide esperar antes de consultar otra vez.',
    'TRANSPORT_FAILURE':'No se pudo contactar con Schwab. Puedes volver a consultar.',
    'ACCOUNT_SELECTION_REQUIRED':'Selecciona una cuenta para consultar.',
    'SELECTED_ACCOUNT_NOT_LINKED':'La cuenta elegida ya no aparece vinculada. Actualiza la lista de cuentas.',
    'ACCOUNT_IDENTITY_MISMATCH':'La identidad de la cuenta no coincide. Lectura detenida.',
    'ACCOUNT_RESPONSE_INVALID':'Schwab devolvió datos que no se pudieron verificar.',
    'ACCOUNT_READ_UNAVAILABLE':'No se pudo verificar la lectura de la cuenta.'}


def _stamp(value):
    try:return datetime.fromisoformat(value).astimezone(ZoneInfo('America/New_York')).strftime('%d/%m/%Y %H:%M:%S ET')
    except (ValueError,TypeError):return 'sin comprobar'


def _read_selected_account(reader,reference):
    """One user action verifies and shares the same account with the REAL host."""
    st.session_state.pop('real_account_connection_error',None)
    if reference is None:return
    try:
        result=reader.load_snapshot(reference)
        if not result or result.get('state')!='ACCOUNT_READABLE' or result.get('reference')!=reference:
            return
        from real_live_control import register_selected_account,RealRuntimeProxy
        context=reader.preview_context(reference)
        register_selected_account(context)
        runtime=st.session_state.get('real_execution_runtime')
        if runtime is None or runtime.binding!=context.binding:
            st.session_state['real_execution_runtime']=RealRuntimeProxy(context.binding)
        st.session_state['real_account_connected_binding']=context.binding
    except Exception as error:
        safe={'LIVE_ACCOUNT_HAS_PENDING_ORDERS','LIVE_ACCOUNT_HAS_POSITIONS','LIVE_ACCOUNT_HAS_ACTIVE_QUEUE'}
        code=str(error)
        st.session_state['real_account_connection_error']=code if code in safe else 'ACCOUNT_SELECTION_NOT_REGISTERED'


def _select_account():
    reference=st.session_state.get('real_account_choice')
    if reference!=st.session_state.get('real_selected_account_ref'):
        # This removes only the browser handle. The independent host keeps exits.
        st.session_state.pop('real_execution_runtime',None)
        st.session_state.pop('real_account_connected_binding',None)
    st.session_state['real_selected_account_ref']=reference
    _read_selected_account(st.session_state['real_account_reader'],reference)


def render_real_account_panel():
    st.info('Selecciona tu cuenta una sola vez. Se usará al preparar compañías y en la cola real.')
    st.caption('Consultar o seleccionar una cuenta no activa compras. Las compañías se activan desde «Preparar compañías».')
    if 'real_account_reader' not in st.session_state:st.session_state['real_account_reader']=AccountReadOnlySession()
    reader=st.session_state['real_account_reader']
    if st.button('Consultar conexión y cuentas',key='real_accounts_connect',width='stretch'):
        with st.spinner('Consultando cuentas en Schwab…'):
            reader.load_accounts()
            reference=st.session_state.get('real_selected_account_ref')
            if reader.inventory and reader.inventory.get('state')=='ACCOUNTS_READABLE' and reference in {
                    row['ref'] for row in reader.inventory['choices']}:
                _read_selected_account(reader,reference)
    inventory=reader.inventory
    if inventory is None:
        st.caption('Todavía no se ha consultado ninguna cuenta real.')
        return
    st.caption('Última consulta de cuentas: '+_stamp(inventory['checked_at']))
    if inventory['state']!='ACCOUNTS_READABLE':
        st.warning(MESSAGES.get(inventory['state'],MESSAGES['ACCOUNT_READ_UNAVAILABLE']))
        return
    choices={row['ref']:row['label'] for row in inventory['choices']}
    if not choices:
        st.warning('Schwab no devolvió cuentas vinculadas.');return
    if st.session_state.get('real_account_choice') not in choices:
        saved=st.session_state.get('real_selected_account_ref')
        st.session_state['real_account_choice']=saved if saved in choices else None
    reference=st.selectbox('Cuenta que quieres consultar',[None,*choices],key='real_account_choice',
        format_func=lambda ref:'Selecciona tu cuenta' if ref is None else choices[ref],on_change=_select_account)
    st.session_state['real_selected_account_ref']=reference
    error=st.session_state.get('real_account_connection_error')
    if error:
        blocked={'LIVE_ACCOUNT_HAS_PENDING_ORDERS','LIVE_ACCOUNT_HAS_POSITIONS','LIVE_ACCOUNT_HAS_ACTIVE_QUEUE'}
        st.warning('No se cambió la cuenta del ejecutor: la cuenta anterior tiene una cola, orden o posición pendiente.'
            if error in blocked else 'No se pudo conservar la selección para la cola real. Pulsa «Consultar conexión y cuentas» para volver a comprobarla.')
    result=reader.snapshot
    if not result or result.get('reference')!=reference:return
    if result['state']!='ACCOUNT_READABLE':
        st.warning(MESSAGES.get(result['state'],MESSAGES['ACCOUNT_READ_UNAVAILABLE']));return
    st.success(result['account_label']+' · Lectura verificada')
    try:shared=reader.preparation_binding(reference)==st.session_state.get('real_account_connected_binding')
    except Exception:shared=False
    if shared:st.caption('Cuenta seleccionada para todo el proceso real. Continúa en «Preparar compañías» o «Cola real».')
    st.caption('Última lectura: '+_stamp(result['checked_at'])+' · Tipo de cuenta: '+result['account_type'])
    try:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(result['checked_at'])).total_seconds()
        if age>60:st.caption('Los saldos mostrados son de la última consulta. Pulsa «Consultar conexión y cuentas» para actualizarlos; tu selección se conserva.')
    except (ValueError,TypeError):pass
    st.markdown('**Saldos informados por Schwab**')
    if result['balances']:
        st.dataframe([{'Concepto':r['concept'],'Importe informado':r['value']} for r in result['balances']],hide_index=True,width='stretch')
    else:st.caption('La respuesta no incluyó los campos de saldo previstos.')
    st.caption('Estos importes no autorizan una compra. El ejecutor verifica efectivo liquidado y consulta la previsualización de Schwab para cada entrada.')
    closing_only=result.get('closing_only_restricted')
    if closing_only is True:
        st.warning('Schwab informa que esta cuenta está restringida a cerrar posiciones. No habilitar nuevas compras.')
    elif closing_only is False:
        st.caption('Schwab no marca restricción de solo cierre en esta lectura. Esto no confirma aprobación para opciones.')
    else:
        st.caption('La respuesta no permite verificar la restricción de solo cierre.')
    st.markdown('**Posiciones de la cuenta**')
    if result['positions']:
        st.dataframe([{'Símbolo':r['symbol'],'Tipo':r['asset_type'],'Cantidad larga':r['long_quantity'],
            'Cantidad corta':r['short_quantity'],'Precio medio':r['average_price'],'Valor informado':r['market_value']}
            for r in result['positions']],hide_index=True,width='stretch')
    elif result['positions_known']:st.caption('Schwab devolvió una lista de posiciones vacía.')
    else:st.caption('La respuesta no incluyó una lista de posiciones; no se interpreta como cero.')
    if result['positions_truncated']:st.caption('Se muestran las primeras 200 posiciones de '+str(result['position_count'])+' recibidas.')
    st.caption('Esta consulta no incorpora posiciones externas. La app gestiona las compras confirmadas que registra su propia cola real.')
    st.markdown('**Órdenes recibidas · últimas 24 horas**')
    if result['orders']:
        st.dataframe([{'Orden Schwab':r['order_id'],'Estado':r['status'],'Tipo':r['order_type'],
            'Símbolos':r['symbols'],'Cantidad':r['quantity'],'Ejecutados':r['filled_quantity'],'Fecha informada':r['entered_at']}
            for r in result['orders']],hide_index=True,width='stretch')
    else:st.caption('Schwab devolvió una lista vacía para el intervalo consultado.')
    if result['orders_truncated']:st.caption('Se muestran las primeras 200 de '+str(result['observed_order_count'])+' órdenes recibidas.')
