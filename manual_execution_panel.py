"""Manual confirmation widgets; only the isolated local simulator can act."""
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit as st

from manual_execution import configured_workflow
from manual_trade_service import read_manual_state
from market_store import DEFAULT_MARKET_DATABASE
from schwab_connection import EncryptedSchwabStore

OWNER='administrator_manual'


@st.cache_resource(ttl=30,show_spinner=False)
def shared_manual_workflow():
    """Missing private opt-in never creates/adopts a simulation database."""
    try:
        from manual_trade_panel import _shared_market_data
        profile=EncryptedSchwabStore().load()
        if not isinstance(profile.get('manual_simulation_policy'),dict) and profile.get('manual_practice_enabled') is not True:
            return None
        def state(symbol):
            today=datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
            return read_manual_state(DEFAULT_MARKET_DATABASE,symbol,today)
        workflow=configured_workflow(profile,Path(__file__).resolve().parent/'exports/trade_review/manual_simulation',
            read_state=state,market_data=_shared_market_data())
        from schwab_simulation import practice_policy
        if practice_policy(workflow.engine.policy):
            from vps_private_runtime import load_config
            from manual_alert_entry import read_alert_reference
            chat=load_config()['TELEGRAM_CHAT_ID']
            workflow.alert_reader=lambda symbol,side,candle:read_alert_reference(
                DEFAULT_MARKET_DATABASE,symbol,side,candle,chat)
        return workflow
    except Exception:
        # Private payloads, account references, paths and provider bodies stay out of UI/logs.
        return None


def _failure():
    st.warning('No se pudo completar la revisión. Comprueba datos, posición y configuración antes de preparar otra. '
        'Una respuesta incierta no se reenvía automáticamente.')


def render_confirmation(workflow, owner, review, *, key):
    st.markdown('**Confirma la operación simulada**')
    st.write('Cuenta simulada: '+review['account_alias'])
    st.write(review['contract']+' · '+str(review['quantity'])+' contratos')
    if review['action']=='BUY':
        st.write(f"Comprar al Ask ${review['ask']} · Total estimado ${review['entry_cost']} USD")
        if review.get('fees_known') is False:
            st.caption('Importe de primas. Costos no verificados; resultado neto no disponible.')
        st.write('Ganancia: '+('Cierre manual' if review['target']=='MANUAL' else review['target']+'%')+
            ' · Stop loss: '+review['stop']+'%')
    elif review['action']=='CLOSE':
        st.write('Cerrar toda la posición · Límite mínimo revisado: $'+review['minimum_price'])
    else:
        st.write('Cancelar la cantidad pendiente. Lo ya comprado se conserva hasta cerrar la posición.')
    st.caption('Solo simulación local. La revisión caduca a los 30 segundos; cualquier cambio exige revisarla de nuevo.')
    used='manual_review_used_'+review['id']
    label={'BUY':'Confirmar compra simulada','CLOSE':'Confirmar cierre simulado',
           'CANCEL':'Confirmar cancelación simulada'}[review['action']]
    if st.button(label,key=key+'_'+review['id'],disabled=st.session_state.get(used,False)):
        # UI guard supplements the durable shared claim in ManualReviews.
        st.session_state[used]=True
        try:
            result=workflow.confirm(owner,review['id'])
        except Exception:
            _failure();return
        status=result['status']
        if status in ('UNKNOWN','EXIT_UNCERTAIN'):
            st.warning('Resultado simulado incierto. Se requiere conciliación; no se repetirá la orden.')
        elif status in ('EXIT_ALREADY_PENDING','EXIT_REVIEW_ALREADY_USED'):
            st.info('Ya existe una solicitud de salida. Revisa su estado; la posición puede seguir abierta.')
        elif status=='CANCELED':
            st.success('Cancelación simulada confirmada. Revisa la cantidad que permanece comprada.')
        else:
            st.success('Solicitud simulada registrada. Aún no significa compra o venta ejecutada.')


def render_entry_actions(symbol, side, contract, quantity_review, target, candle, *, workflow=None, owner=OWNER):
    workflow=workflow or shared_manual_workflow()
    from schwab_simulation import practice_policy
    observed=workflow is not None and practice_policy(workflow.engine.policy)
    ready=workflow is not None and quantity_review is not None and target is not None and (observed or contract.price_increment is not None)
    context=(symbol,side,contract.snapshot.symbol,candle,
        tuple(sorted((str(k),str(v)) for k,v in (quantity_review or {}).items())),str(target))
    key='manual_entry_draft_'+symbol+'_'+side
    stored=st.session_state.get(key)
    if stored and stored['context']!=context:
        del st.session_state[key];stored=None
    if st.button('Preparar compra simulada '+side,key='manual_prepare_buy_'+symbol,disabled=not ready):
        try:
            kwargs={'alert_candle':candle} if observed and callable(getattr(workflow,'alert_reader',None)) else {}
            review=workflow.prepare_buy(owner,symbol,side,contract.snapshot.symbol,quantity_review['quantity'],target,**kwargs)
        except Exception:
            _failure();return
        stored={'context':context,'review':review};st.session_state[key]=stored
    if stored:
        render_confirmation(workflow,owner,stored['review'],key='manual_confirm_buy_'+symbol)
    if workflow is None:
        st.info('La simulación manual aún requiere su configuración de cuenta simulada y límites de riesgo. '
            'Los costos y el incremento de precio del contrato deben estar verificados.')


