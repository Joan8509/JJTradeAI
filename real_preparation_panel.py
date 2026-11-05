"""Real-mode preparation UI. No execution worker, broker writes or simulation I/O."""
from datetime import datetime,timezone
import streamlit as st
from real_trade_preparation import RealPreparationSession,PreparationError,TARGETS,watched_symbols
from price_ranges import optimal_option_premium

VIEWS=('Cuenta','Con mi saldo','Preparar compañías','Cola real','Operaciones y resultados','Estado de la estrategia')


def _target(value):return 'Manual' if value=='MANUAL' else value+'%' if value else 'Elegir objetivo'


def _account():
    reader=st.session_state.get('real_account_reader');ref=st.session_state.get('real_selected_account_ref')
    try:return reader,ref,reader.preparation_binding(ref)
    except Exception:return reader,ref,None


def _go_account():st.session_state['real_workspace_view']='Cuenta'
def _go_queue():st.session_state['real_workspace_view']='Cola real'


def _runtime(binding):
    if binding is None:return None
    runtime=st.session_state.get('real_execution_runtime')
    if runtime is None or runtime.binding!=binding:
        from real_live_control import RealRuntimeProxy
        runtime=RealRuntimeProxy(binding);st.session_state['real_execution_runtime']=runtime
    return runtime


def render_real_workspace():
    from real_activation_panel import render_real_activation_status
    render_real_activation_status()
    next_view=st.session_state.pop('real_workspace_next_view',None)
    if next_view in VIEWS:st.session_state['real_workspace_view']=next_view
    if st.session_state.get('real_workspace_view')=='Propuestas':
        st.session_state['real_workspace_view']='Preparar compañías'
    tabs=st.tabs(VIEWS,key='real_workspace_view',on_change='rerun')
    for view,tab in zip(VIEWS,tabs):
        if tab.open:
            with tab:_render_real_view(view)


def _render_real_view(view):
    if view=='Cuenta':
        from real_account_panel import render_real_account_panel
        render_real_account_panel();return
    if view=='Estado de la estrategia':
        from strategy_diagnostics_panel import render_strategy_diagnostics
        render_strategy_diagnostics(watched_symbols());return
    if view=='Operaciones y resultados':
        from real_results_panel import render_real_results
        render_real_results(_account()[2],go_account=_go_account,go_queue=_go_queue);return
    if 'real_preparation_service' not in st.session_state:
        st.session_state['real_preparation_service']=RealPreparationSession()
    service=st.session_state['real_preparation_service']
    reader,ref,binding=_account()
    if service.account_binding!=binding:
        service.preparation=None;service.last_result=None
    runtime=st.session_state.get('real_execution_runtime')
    try:connected=runtime is not None and runtime.binding==binding and runtime.can_arm()
    except Exception:connected=False
    st.info('Configuración de operaciones reales · Revisa el estado en «Cola real».' if connected else
        'Preparación para operar en real · Elige y activa las compañías en «Preparar compañías».')
    if binding is None:
        st.caption('Consulta y selecciona tu cuenta para preparar las compañías de la cola real.')
        st.button('Consultar mi cuenta',on_click=_go_account,key='real_prep_go_account')
    else:st.caption(reader.snapshot['account_label']+' · Preparación independiente de la simulación')
    if view=='Con mi saldo':
        from real_affordability_panel import render_affordability
        render_affordability(binding)
    elif view=='Preparar compañías':_editor(service,binding)
    elif view=='Cola real':_queue(service,reader,ref,binding)


