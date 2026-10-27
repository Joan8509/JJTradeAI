"""Three focused, lazily rendered tabs; viewing live signals cannot arm a queue."""
import streamlit as st

TABS=('Estrategia en Vivo','Operar Automáticamente','Mis operaciones')
SLUGS=('vivo','automatico','operaciones')
HOME_STYLE='''<style>
/* jj-home-tabs-v2: one continuous surface, without the floating underline. */
.st-key-jj_home_nav [data-testid="stTabs"] [role="tablist"] {
  width:100%;gap:.4rem;padding:.4rem;box-sizing:border-box;
  background:rgba(12,26,45,.96);border:1px solid #29405c;border-radius:14px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.04);}
.st-key-jj_home_nav [data-testid="stTabs"] [role="tab"] {
  flex:1 1 0!important;min-width:0!important;justify-content:center;
  white-space:normal!important;height:auto;min-height:3rem;padding:.65rem .75rem;
  border-radius:9px;border:1px solid transparent;box-shadow:none;}
.st-key-jj_home_nav [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  background:#1b3b60;border-color:#365b83;box-shadow:inset 0 1px 0 #ffffff0a;}
.st-key-jj_home_nav [data-testid="stTabs"] [role="tab"] p {
  white-space:normal!important;overflow-wrap:normal;text-align:center;
  font-size:1rem!important;font-weight:600;line-height:1.25;}
.st-key-jj_home_nav [data-baseweb="tab-highlight"],
.st-key-jj_home_nav [data-baseweb="tab-border"] {display:none!important;}
@media(max-width:700px){
  .st-key-jj_home_nav [data-testid="stTabs"] [role="tablist"] {gap:.2rem;padding:.25rem;}
  .st-key-jj_home_nav [data-testid="stTabs"] [role="tab"] {min-height:3.5rem;padding:.4rem .2rem;}
  .st-key-jj_home_nav [data-testid="stTabs"] [role="tab"] p {font-size:.82rem!important;}
}
</style>'''


def render_dashboard_home(*, show_header=True):
    st.markdown(HOME_STYLE,unsafe_allow_html=True)
    if show_header:
        st.markdown('# JJTrade AI')
        st.caption('Mercado en vivo · Operaciones en simulación')
    desired='automatico' if st.query_params.get('automaticas')=='1' else 'operaciones' if st.query_params.get('resultados')=='1' else st.query_params.get('vista','vivo')
    if desired not in SLUGS:desired='vivo'
    label=TABS[SLUGS.index(desired)]
    if st.session_state.get('jj_home_tab')!=label:st.session_state['jj_home_tab']=label
    for legacy in ('automaticas','resultados'):
        if legacy in st.query_params:del st.query_params[legacy]
    if st.query_params.get('vista')!=desired:
        st.query_params['vista']=desired
    def changed():
        st.query_params['vista']=SLUGS[TABS.index(st.session_state['jj_home_tab'])]
    with st.container(key='jj_home_nav'):
        tabs=st.tabs(TABS,key='jj_home_tab',on_change=changed)
        for index,tab in enumerate(tabs):
            if not tab.open:continue
            with tab:
                if index==0:
                    from dashboard_live import render_live_strategies
                    render_live_strategies()
                elif index==1:
                    from automatic_entry_panel import render_automatic_entry_panel
                    render_automatic_entry_panel(embedded=True)
                else:
                    from operation_results_panel import render_operation_results
                    render_operation_results(title='Mis operaciones',default_period='Todo el historial',show_manage=True)
