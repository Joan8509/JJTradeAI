"""Explicit current activation status. No vault, broker or execution imports."""
import streamlit as st


def render_real_activation_status():
    details=st.expander('Activación de compras y ventas reales',key='real_activation_details',on_change='rerun')
    if not details.open:return
    with details:
        runtime=st.session_state.get('real_execution_runtime')
        try:
            if runtime is not None and callable(getattr(type(runtime),'display_status',None)):
                connected=runtime.display_status().get('ready_to_arm') is True
            else:connected=runtime is not None and runtime.can_arm()
        except Exception:connected=False
        if connected:st.info('Ejecutor real conectado. Activa tu selección desde «Preparar compañías» y síguela en «Cola real».')
        elif runtime is not None:st.warning('El ejecutor aún no confirma disponibilidad para armar compras. Revisa «Cola real».')
        else:st.caption('Selecciona tu cuenta y revisa el estado del ejecutor en «Cola real».')
        st.write('Parámetros solicitados: cantidades y objetivos del dashboard, con stop del 20%.')
        st.caption('La cola real usa el ejecutor supervisado en la VPS. Las compras exigen señal, contrato, cotización, previsualización y fondos válidos en ese momento.')
        st.write('El stop se gestiona desde la VPS al Bid disponible. El precio de ejecución y el porcentaje final dependen del mercado y del broker.')
        st.caption('«Activar preparación» pone las compañías bajo el radar. En «Cola real» puedes pausar, reactivar o quitar las que esperan.')