@st.fragment(run_every='2s')
def _queue(service,reader,reference,binding):
    st.subheader('Compras automáticas reales')
    st.caption('Prepara tus compañías antes de la apertura. Solo la primera entrada válida podrá comprar; las demás quedarán fuera de esta cola. Stop del 20% y cierre manual.')
    st.caption('El contrato debe caber en tu efectivo liquidado, con la cantidad elegida y los costos informados. Los precios pueden cambiar al abrir.')
    st.caption('Los porcentajes se calculan sobre la prima. El resultado neto descontará las comisiones reales.')
    if binding is None:return
    runtime=_runtime(binding)
    try:status=runtime.status()
    except Exception:status={}
    # Only a server-owned runtime may be installed here. Loading a page, editing
    # rows or selecting Real never constructs a gateway or starts a worker.
    ready=False
    if runtime is not None and runtime.binding==binding:
        try:ready=runtime.can_arm()
        except Exception:pass
    if not ready:
        st.warning('Esperando que el ejecutor confirme cuenta, fondos y previsualización. El estado se actualiza automáticamente.')
        if runtime is not None and hasattr(runtime,'status'):
            codes=status.get('blockers',[])
            labels={'LIVE_HOST_NOT_CURRENT':'Esperando al ejecutor de la VPS',
                'LIVE_EXPLICIT_ACCOUNT_SELECTION_REQUIRED':'Selecciona y consulta tu cuenta en «Cuenta»',
                'LIVE_PREVIEW_PROTOCOL_NOT_VERIFIED':'Previsualización de Schwab pendiente de validar',
                'LIVE_ACCOUNT_NOT_CURRENT':'Esperando lectura actual de cuenta',
                'LIVE_OPTION_DATA_REAUTHORIZE':'Schwab pide reconectar JJTradeAI-Datos para consultar opciones',
                'LIVE_OPTION_DATA_AUTH_NOT_CURRENT':'Esperando verificación de la autorización de datos de opciones',
                'LIVE_SETTLED_CASH_UNPROVEN':'No se pudo comprobar el efectivo liquidado',
                'LIVE_ACCOUNT_REFRESH_UNAVAILABLE':'No se pudo actualizar la cuenta',
                'LIVE_EXIT_MONITOR_NOT_CURRENT':'Esperando al monitor de salidas',
                'LIVE_ORDER_MONITOR_NOT_CURRENT':'Esperando confirmaciones de órdenes de Schwab',
                'LIVE_ORDER_REQUIRES_RECONCILIATION':'Hay una solicitud que requiere conciliación con Schwab',
                'LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION':'Schwab informa una venta externa: requiere conciliar el cierre manual',
                'LIVE_DEPLOYMENT_VALIDATION_IN_PROGRESS':'Validación de la integración en curso'}
            if isinstance(codes,list) and codes:st.caption('Estado: '+', '.join(labels.get(c,'Revisión de conexión pendiente') for c in codes))
    if runtime is not None and hasattr(runtime,'status'):
        notice=status.get('execution_notices',{})
        if isinstance(notice,dict):
            if notice.get('state')=='CURRENT':st.caption('Avisos reales activos: compras y ventas confirmadas se envían por Telegram.')
            elif notice.get('state')=='DELIVERY_REQUIRES_REVIEW':st.warning('Hay una notificación real sin entrega confirmada. Revisa Telegram y el historial de operaciones.')
            elif notice.get('state')=='WAITING_RETRY':st.caption('Telegram pidió esperar; el aviso real se enviará al terminar ese intervalo.')
        targets=status.get('broker_target_orders',{})
        if isinstance(targets,dict) and targets:
            for contract,item in targets.items():
                if item.get('state')=='BROKER_TARGET_WORKING':st.success('Venta por ganancia colocada en Schwab: '+contract+' · LIMIT $'+item['limit'])
                elif item.get('review'):st.warning('La venta requiere conciliación: '+contract+'. Revisa la posición y las órdenes en Schwab; los reintentos están bloqueados.')
                elif item.get('error'):st.warning('Objetivo aún no colocado en Schwab: '+contract+'. La VPS mantiene la salida automática y el stop.')
                elif item.get('state')=='BROKER_TARGET_ACKNOWLEDGED':st.caption('Schwab recibió la venta por ganancia; verificando su estado.')
        followup=status.get('opportunities',{})
        external=status.get('external_manual_closes',{})
        if isinstance(external,dict):
            for contract,item in external.items():
                if item.get('review'):
                    st.warning('Venta manual pendiente de conciliación: '+contract+'. Compras pausadas; revisa las órdenes en Schwab.')
                elif item.get('state')=='MANUAL_CLOSE_RECONCILED':
                    st.success('Venta manual conciliada: '+contract+' · Restantes: '+str(item['remaining'])+'. Las demás compañías siguen pausadas.')
                elif item.get('detected'):
                    st.info('Venta manual detectada: '+contract+'. Conciliando cantidades y retirando la salida pendiente de la app. Compras pausadas.')
        if isinstance(followup,dict) and followup:
            messages={'NO_CURRENT_SIGNAL':'Esperando estrategia válida','WAITING_FOR_VALID_SIGNAL':'Esperando estrategia válida',
                'SIGNAL_ENTRY_WINDOW_EXPIRED':'Señal vencida; esperando una nueva',
                'LIVE_SETTLED_CASH_INSUFFICIENT':'Efectivo liquidado insuficiente',
                'LIVE_PREVIEW_NOT_ACCEPTED':'Schwab requiere revisar la propuesta',
                'LIVE_PREVIEW_COSTS_INCOMPLETE':'Esperando costos informados por Schwab',
                'COLLECTOR_NOT_CURRENT':'Esperando conexión de mercado',
                'TRADE_NOT_CURRENT':'Esperando precio reciente',
                'SIGNAL_AND_CONTRACT_PREPARED':'Entrada preparada; pendiente de ejecución',
                'NO_ELIGIBLE_EXPIRATION_OR_RANGE':'Sin contrato apto en el rango y vencimiento',
                'RATE_LIMITED':'Esperando el intervalo solicitado por Schwab'}
    st.info('Una sola operación entre todas las compañías. La primera solicitud reserva la entrada; una compra confirmada, incluso parcial, excluye a las demás. No se repite automáticamente después de vender.')
    notice=st.session_state.pop('real_queue_notice',None)
    if notice:st.success(notice)
    if runtime is not None and runtime.binding==binding:
        try:plan=runtime.queue.read(binding)
        except Exception:plan=None
        if plan:
            st.caption('Sesión: '+plan['session_open']+' → '+plan['session_close'])
            if plan.get('paused'):st.warning('Compras reales pausadas. Ninguna compañía de esta cola puede iniciar una compra nueva.')
            if plan.get('winning_symbol'):
                st.success('Primera compra confirmada: '+plan['winning_symbol']+'. Las demás compañías quedaron fuera de la entrada automática.')
            elif plan.get('first_entry_only') and plan.get('entry_owner'):
                owner=next((r['symbol'] for r in plan['rows'] if r['id']==plan['entry_owner']),'')
                st.caption('Entrada reservada para '+owner+'. Las demás esperan la confirmación de Schwab; no pueden comprar.')
            def row_state(row):
                if row['state']=='EXCLUDED_FIRST_ENTRY':return 'Fuera de entrada automática: ya se compró en otra compañía'
                if row['state']=='ARMED' and plan.get('entry_owner'):return 'En espera: entrada reservada'
                if row['state']=='ARMED':return 'Bajo el radar'
                return {'PAUSED':'Pausada','SUBMITTING':'Compra en proceso',
                    'ORDER_SENT':'Operación en seguimiento','REQUIRES_REVIEW':'Requiere revisión'}.get(row['state'],row['state'])
            def row_followup(row):
                if row['state']=='PAUSED':return 'Compras pausadas'
                if row['state']=='ORDER_SENT':return 'Confirmando ejecuciones y vigilando la operación'
                if row['state']=='SUBMITTING':return 'Preparando el envío de compra'
                if row['state']=='REQUIRES_REVIEW':return 'Conciliación pendiente; nuevas compras bloqueadas'
                if plan.get('entry_owner'):return 'Esperando confirmación de la primera compra'
                if isinstance(followup,dict) and followup:
                    return messages.get(followup.get(row['symbol']),'Esperando estrategia válida')
                return 'Esperando estrategia válida'
            visible=[r for r in plan['rows'] if r['state'] not in ('REMOVED','EXPIRED','COMPLETED','EXCLUDED_FIRST_ENTRY')]
            st.caption('Compañías en esta cola: '+str(len(visible)))
            if visible:
                st.dataframe([{'Compañía':r['symbol'],'Contratos':r['quantity'],'Objetivo':_target(r['target']),
                    'Estado':row_state(r),'Seguimiento':row_followup(r)}
                    for r in visible],hide_index=True,width='stretch')
            else:st.info('No hay compañías en espera de operar. Puedes activarlas desde «Preparar compañías».')
            removable=[r for r in visible if r['state'] in ('ARMED','PAUSED') and
                not r.get('request_id') and not r.get('claim') and plan.get('entry_owner')!=r['id']]
            if removable:
                choices={r['id']:r['symbol'] for r in removable}
                selected=st.selectbox('Compañía que quieres quitar de la cola',list(choices),
                    format_func=choices.get,key='real_queue_remove_choice_'+plan['id'])
                if st.button('Quitar compañía de la cola real',key='real_queue_remove',width='stretch'):
                    try:
                        runtime.remove(plan['id'],selected)
                        st.session_state['real_queue_notice']=choices[selected]+' quitada de la cola real.'
                        st.rerun()
                    except Exception:
                        st.error('No se pudo quitar. Actualiza la cola: puede haber cambiado o tener una compra en curso.')
            if removable:
                paused=bool(plan.get('paused'))
                session_current=datetime.now(timezone.utc)<datetime.fromisoformat(plan['session_close'])
                can_resume=ready and session_current and not plan.get('entry_owner') and not plan.get('entry_consumed') and not any(
                    r['state'] in ('SUBMITTING','ORDER_SENT','REQUIRES_REVIEW') for r in plan['rows'])
                if paused and not session_current:st.caption('La sesión de esta cola terminó. Activa una preparación para la próxima sesión desde «Preparar compañías».')
                if st.button('Activar' if paused else 'Pausar',key='real_queue_toggle',
                        disabled=paused and not can_resume,width='stretch'):
                    try:
                        if paused:runtime.resume(plan['id'])
                        else:runtime.pause()
                        st.session_state['real_queue_notice']='Compañías activas bajo el radar.' if paused else 'Compras pausadas. El seguimiento de salidas continúa.'
                        st.rerun()
                    except Exception:
                        st.error('No se pudo cambiar el estado. Si la sesión terminó, activa una nueva preparación; una compra en curso conserva su seguimiento.')
                if st.button('Eliminar todas las compañías en espera',key='real_queue_clear',width='stretch'):
                    try:
                        runtime.remove_waiting(plan['id'])
                        st.session_state['real_queue_notice']='Compañías en espera eliminadas. Las operaciones iniciadas conservan su seguimiento.'
                        st.rerun()
                    except Exception:st.error('No se pudo vaciar la espera. La cola puede haber cambiado.')
        else:st.info('No hay compañías activadas. Elige las compañías y pulsa «Activar preparación» en «Preparar compañías».')
    if runtime is not None and hasattr(runtime,'positions'):
        try:positions=runtime.positions()
        except Exception:positions=[]
        if isinstance(positions,list) and positions:
            st.subheader('Mis posiciones reales de la app')
            for position in positions:
                st.write(position['contract']+' · '+str(position['quantity'])+' contratos · Objetivo '+_target(position['target']))
                if st.button('Cerrar esta posición en REAL',key='real_close_'+position['id'],
                        disabled=position.get('external_close_pending',False),width='stretch'):
                    try:
                        runtime.close_manually(position['id'])
                        st.success('Cierre solicitado al ejecutor. La posición se confirma cerrada cuando Schwab informa la ejecución.')
                    except Exception:st.error('No se pudo registrar el cierre. Revisa el estado de la cuenta y del ejecutor.')
    if runtime is not None and hasattr(runtime,'trade_history'):
        try:history=runtime.trade_history()
        except Exception:history=[]
        if isinstance(history,list) and history:
            st.subheader('Operaciones reales confirmadas por Schwab')
            st.dataframe([{'Contrato':r['contract'],'Compra confirmada':r['bought'],
                'Precio de entrada':r['entry_average'],'Hora de compra (UTC)':r['entered_at'],
                'Venta confirmada':r['sold'],'Estado':'Cerrada' if r['state']=='CLOSED' else 'Abierta',
                'Cierre manual conciliado':'Sí' if r['manual_close'] else 'No'} for r in history],
                hide_index=True,width='stretch')
    st.caption('Los avisos de estrategia siguen su propio radar. La confirmación de una operación real aparece en esta cola y en Schwab.')


