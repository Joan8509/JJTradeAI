"""Streamlit plan editor. Saving/reading plans never submits an order."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import streamlit as st

from automatic_entry_queue import QueueStore, official_sessions, signal_key, watched_symbols
from market_store import DEFAULT_MARKET_DATABASE
from manual_trade_service import read_manual_state
from price_ranges import optimal_option_premium
from mobile_layout import MOBILE_STYLE
from option_contract_selection import MAX_ENTRY_SPREAD
from option_exit_plan import load_global_exit_policy
from schwab_queue_readiness import probe_queue_connection, connection_is_recent, BackgroundConnectionProbe

LABELS = {
    'ARMED':'En cola', 'PAUSED':'Pausada', 'DISPATCHING':'Registrando solicitud',
    'SUBMITTED':'Entrada de esta fila ya utilizada', 'UNCERTAIN':'Requiere conciliación',
    'EXPIRED':'Sesión terminada', 'BLOCKED':'Entrada detenida',
    'WAITING_NEW_SIGNAL':'Esperando una señal nueva', 'BEFORE_SESSION':'Esperando apertura',
    'NO_CURRENT_SIGNAL':'Esperando que se cumpla la estrategia',
    'NO_ELIGIBLE_CONTRACTS':'Sin contrato ITM/OTM≤5 que cumpla rango y spread; sigue esperando',
    'NO_ELIGIBLE_EXPIRATION_OR_RANGE':'Sin vencimiento o rango apto',
    'MONITOR_NOT_READY':'Esperando monitor de salidas',
    'COLLECTOR_NOT_CURRENT':'Esperando conexión y datos recientes del colector',
    'TRADE_NOT_CURRENT':'Esperando un trade reciente', 'DATA_NOT_READY':'Datos todavía no aptos',
    'CHECK_REQUIRED':'Comprobación pendiente; no se ha autorizado una entrada',
    'MARKET_DATA_COOLDOWN':'Esperando el intervalo del proveedor',
    'MARKET_DATA_UNAVAILABLE':'Cotizaciones Schwab no disponibles',
    'REAUTHORIZATION_REQUIRED':'Renovar autorización de Schwab',
    'AUTHORIZATION_REQUIRED':'Falta autorización de Schwab',
    'SIGNAL_CHANGED':'La señal cambió durante la consulta',
    'RESTART_WAIT_NEW_SIGNAL':'Tras reiniciar, esperando una señal nueva',
    'PAUSED_BY_USER':'Pausada por ti', 'SESSION_ENDED':'No se traslada automáticamente al día siguiente',
    'RECONCILIATION_REQUIRED':'Revisar solicitudes y posiciones; no se reintentará',
    'SIGNAL_ALREADY_CLAIMED':'Esta señal ya tiene una solicitud; no se repetirá',
    'RANGE_CHANGED_REARM_REQUIRED':'Cambió el rango: revisar y volver a poner en cola',
    'EXISTING_EXPOSURE_NO_REINFORCEMENT':'Ya hay posición o compra pendiente en esta compañía',
    'ENTRIES_PAUSED_OR_UNRECONCILED':'Entradas pausadas o conciliación pendiente',
    'DUPLICATE_SIGNAL':'Esta señal ya fue operada; esperando otra señal nueva',
    'DETECTOR_STATE_INVALID':'Esperando un estado válido y actual del detector',
    'MAINTENANCE':'Actualizando el motor de entradas; se conserva tu configuración',
}

@st.cache_resource
def queue_store():
    """v4: refresh cached component for final quote diagnostics and maintenance."""
    return QueueStore()


@st.cache_resource(show_spinner=False)
def connection_probe():
    return BackgroundConnectionProbe()


def queue_connection():
    return connection_probe().poll()


@st.fragment
def render_queue_connection():
    if st.button('Comprobar conexión Schwab', key='auto_queue_check_schwab', width='stretch'):
        # Only this explicit interaction waits for the provider. Typing in the
        # editor and idle viewing never launch timed UI reruns.
        with st.spinner('Comprobando conexión Schwab…'):
            connection_probe().remember(probe_queue_connection())
    result = queue_connection()
    slot = st.empty()
    show_queue_connection(result, slot)
    return connection_is_recent(result, datetime.now(timezone.utc)), slot


def show_queue_connection(result, slot):
    ready = connection_is_recent(result, datetime.now(timezone.utc))
    with slot.container():
        if ready:
            st.success('Schwab conectado · Acceso a cotizaciones comprobado')
        elif result.get('state') == 'AUTHORIZATION_REQUIRED':
            st.error('Schwab necesita renovar la autorización. Completa la autorización en el escritorio RDP de la VPS y pulsa Comprobar conexión Schwab.')
        elif result.get('state') in {'CHECKING','CONNECTED'}:
            st.info('Comprobando Schwab en segundo plano. Puedes preparar la selección; se verificará antes de ponerla en cola.')
        else:
            st.warning('Conexión con Schwab sin confirmar. Puedes elegir tus compañías; comprueba la conexión antes de ponerlas en cola.')
        if result.get('reason') in {'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED',
                'PRIVATE_MARKET_CONFIG_UNAVAILABLE','TRANSPORT_FAILURE',
                'HTTP_FAILURE','RATE_LIMITED','CHECK_FAILED'}:
            st.caption('Comprobacion: '+result['reason'])
        try:
            stamp = datetime.fromisoformat(result['checked_at']).astimezone(ZoneInfo('America/New_York'))
            st.caption('Última comprobación: '+stamp.strftime('%H:%M:%S ET')+
                ' · Se comprueba de nuevo al poner en cola. La compra sigue siendo simulada; contrato y datos se validan al entrar.')
        except (KeyError, TypeError, ValueError):
            pass


def render_automatic_entry_panel(*, embedded=False):
    st.markdown(MOBILE_STYLE,unsafe_allow_html=True)
    st.markdown('## Preparar entradas automáticas · Simulación')
    st.info('Selecciona compañías, contratos y objetivo. Al ponerlas en cola, autorizas una compra '
        'simulada por compañía en la sesión elegida cuando aparezca una señal nueva. No usa dinero de Schwab.')
    st.caption('Salida superior → CALL · Salida inferior → PUT · ITM u OTM hasta 5.º strike · Apto más cercano al spot · '
        f'Ask dentro de tu rango · Spread máximo ${MAX_ENTRY_SPREAD:.2f} · Stop loss {load_global_exit_policy().stop_loss_pct}% · Cierre manual disponible.')
    connection_ready, connection_slot = render_queue_connection()
    if not embedded:
        if st.button('Operaciones y resultados',key='auto_queue_results',width='stretch'):
            st.query_params.clear();st.query_params['resultados']='1';st.rerun()
    now = datetime.now(timezone.utc)
    try:
        store = queue_store()
        sessions = official_sessions(DEFAULT_MARKET_DATABASE, now)
        symbols = watched_symbols()
    except Exception:
        st.error('No se pudo abrir la cola o el calendario oficial. No se ha armado ninguna entrada.'); return
    if not sessions:
        st.warning('Falta calendario oficial de próximas sesiones. No se inventarán fechas de mercado.'); return
    days = {s[0]:s for s in sessions}
    saved_day=st.session_state.get('auto_queue_saved_session',st.session_state.get('auto_queue_session'))
    if saved_day not in days:
        saved_day=next(iter(days));bulk_clear_consent()
    st.session_state['auto_queue_saved_session']=saved_day
    st.session_state['auto_queue_session']=saved_day
    session_day = st.selectbox('Sesión en que se permiten las entradas (ET)', list(days),
        format_func=lambda day: day+' · '+datetime.fromisoformat(days[day][1]).astimezone(ZoneInfo('America/New_York')).strftime('%H:%M')+
        '–'+datetime.fromisoformat(days[day][2]).astimezone(ZoneInfo('America/New_York')).strftime('%H:%M'), key='auto_queue_session',on_change=queue_session_changed)
    st.caption('Puedes preparar o pausar la cola antes de abrir o durante el mercado. '
        'Solo toma señales nuevas posteriores al armado; no compra por avisos antiguos. '
        'Cada fila se consume al registrar una solicitud y caduca al cierre de su sesión.')
    mode=st.radio('Preparar cola', ['Varias compañías','Una compañía'],
        key='auto_queue_mode',horizontal=True,on_change=pause_queue_follow)
    if mode=='Varias compañías':
        render_bulk_preparation(store,symbols,session_day,connection_ready,connection_slot)
        render_queue_status(store)
        return
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1, 2])
        def clear_company():
            pause_queue_follow()
            st.session_state['auto_queue_quantity']=0
            st.session_state['auto_queue_target']=None
            st.session_state['auto_queue_consent']=False
        def clear_consent():
            pause_queue_follow()
            st.session_state['auto_queue_consent']=False
        symbol = c1.selectbox('Compañía', symbols, key='auto_queue_symbol', on_change=clear_company)
        quantity = c2.number_input('Contratos', min_value=0, step=1, key='auto_queue_quantity', on_change=clear_consent)
        target = c3.selectbox('Ganancia objetivo', [None,'10','20','35','100','MANUAL'],
            format_func=lambda x: 'Elige objetivo' if x is None else 'Cierre manual' if x == 'MANUAL' else x+'%', key='auto_queue_target', on_change=clear_consent)
        st.caption('El costo máximo de primas será cantidad × 100 × Ask máximo de tu rango. '
            'La compra simulada usa el Ask actual hasta ese máximo y caduca tras 10 segundos sin completar. '
            'Comisiones no verificadas; no es un límite diario.')
    try:
        low, high = optimal_option_premium(symbol)
        st.write(f'**{symbol}** · Rango Ask ${low}–${high} por acción del contrato · '
            f'Prima por contrato: ${low*100:.2f}–${high*100:.2f}')
        if quantity is not None and quantity > 0:
            st.write(f'**Máximo de primas para esta fila: ${high*100*int(quantity):.2f} USD**')
    except ValueError:
        st.warning('Esta compañía todavía no tiene un rango aprobado; no puede armarse.')
    consent = st.checkbox('Autorizar esta entrada automática en SIMULACIÓN para la sesión elegida', key='auto_queue_consent')
    submit = st.button('Poner en cola · Simulación', type='primary', key='auto_queue_arm',width='stretch')
    if submit:
        if not consent or quantity is None or quantity < 1 or target is None:
            st.warning('Elige cantidad, objetivo y autorización para poner la compañía en cola.')
        else:
            # Do not arm from the cached indicator: verify now before authorizing.
            with st.spinner('Verificando Schwab antes de poner en cola…'):
                fresh_connection = probe_queue_connection()
            connection_probe().remember(fresh_connection)
            show_queue_connection(fresh_connection, connection_slot)
            if not connection_is_recent(fresh_connection, datetime.now(timezone.utc)):
                st.error('Schwab no confirmó el acceso. Esta compañía no se puso en cola. Comprueba la conexión e inténtalo de nuevo.')
                render_queue_status(store)
                return
            now = datetime.now(timezone.utc)
            try:
                # Symbols/target/session are revalidated by backend.
                state = read_manual_state(DEFAULT_MARKET_DATABASE, symbol, now.astimezone(ZoneInfo('America/New_York')).date())
                store.arm(symbol, int(quantity), target, session_day, now=now,
                    sessions=official_sessions(DEFAULT_MARKET_DATABASE, now), baseline=signal_key(state.get('tick') or {}))
                st.session_state['auto_queue_follow']=True
                st.success(symbol+' está en cola. Puedes añadir otra compañía en el mismo formulario.')
            except Exception:
                st.error('No se pudo poner en cola. Comprueba rango y sesión; una compañía ya armada '
                    'o con resultado incierto no se vuelve a autorizar. Revisa su fila abajo.')
    render_queue_status(store)


def pause_queue_follow():
    # Display only: never pauses the stored queue, entries or position monitor.
    st.session_state['auto_queue_follow']=False


def bulk_clear_consent():
    pause_queue_follow()
    st.session_state['auto_bulk_consent']=False


def queue_session_changed():
    st.session_state['auto_queue_saved_session']=st.session_state['auto_queue_session']
    st.session_state['auto_queue_consent']=False
    bulk_clear_consent()


def bulk_draft():
    # Widget-owned state is cleaned up when a tab/mode is not rendered.
    # A separate draft survives navigation, but never grants authorization.
    if 'auto_bulk_draft' not in st.session_state:
        selected=list(st.session_state.get('auto_bulk_symbols',[]))
        controls=dict(quantity=st.session_state.get('auto_bulk_default_quantity',0),
            target=st.session_state.get('auto_bulk_default_target'))
        st.session_state['auto_bulk_draft']=dict(selected=selected,controls=controls,
            applied=dict(quantity=0,target=None),rows={symbol:dict(
                quantity=st.session_state.get('auto_bulk_quantity_'+symbol,0),
                target=st.session_state.get('auto_bulk_target_'+symbol)) for symbol in selected})
    return st.session_state['auto_bulk_draft']


def bulk_select_symbols(symbols):
    draft=bulk_draft();draft['selected']=list(symbols)
    for symbol in symbols:
        draft['rows'].setdefault(symbol,dict(draft['applied']))
    st.session_state['auto_bulk_symbols']=list(symbols)
    bulk_clear_consent()


def bulk_selection_changed():
    bulk_select_symbols(st.session_state.get('auto_bulk_symbols',[]))


def bulk_controls_changed():
    bulk_draft()['controls']=dict(quantity=st.session_state['auto_bulk_default_quantity'],
        target=st.session_state['auto_bulk_default_target'])
    bulk_clear_consent()


def bulk_row_changed(symbol):
    bulk_draft()['rows'][symbol]=dict(quantity=st.session_state['auto_bulk_quantity_'+symbol],
        target=st.session_state['auto_bulk_target_'+symbol])
    bulk_clear_consent()


def bulk_apply_defaults(fields=('quantity','target')):
    draft=bulk_draft();bulk_controls_changed()
    chosen={key:value for key,value in draft['controls'].items()
        if key in fields and ((key=='quantity' and value>0) or (key=='target' and value is not None))}
    draft['applied'].update(chosen)
    for symbol in draft['selected']:
        draft['rows'].setdefault(symbol,dict(quantity=0,target=None)).update(chosen)
    bulk_clear_consent()


def target_label(value):
    return 'Elige objetivo' if value is None else 'Cierre manual' if value=='MANUAL' else value+'%'


def render_bulk_preparation(store,symbols,session_day,connection_ready,connection_slot):
    draft=bulk_draft()
    draft['selected']=[symbol for symbol in draft['selected'] if symbol in symbols]
    st.session_state['auto_bulk_symbols']=list(draft['selected'])
    available=[]
    for symbol in symbols:
        try:optimal_option_premium(symbol);available.append(symbol)
        except ValueError:pass
    c1,c2=st.columns(2)
    c1.button('Seleccionar todas con rango',key='auto_bulk_select_all',width='stretch',
        on_click=bulk_select_symbols,args=(available,),help='Solo cambia esta preparación; no modifica la cola ya guardada.')
    c2.button('Quitar selección',key='auto_bulk_select_none',width='stretch',
        on_click=bulk_select_symbols,args=([],),help='Solo vacía la selección del formulario; las entradas ya en cola permanecen.')
    selected=st.multiselect('1. Selecciona las compañías',symbols,
        key='auto_bulk_symbols',on_change=bulk_selection_changed)
    if not selected:
        st.caption('Después podrás aplicar la misma cantidad y objetivo a todas, o ajustar cada compañía.')
        return
    st.markdown('**2. Define contratos y objetivos**')
    st.session_state['auto_bulk_default_quantity']=draft['controls']['quantity']
    st.session_state['auto_bulk_default_target']=draft['controls']['target']
    c1,c2=st.columns(2)
    default_qty=c1.number_input('Contratos para todas',min_value=0,step=1,
        key='auto_bulk_default_quantity',on_change=bulk_controls_changed,
        help='Deja 0 para conservar las cantidades de cada compañía al aplicar el objetivo.')
    default_target=c2.selectbox('Objetivo para todas',[None,'10','20','35','100','MANUAL'],
        format_func=target_label,key='auto_bulk_default_target',on_change=bulk_controls_changed)
    c1.button('Aplicar solo contratos',key='auto_bulk_apply_quantity',width='stretch',
        disabled=default_qty<1,on_click=bulk_apply_defaults,args=(('quantity',),))
    c2.button('Aplicar solo objetivo',key='auto_bulk_apply_target',width='stretch',
        disabled=default_target is None,on_click=bulk_apply_defaults,args=(('target',),))
    st.button('Aplicar a todas las seleccionadas',key='auto_bulk_apply',width='stretch',
        disabled=default_qty<1 and default_target is None,on_click=bulk_apply_defaults)
    st.caption('Puedes aplicar solo el objetivo dejando contratos en 0, o solo los contratos dejando «Elige objetivo». '
        'Las compañías nuevas reciben los últimos valores aplicados; tus ajustes individuales se conservan.')
    selections=[];total=0;valid=True
    for symbol in selected:
        row=draft['rows'].setdefault(symbol,dict(draft['applied']))
        st.session_state['auto_bulk_quantity_'+symbol]=row['quantity']
        st.session_state['auto_bulk_target_'+symbol]=row['target']
        with st.container(border=True):
            st.markdown('**'+symbol+'**')
            c1,c2=st.columns(2)
            quantity=c1.number_input('Contratos · '+symbol,min_value=0,step=1,
                key='auto_bulk_quantity_'+symbol,on_change=bulk_row_changed,args=(symbol,))
            target=c2.selectbox('Objetivo · '+symbol,[None,'10','20','35','100','MANUAL'],
                format_func=target_label,key='auto_bulk_target_'+symbol,on_change=bulk_row_changed,args=(symbol,))
            try:
                low,high=optimal_option_premium(symbol)
                cost=high*100*quantity;total+=cost
                st.caption(f'Rango Ask ${low}–${high} · Máximo de primas ${cost:.2f}')
            except ValueError:
                valid=False
                st.warning('Falta rango aprobado. Quita esta compañía para poner las demás en cola.')
            valid=valid and quantity>0 and target is not None
            selections.append(dict(symbol=symbol,quantity=quantity,target=target))
    incomplete=[row['symbol'] for row in selections if row['quantity']<1 or row['target'] is None]
    if incomplete:
        st.info('Completa cantidad y objetivo en: '+', '.join(incomplete)+'. Aún no están en cola.')
        if default_qty > 0 or default_target is not None:
            st.warning('Los valores comunes de arriba aún no están aplicados a todas las filas. '
                'Pulsa «Aplicar a todas las seleccionadas» y revisa los datos antes de autorizar.')
    st.write(f'**{len(selected)} compañías · Máximo conjunto de primas: ${total:.2f} USD**')
    st.caption('Cantidad × 100 × Ask máximo de cada rango. No es pérdida máxima ni límite diario; comisiones no verificadas.')
    signature=(session_day,tuple((row['symbol'],row['quantity'],row['target']) for row in selections))
    if st.session_state.get('auto_bulk_signature')!=signature:
        bulk_clear_consent()
        st.session_state['auto_bulk_signature']=signature
    st.checkbox('Autorizar las compañías y cantidades de esta selección en SIMULACIÓN para la sesión elegida',
        key='auto_bulk_consent')
    if not valid:
        st.warning('Para habilitar el botón, completa cantidad, objetivo y rango de todas las compañías seleccionadas.')
    elif not st.session_state.get('auto_bulk_consent'):
        st.info('3. Marca la autorización de simulación que aparece arriba y pulsa Poner seleccionadas en cola. No se compra al guardar la cola.')
    if st.button('Poner seleccionadas en cola · Simulación',type='primary',width='stretch',
            key='auto_bulk_arm',disabled=not valid):
        if not st.session_state.get('auto_bulk_consent'):
            st.warning('Revisa la selección y marca la autorización antes de ponerla en cola.')
            return
        with st.spinner('Verificando Schwab antes de poner en cola…'):
            fresh=probe_queue_connection()
        connection_probe().remember(fresh);show_queue_connection(fresh,connection_slot)
        if not connection_is_recent(fresh,datetime.now(timezone.utc)):
            st.error('Schwab no confirmó el acceso. No se puso ninguna compañía en cola; tu selección permanece.')
            return
        try:
            now=datetime.now(timezone.utc)
            for selection in selections:
                state=read_manual_state(DEFAULT_MARKET_DATABASE,selection['symbol'],now.astimezone(ZoneInfo('America/New_York')).date())
                selection['baseline']=signal_key(state.get('tick') or {})
            now=datetime.now(timezone.utc)
            if not connection_is_recent(fresh,now):raise ValueError('CONNECTION_NOT_CURRENT')
            store.arm_many(selections,session_day,now=now,
                sessions=official_sessions(DEFAULT_MARKET_DATABASE,now))
        except Exception:
            st.error('No se añadió ninguna compañía. Revisa si alguna ya está en cola, tiene un intento incierto o necesita un rango o sesión válidos.')
        else:
            st.session_state['auto_queue_follow']=True
            st.success(f'{len(selections)} compañías puestas en cola para la sesión elegida. Esperan una señal nueva.')


def clear_queue_rows(store, *, now, ledger_path=None):
    """Archive a bounded snapshot using the existing atomic exposure guard.

    Never deletes ledger history or attempts, and never retries a changed row.
    New plans added concurrently are outside this user's snapshot.
    """
    removed = kept = 0
    for row in store.plans():
        try:
            store.archive(row['id'], now=now, ledger_path=ledger_path)
            removed += 1
        except Exception:
            try:
                if row['state']!='UNCERTAIN':raise ValueError
                store.archive_unexecuted_uncertain(row['id'],now=now,ledger_path=ledger_path)
                removed+=1
            except Exception:
                # Includes real exposure, unresolved attempts and RO failures.
                kept += 1
    return removed, kept


def render_queue_status(store):
    st.session_state.setdefault('auto_queue_follow',False)
    live=st.toggle('Seguimiento en vivo de la cola',key='auto_queue_follow',
        help='Solo actualiza esta vista. Apagarlo no pausa entradas, salidas ni avisos.')
    if not live:
        st.caption('Vista sin refrescos automáticos mientras preparas. La cola guardada sigue funcionando; '
            'puedes actualizarla manualmente o activar su seguimiento.')
    return st.fragment(run_every='2s' if live else None,key='auto_queue_status')(_render_queue_status)(store)


def _render_queue_status(store):
    # An ordinary button interaction reruns only this fragment.
    st.button('Actualizar cola',key='auto_queue_refresh',width='stretch')
    st.markdown('### Mi cola y resultados')
    now = datetime.now(timezone.utc)
    try:
        status = store.status(now); plans = store.plans()
    except Exception:
        st.error('No se pudo consultar el estado de la cola.'); return
    if status == 'READY':
        st.success('Motor de entradas conectado · Simulación local')
    elif status == 'MONITOR_NOT_READY':
        st.warning('Esperando sesión regular y monitor de salidas listo. Fuera de mercado no se ejecutan entradas.')
    else:
        st.warning('Motor de entradas sin comprobación reciente. Guardar la cola no demuestra que esté ejecutándose.')
    if store.maintenance():
        st.warning('Actualización en curso: las nuevas entradas están pausadas temporalmente. Se conserva tu selección.')
    if st.button('Pausar todas las entradas en cola', key='auto_queue_pause_all',width='stretch'):
        store.pause(); st.rerun()
    if st.button('Borrar operaciones', key='auto_queue_clear_all',width='stretch',disabled=not plans,
            help='Quita las filas en cola, pausadas y ya cerradas. Conserva el historial y las operaciones abiertas o pendientes.'):
        removed, kept = clear_queue_rows(store, now=datetime.now(timezone.utc))
        st.session_state['auto_queue_clear_result'] = (removed, kept)
        st.rerun()
    cleared = st.session_state.pop('auto_queue_clear_result', None)
    if cleared is not None:
        st.success(f'{cleared[0]} filas quitadas. El historial permanece en Mis operaciones.')
        if cleared[1]:
            st.warning(f'{cleared[1]} filas conservadas: tienen una operación abierta, pendiente o requieren revisión.')
    st.caption('Eliminar quita la fila de esta vista y pausa su entrada si sigue en cola. '
        'El historial se conserva. Una operación abierta o pendiente se gestiona en Mis operaciones / cerrar.')
    if not plans:
        st.info('Cola vacía. Añade tu primera compañía arriba.'); return
    from queue_position_cards import read_card_snapshot,render_card_position
    cards=read_card_snapshot(now=now) if any(p['client_key'] for p in plans) else {}
    from decimal import Decimal
    armed = [p for p in plans if p['state']=='ARMED' and datetime.fromisoformat(p['closes_at'])>now]
    st.write(f"En cola: {len(armed)} compañías · Máximo conjunto de primas: $"+
        f"{sum((Decimal(p['max_cost']) for p in armed),Decimal('0')):.2f} USD")
    for row in plans:
        with st.container(border=True):
            st.markdown('**'+row['symbol']+' · '+str(row['quantity'])+' contratos · '+
                ('Cierre manual' if row['target']=='MANUAL' else 'Objetivo '+row['target']+'%')+'**')
            st.write(row['session_date']+' ET · '+LABELS.get(row['state'], row['state']))
            st.caption('Stop para nuevas entradas '+str(load_global_exit_policy().stop_loss_pct)+'% · Rango Ask $'+row['low']+'–$'+row['high']+' · Máximo de primas $'+row['max_cost'])
            if row['reason']:
                st.write(LABELS.get(row['reason'], 'Esperando comprobaciones: '+row['reason']))
            try:
                check=store.last_catalog_check(row['id'])
                if check:
                    from queue_entry_diagnostics import check_caption
                    st.caption(check_caption(check))
            except (ValueError,OSError):pass
            if row['state']=='ARMED' and st.button('Pausar '+row['symbol'], key='auto_queue_pause_'+row['id'],width='stretch'):
                store.pause(row['id']); st.rerun()
            removable=store.can_archive(row)
            if (row['state']=='UNCERTAIN' and row['client_key'] is None and
                    now>=datetime.fromisoformat(row['closes_at'])):
                st.caption('Este intento no se reintentará. Puedes comprobar ambos registros del simulador y retirarlo si no llegó a crear una orden.')
                if st.button('Comprobar y retirar '+row['symbol'],key='auto_queue_review_'+row['id'],width='stretch'):
                    try:store.archive_unexecuted_uncertain(row['id'],now=datetime.now(timezone.utc))
                    except Exception:
                        st.warning('No se puede retirar todavía: hay una orden, exposición o no fue posible confirmar ambos registros.')
                    else:st.rerun()
            if st.button('Eliminar '+row['symbol'],key='auto_queue_delete_'+row['id'],width='stretch',
                    disabled=not removable,help='Pausa y quita esta fila; conserva el historial. Disponible cuando no hay operación abierta, pendiente o incierta.'):
                try:store.archive(row['id'],now=datetime.now(timezone.utc))
                except Exception:
                    st.warning('No se pudo quitar: la operación cambió o requiere conciliación. Revisa su estado.');continue
                st.rerun()
            if row['client_key']:
                st.caption('Esta fila autoriza una compra. Para otra entrada, añade una nueva fila con tu cantidad y objetivo.')
                render_card_position(row,cards.get(row['client_key']))
                if st.button('Ver operación / cerrar', key='auto_queue_view_'+row['id']):
                    st.query_params.clear(); st.query_params['operaciones']='1'; st.rerun()
    if st.button('Mis operaciones / cerrar', key='auto_queue_positions'):
        st.query_params.clear(); st.query_params['operaciones']='1'; st.rerun()
