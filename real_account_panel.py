"""Manual account observation only. This page never arms a simulation or order."""
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import streamlit as st
from real_account_readonly import AccountReadOnlySession,ACCOUNT_CALLBACK

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


def render_real_account_panel():
    st.info('Consulta de cuenta · Solo lectura. El envío de órdenes reales no está habilitado.')
    st.caption('Esta pantalla no modifica la cola ni las operaciones de simulación. Consulta solo cuando pulses los botones.')
    if 'real_account_reader' not in st.session_state:st.session_state['real_account_reader']=AccountReadOnlySession()
    reader=st.session_state['real_account_reader']
    if st.button('Consultar conexión y cuentas',key='real_accounts_connect',width='stretch'):
        with st.spinner('Consultando cuentas en Schwab…'):reader.load_accounts()
    inventory=reader.inventory
    if inventory is None:
        st.caption('Todavía no se ha consultado ninguna cuenta real.')
        _setup()
        return
    st.caption('Última consulta de cuentas: '+_stamp(inventory['checked_at']))
    if inventory['state']!='ACCOUNTS_READABLE':
        st.warning(MESSAGES.get(inventory['state'],MESSAGES['ACCOUNT_READ_UNAVAILABLE']))
        _setup();return
    choices={row['ref']:row['label'] for row in inventory['choices']}
    if not choices:
        st.warning('Schwab no devolvió cuentas vinculadas.');return
    if st.session_state.get('real_account_choice') not in choices:st.session_state['real_account_choice']=None
    reference=st.selectbox('Cuenta que quieres consultar',[None,*choices],key='real_account_choice',
        format_func=lambda ref:'Selecciona tu cuenta' if ref is None else choices[ref])
    if st.button('Consultar esta cuenta',key='real_account_read',disabled=reference is None,width='stretch'):
        with st.spinner('Leyendo saldos, posiciones y órdenes…'):reader.load_snapshot(reference)
    result=reader.snapshot
    if not result or result.get('reference')!=reference:return
    if result['state']!='ACCOUNT_READABLE':
        st.warning(MESSAGES.get(result['state'],MESSAGES['ACCOUNT_READ_UNAVAILABLE']));return
    st.success(result['account_label']+' · Lectura verificada')
    st.caption('Última lectura: '+_stamp(result['checked_at'])+' · Tipo de cuenta: '+result['account_type'])
    try:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(result['checked_at'])).total_seconds()
        if age>60:st.warning('Esta lectura tiene más de un minuto. Pulsa «Consultar esta cuenta» para actualizarla.')
    except (ValueError,TypeError):pass
    st.markdown('**Saldos informados por Schwab**')
    if result['balances']:
        st.dataframe([{'Concepto':r['concept'],'Importe informado':r['value']} for r in result['balances']],hide_index=True,width='stretch')
    else:st.caption('La respuesta no incluyó los campos de saldo previstos.')
    st.caption('La divisa, la disponibilidad específica para opciones y los permisos para operar opciones aún deben verificarse. Estos importes no autorizan una compra.')
    st.markdown('**Posiciones de la cuenta**')
    if result['positions']:
        st.dataframe([{'Símbolo':r['symbol'],'Tipo':r['asset_type'],'Cantidad larga':r['long_quantity'],
            'Cantidad corta':r['short_quantity'],'Precio medio':r['average_price'],'Valor informado':r['market_value']}
            for r in result['positions']],hide_index=True,width='stretch')
    elif result['positions_known']:st.caption('Schwab devolvió una lista de posiciones vacía.')
    else:st.caption('La respuesta no incluyó una lista de posiciones; no se interpreta como cero.')
    if result['positions_truncated']:st.caption('Se muestran las primeras 200 posiciones de '+str(result['position_count'])+' recibidas.')
    st.caption('Solo observación: ninguna posición de esta cuenta se incorpora ni se gestiona automáticamente por JJTrade.')
    st.markdown('**Órdenes recibidas · últimas 24 horas**')
    if result['orders']:
        st.dataframe([{'Orden Schwab':r['order_id'],'Estado':r['status'],'Tipo':r['order_type'],
            'Símbolos':r['symbols'],'Cantidad':r['quantity'],'Ejecutados':r['filled_quantity'],'Fecha informada':r['entered_at']}
            for r in result['orders']],hide_index=True,width='stretch')
    else:st.caption('Schwab devolvió una lista vacía para el intervalo consultado.')
    if result['orders_truncated']:st.caption('Se muestran las primeras 200 de '+str(result['observed_order_count'])+' órdenes recibidas.')


def _setup():
    with st.expander('Preparar la conexión de cuentas'):
        st.write('Usaremos una aplicación distinta de JJTradeAI-Datos para conservar la conexión de la simulación.')
        st.write('En el portal Schwab: crea JJTradeAI-Cuenta con Accounts and Trading Production. Si solicita Order Limit, usa 0 para esta etapa de lectura.')
        st.code(ACCOUNT_CALLBACK,language=None)
        st.caption('Callback de la nueva aplicación. Las credenciales se guardarán mediante consola privada cifrada; no las envíes por chat ni las introduzcas en esta página.')
        st.link_button('Abrir portal de desarrolladores Schwab','https://developer.schwab.com/dashboard/apps')