def _select_symbols(values):st.session_state['real_prep_symbols']=list(values)


def _editor(service,binding):
    universe=watched_symbols();scope=binding or 'UNSELECTED'
    models=st.session_state.setdefault('real_prep_models',{})
    model=models.setdefault(scope,dict(selected=[],rows={},generation=0))
    if st.session_state.get('real_prep_widget_scope')!=scope:
        st.session_state['real_prep_widget_scope']=scope
        st.session_state['real_prep_symbols']=list(model['selected'])
    st.subheader('Preparar compañías')
    st.caption('Selecciona una, varias o todas; aplica cantidad y objetivo. «Activar preparación» las deja bajo el radar para comprar automáticamente con dinero real al detectar una entrada válida.')
    left,right=st.columns(2)
    left.button('Seleccionar todas',on_click=_select_symbols,args=(universe,),key='real_prep_all',width='stretch')
    right.button('Quitar selección',on_click=_select_symbols,args=((),),key='real_prep_none',width='stretch')
    if 'real_prep_symbols' not in st.session_state:st.session_state['real_prep_symbols']=list(model['selected'])
    selected=st.multiselect('Compañías',universe,key='real_prep_symbols')
    if list(selected)!=model['selected']:
        model['selected']=list(selected);model['generation']+=1
    for symbol in selected:model['rows'].setdefault(symbol,dict(symbol=symbol,quantity=1,target=None))
    qty_col,target_col=st.columns(2)
    qty=qty_col.number_input('Contratos para todas',min_value=1,step=1,key='real_prep_common_quantity')
    target=target_col.selectbox('Objetivo para todas',[None,*TARGETS],format_func=_target,key='real_prep_common_target')
    if st.button('Aplicar a todas las seleccionadas',key='real_prep_apply',disabled=not selected or target is None,width='stretch'):
        for symbol in selected:model['rows'][symbol]=dict(symbol=symbol,quantity=qty,target=target)
        model['generation']+=1
    if not selected:
        st.caption('Selecciona al menos una compañía.');return
    rows=[]
    for symbol in selected:
        row=model['rows'][symbol]
        try:price_range=optimal_option_premium(symbol)
        except ValueError:price_range=None
        rows.append({'Compañía':symbol,'Contratos':row['quantity'],'Objetivo':row['target'] or 'ELEGIR',
            'Rango Ask':f'{price_range[0]}–{price_range[1]}' if price_range else 'Sin rango definido'})
    edited=st.data_editor(rows,hide_index=True,width='stretch',num_rows='fixed',
        key='real_prep_editor_'+scope[:12]+'_'+str(model['generation']),disabled=['Compañía','Rango Ask'],
        column_config={'Contratos':st.column_config.NumberColumn(min_value=1,step=1,required=True),
            'Objetivo':st.column_config.SelectboxColumn(options=['ELEGIR',*TARGETS],required=True)})
    payload=[dict(symbol=r['Compañía'],quantity=r['Contratos'],target=r['Objetivo'] if r['Objetivo']!='ELEGIR' else None) for r in edited]
    for row in payload:model['rows'][row['symbol']]=dict(row)
    st.caption('Stop del 20% y cierre manual. La primera compra confirmada deja a las demás compañías fuera de la entrada automática.')
    runtime=_runtime(binding)
    try:ready=runtime is not None and runtime.can_arm()
    except Exception:ready=False
    if not ready:st.caption('Para activar, selecciona tu cuenta en «Cuenta» y espera que el ejecutor confirme la conexión.')
    if st.button('Activar preparación',key='real_prep_activate',disabled=not ready,type='primary',width='stretch'):
        try:
            if _account()[2]!=binding:raise ValueError('ACCOUNT_SELECTION_REQUIRED')
            plan=runtime.queue.read(binding)
            if plan and any(r['state'] not in ('PAUSED','EXPIRED','COMPLETED','EXCLUDED_FIRST_ENTRY','REMOVED') for r in plan['rows']):
                raise ValueError('LIVE_QUEUE_ALREADY_EXISTS')
            saved=service.save(binding,payload)
            runtime.arm(saved['rows'],repeat_new_signals=False,first_entry_only=True)
            st.session_state['real_queue_notice']='Preparación activada. Compañías bajo el radar para una sola entrada real.'
            st.session_state['real_workspace_next_view']='Cola real'
            st.rerun()
        except PreparationError as error:
            st.error('Elige una cantidad entera y un objetivo para cada compañía.' if str(error) in ('QUANTITY_REQUIRED','TARGET_REQUIRED') else 'Revisa la selección antes de guardar.')
        except Exception as error:
            st.error('Ya existe una cola en seguimiento. Usa sus controles antes de activar otra preparación.'
                if str(error)=='LIVE_QUEUE_ALREADY_EXISTS' else 'No se pudo confirmar la activación. Revisa la cuenta y «Cola real» antes de volver a intentarlo.')
