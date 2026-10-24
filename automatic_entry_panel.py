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


def render_automatic_entry_panel(*, embedded=False):
    st.markdown(MOBILE_STYLE,unsafe_allow_html=True)
    st.markdown('## Preparar entradas automáticas · Simulación')
    st.info('Selecciona compañías, contratos y objetivo. Al ponerlas en cola, autorizas una compra '
        'simulada por compañía en la sesión elegida cuando aparezca una señal nueva. No usa dinero de Schwab.')
    st.caption('Salida superior → CALL · Salida inferior → PUT · ITM u OTM hasta 5.º strike · Apto más cercano al spot · '
        f'Ask dentro de tu rango · Spread máximo ${MAX_ENTRY_SPREAD:.2f} · Stop loss {load_global_exit_policy().stop_loss_pct}% · Cierre manual disponible.')
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
    session_day = st.selectbox('Sesión en que se permiten las entradas (ET)', list(days),
        format_func=lambda day: day+' · '+datetime.fromisoformat(days[day][1]).astimezone(ZoneInfo('America/New_York')).strftime('%H:%M')+
        '–'+datetime.fromisoformat(days[day][2]).astimezone(ZoneInfo('America/New_York')).strftime('%H:%M'), key='auto_queue_session')
    st.caption('Puedes preparar o pausar la cola antes de abrir o durante el mercado. '
        'Solo toma señales nuevas posteriores al armado; no compra por avisos antiguos. '
        'Cada fila se consume al registrar una solicitud y caduca al cierre de su sesión.')
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1, 2])
        def clear_company():
            st.session_state['auto_queue_quantity']=0
            st.session_state['auto_queue_target']=None
            st.session_state['auto_queue_consent']=False
        def clear_consent():
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
            try:
                # Symbols/target/session are revalidated by backend.
                state = read_manual_state(DEFAULT_MARKET_DATABASE, symbol, now.astimezone(ZoneInfo('America/New_York')).date())
                store.arm(symbol, int(quantity), target, session_day, now=now,
                    sessions=official_sessions(DEFAULT_MARKET_DATABASE, now), baseline=signal_key(state.get('tick') or {}))
                st.success(symbol+' está en cola. Puedes añadir otra compañía en el mismo formulario.')
            except Exception:
                st.error('No se pudo poner en cola. Comprueba rango y sesión; una compañía ya armada '
                    'o con resultado incierto no se vuelve a autorizar. Revisa su fila abajo.')
    render_queue_status(store)


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
            # Includes rows claimed concurrently, open exposure and RO failures.
            kept += 1
    return removed, kept


@st.fragment(run_every='2s')
def render_queue_status(store):
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
