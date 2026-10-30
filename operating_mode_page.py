"""Navigation only: selecting a page never changes broker or worker modes."""
import streamlit as st


_SIMULATION_LINKS = ('vista', 'automaticas', 'resultados', 'operaciones', 'operar', 'ajustes')


def selected_page(params):
    mode = params.get('modo')
    if mode == 'real':
        return 'real'
    if mode == 'simulacion':
        return 'simulacion'
    # Preserve existing dashboard/Telegram links, always as simulation.
    if mode is None and any(params.get(key) for key in _SIMULATION_LINKS):
        return 'simulacion'
    return 'inicio'


def _choose(mode):
    st.query_params.clear()
    if mode:
        st.query_params['modo'] = mode


def render_operating_mode(render_brand):
    """Return True only for the existing simulation UI; no broker access here."""
    page = selected_page(st.query_params)
    if page == 'simulacion':
        if st.query_params.get('modo') != 'simulacion':
            st.query_params['modo'] = 'simulacion'
        with st.container(horizontal=True, vertical_alignment='center'):
            st.button('← Cambiar de modo', key='jj_mode_back',
                      on_click=_choose, args=(None,))
            st.caption('SIMULACIÓN · No utiliza dinero real')
        return True

    render_brand()
    if page == 'real':
        st.subheader('Operar en Real')
        from real_account_panel import render_real_account_panel
        render_real_account_panel()
        st.button('Ir a Simulación', key='jj_real_to_simulation', type='primary',
                  on_click=_choose, args=('simulacion',), width='stretch')
        st.button('← Volver al inicio', key='jj_real_back',
                  on_click=_choose, args=(None,), width='stretch')
        return False

    st.subheader('¿Cómo quieres operar?')
    st.caption('Elige tu espacio de trabajo.')
    left, right = st.columns(2, gap='medium')
    with left:
        with st.container(border=True):
            st.markdown('### Operar en Real')
            st.write('Tu espacio para operar con tu cuenta Schwab.')
            st.caption('Consulta de cuenta · Solo lectura')
            st.button('Operar en Real', key='jj_select_real',
                      on_click=_choose, args=('real',), width='stretch')
    with right:
        with st.container(border=True):
            st.markdown('### Operar en Simulación')
            st.write('Practica con el dashboard que ya tienes preparado.')
            st.caption('Simulación local · Sin utilizar dinero real')
            st.button('Operar en Simulación', key='jj_select_simulation', type='primary',
                      on_click=_choose, args=('simulacion',), width='stretch')
    return False
