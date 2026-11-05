"""Funding guidance only: no quote polling, order gateway or queue mutation."""
import streamlit as st
from real_affordability import current_budget,range_candidates
from real_trade_preparation import watched_symbols
from price_ranges import load_optimal_option_premiums


def _prepare(binding,symbols):
    models=st.session_state.setdefault('real_prep_models',{})
    model=models.setdefault(binding,dict(selected=[],rows={},generation=0))
    model['selected']=list(symbols)
    for symbol in symbols:
        old=model['rows'].get(symbol,{})
        model['rows'][symbol]=dict(symbol=symbol,quantity=1,target=old.get('target'))
    model['generation']+=1
    st.session_state['real_prep_widget_scope']=binding
    st.session_state['real_prep_symbols']=list(symbols)
    st.session_state['real_prep_common_quantity']=1
    st.session_state['real_workspace_view']='Preparar compañías'


def render_affordability(binding):
    st.subheader('Compañías para un contrato con mi saldo')
    st.caption('Lista orientativa por el rango de primas configurado. El precio y los costos del contrato se confirman con Schwab al detectar una entrada válida.')
    if binding is None:
        st.info('Selecciona y consulta tu cuenta en «Cuenta».');return
    from real_live_control import RealRuntimeProxy
    runtime=st.session_state.get('real_execution_runtime')
    if runtime is None or runtime.binding!=binding:
        runtime=RealRuntimeProxy(binding)
        st.session_state['real_execution_runtime']=runtime
    try:
        budget=current_budget(runtime.status(),binding)
        rows=range_candidates(watched_symbols(),budget['available'],load_optimal_option_premiums())
    except ValueError:
        st.warning('No hay una lectura actual del efectivo disponible. En «Cola real», conecta la cuenta seleccionada y después actualiza esta vista.')
        st.button('Actualizar saldo y lista',key='real_budget_refresh',width='stretch');return
    left,right=st.columns(2)
    left.metric('Efectivo disponible para nuevas compras',f"${budget['available']:.2f} USD")
    right.metric('Reservas de compras recientes o pendientes',f"${budget['reserved']:.2f} USD")
    st.caption('Se usa el efectivo liquidado comprobado, con las reservas de la app descontadas; no el valor total de la cuenta. Un contrato estándar representa 100 unidades de prima.')
    candidates=[r['symbol'] for r in rows if r['candidate']]
    st.write(f'{len(candidates)} compañías candidatas por rango para 1 contrato.')
    states={'CANDIDATE_COSTS_PENDING':'Puede caber; confirmar Ask y costos',
        'OUT_OF_BUDGET':'Prima mínima fuera del presupuesto',
        'COSTS_LEAVE_NO_MARGIN':'Sin margen para costos; pendiente',
        'RANGE_MISSING':'Sin rango configurado'}
    st.dataframe([{'Compañía':r['symbol'],'Contratos':1,
        'Prima por contrato (USD)':f"{r['minimum']:.2f}–{r['maximum']:.2f}" if 'minimum' in r else 'Sin rango',
        'Ask máximo antes de costos':f"{r['ask_ceiling']:.4f}" if r['candidate'] else '—',
        'Estado':states[r['state']]} for r in rows],hide_index=True,width='stretch')
    st.caption('La lista no confirma que exista ahora un contrato apto ni una señal. Deben cumplirse rango, spread, vencimiento, frescura y costos; el Ask máximo indicado aún debe descontar comisiones y tasas. Se compra solo una de las compañías de la cola.')
    st.button('Preparar candidatas con 1 contrato',key='real_budget_prepare',
        disabled=not candidates,on_click=_prepare,args=(binding,candidates),width='stretch')
    st.caption('Después elige el objetivo y pulsa «Activar preparación». Este botón de selección no activa compras ni cambia una cola ya activa.')
    if candidates:
        _check_contract(binding,runtime,candidates,budget['available'])
    st.button('Actualizar saldo y lista',key='real_budget_refresh',width='stretch')


def _check_contract(binding,runtime,candidates,available):
    from datetime import datetime,timezone
    st.subheader('Comprobar un contrato sin comprar')
    symbol=st.selectbox('Compañía candidata',candidates,key='real_budget_company')
    side=st.selectbox('Dirección del contrato',['CALL','PUT'],key='real_budget_side')
    st.caption('Consulta opcional durante la sesión regular, con la cola real sin activar y sin posiciones de la app. Comprueba un contrato con cotización reciente y costos de Schwab; no espera ni genera una señal.')
    def idle():
        try:
            plan=runtime.queue.read(binding)
            return not runtime.positions() and (not plan or not any(
                r['state'] in ('ARMED','SUBMITTING','ORDER_SENT') for r in plan['rows']))
        except Exception:return False
    if st.button('Comprobar precio y costos · sin comprar',key='real_budget_check',width='stretch'):
        st.session_state.pop('real_budget_result',None)
        try:
            from real_live_control import next_official_session,verified_preview_wire
            from real_affordability import verify_contract_budget
            # Refuse outside RTH/busy before constructing any OAuth/market client.
            now=datetime.now(timezone.utc);start,end=next_official_session(now)
            if not start<=now<end:raise ValueError('OUTSIDE_OFFICIAL_SESSION')
            if not idle():raise ValueError('BUDGET_CHECK_EXECUTOR_BUSY')
            reader=st.session_state['real_account_reader']
            context=reader.preview_context(st.session_state['real_selected_account_ref'])
            if context.binding!=binding:raise ValueError('BUDGET_NOT_CURRENT')
            from manual_trade_service import owner_market_data
            from schwab_preview_client import SchwabPreviewClient
            result=verify_contract_budget(symbol,side,context=context,market=owner_market_data(),
                preview=SchwabPreviewClient(context,wire_format=verified_preview_wire(binding)),
                budget_reader=runtime.status,idle=idle,session_provider=next_official_session)
            st.session_state['real_budget_result']=result
        except Exception as error:
            messages={'OUTSIDE_OFFICIAL_SESSION':'Fuera de la sesión regular. Por ahora usa la lista orientativa por rango.',
                'BUDGET_CHECK_EXECUTOR_BUSY':'La cola o una posición real está en seguimiento. Esta consulta queda reservada para antes de activar la cola.',
                'NO_CURRENT_AFFORDABLE_CONTRACT':'No se encontró ahora un contrato apto de esa dirección dentro del efectivo disponible.',
                'BUDGET_COST_EXCEEDS_AVAILABLE':'El contrato comprobado supera el saldo al incluir los costos.',
                'ACCOUNT_READING_NOT_CURRENT':'Actualiza primero la lectura de tu cuenta en «Cuenta».'}
            st.warning(messages.get(str(error),'No se pudo confirmar precio y costos actuales. Actualiza la cuenta y vuelve a comprobar; no se envió una compra.'))
    result=st.session_state.get('real_budget_result')
    if result and result.get('binding')==binding and result.get('symbol')==symbol and result.get('side')==side:
        from decimal import Decimal
        if datetime.now(timezone.utc)<datetime.fromisoformat(result['expires_at']) and Decimal(result['cost'])<=available:
            st.success(f"Contrato comprobado: {result['contract']} · Ask ${result['ask']} · Costo estimado con cargos: ${result['cost']} USD por 1 contrato.")
            st.caption('Válido solo para la cotización consultada. La compra automática vuelve a comprobar fondos, contrato y estrategia; esta consulta no reserva dinero.')
        else:st.caption('La comprobación del contrato venció. Consulta de nuevo para obtener precio y costos actuales.')