@st.fragment(run_every='1s')
def render_manual_positions(*, workflow=None, owner=OWNER):
    st.markdown('### Mis operaciones · Simulación')
    st.caption('Órdenes reales deshabilitadas. Las posiciones y ejecuciones de esta sección son simuladas localmente.')
    workflow=workflow or shared_manual_workflow()
    if workflow is None:
        st.info('No hay una sesión de simulación manual configurada. No se han consultado posiciones de la cuenta real.')
        from position_monitor_panel import render_empty_position_monitor
        render_empty_position_monitor()
        st.button('Cerrar posición simulada',disabled=True,key='manual_no_position')
        return
    try:
        from telegram_manual_controls import companion_ready
        if not companion_ready():
            workflow.observe()
    except Exception:
        st.info('Esperando cotizaciones y conciliación aptas para actualizar la simulación.')
    try:
        positions=workflow.positions();orders=workflow.pending_orders()
    except Exception:
        _failure();return
    from schwab_simulation import practice_policy
    if practice_policy(workflow.engine.policy):
        from manual_practice_report import practice_summary
        try:
            summary=practice_summary(workflow.engine.ledger,workflow.engine.policy.account_alias,now=workflow.clock())
            st.markdown('#### Resultado del ensayo conectado')
            st.write(f"Cerradas: {summary['closed_trades']} · Ganadoras: {summary['winning_closed_trades']} · "
                f"Perdedoras: {summary['losing_closed_trades']} · Contratos abiertos: {summary['remaining_contracts']}")
            st.write(f"Resultado bruto de cerradas: ${summary['closed_gross_pnl']:+.2f} USD · "
                f"Ventas parciales: {summary['partial_exits']}")
            st.write(f"Resultado bruto realizado en ventas parciales: ${summary['partial_realized_gross']:+.2f} USD")
            st.caption('Precios reales; ejecuciones simuladas. Selección manual de operaciones, '
                'sin rentabilidad garantizada. Costos no verificados: neto no disponible. '
                'Las posiciones abiertas no están incluidas en el resultado de cerradas.')
        except Exception:
            st.info('Resumen del ensayo pendiente de conciliación.')
    if not positions and not orders:
        st.info('Sin posiciones ni órdenes simuladas pendientes.')
    for row in orders:
        with st.container(border=True):
            order=row['order']
            st.write(order['contract']+' · '+('Compra' if order['instruction']=='BUY_TO_OPEN' else 'Cierre')+
                ' · '+row['status']+f" · Ejecutados {row['filled_quantity']}/{order['quantity']}")
            st.caption('Una orden pendiente no equivale a una ejecución confirmada.')
            if st.button('Preparar cancelación simulada',key='manual_cancel_'+row['client_key'],
                    disabled=row['status'] not in ('WORKING','PARTIALLY_FILLED')):
                try:
                    st.session_state['manual_cancel_review_'+row['client_key']]=workflow.prepare_cancel(owner,row['client_key'])
                except Exception:_failure()
            review=st.session_state.get('manual_cancel_review_'+row['client_key'])
            if review:
                render_confirmation(workflow,owner,review,key='manual_cancel_confirm_'+row['client_key'])
    for position in positions:
        code=position['contract']
        with st.container(border=True):
            st.write(code+f" · {position['quantity']} contratos · Prima media ${position['average_fill']}")
            st.caption('Stop loss: '+position['plan']['stop_pct']+'% · Ganancia: '+
                (position['plan']['target_pct']+'%' if position['plan']['target_pct'] is not None else 'Cierre manual'))
            from position_monitor_panel import render_position_monitor
            render_position_monitor(workflow,position)
            if st.button('Cerrar posición simulada',key='manual_close_'+position['entry_client_key']):
                try:
                    st.session_state['manual_close_review_'+code]=workflow.prepare_close(owner,code)
                except Exception:_failure()
            review=st.session_state.get('manual_close_review_'+code)
            if review:
                render_confirmation(workflow,owner,review,key='manual_close_confirm_'+code)
