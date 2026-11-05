"""Explicit account selection shared across REAL views, without production I/O."""
from tests.test_real_preparation_panel import select_real_tab
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock,patch
from streamlit.testing.v1 import AppTest


def page():
    import streamlit as st
    from real_account_readonly import AccountReadOnlySession
    from real_trade_preparation import RealPreparationSession
    from real_preparation_panel import render_real_workspace
    from tests.test_real_account_readonly import client_fixture,NOW
    from tests.test_real_trade_preparation import MemoryPreparationStore
    if 'real_account_reader' not in st.session_state:
        clock=[NOW]
        st.session_state['test_clock']=clock
        client=client_fixture()
        st.session_state['test_client']=client
        st.session_state['real_account_reader']=AccountReadOnlySession(lambda:client,lambda:clock[0])
        store=MemoryPreparationStore()
        st.session_state['real_preparation_service']=RealPreparationSession(store_factory=lambda:store,clock=lambda:clock[0])
        st.session_state['real_workspace_view']='Cuenta'
    render_real_workspace()


class RealAccountPanelTests(TestCase):
    def setUp(self):
        self.register=self.enterContext(patch('real_live_control.register_selected_account'))
        self.proxies=[]
        def proxy(binding):
            runtime=Mock(binding=binding)
            runtime.can_arm.return_value=True
            runtime.status.return_value=dict(ready_to_arm=True,blockers=[])
            runtime.queue.read.return_value=None
            runtime.positions.return_value=[]
            runtime.trade_history.return_value=[]
            self.proxies.append(runtime)
            return runtime
        self.enterContext(patch('real_live_control.RealRuntimeProxy',side_effect=proxy))

    def app(self):return AppTest.from_function(page,default_timeout=25).run(timeout=25)

    def select(self,app):
        app.button(key='real_accounts_connect').click().run()
        ref=app.session_state['real_account_reader'].inventory['choices'][0]['ref']
        app.selectbox(key='real_account_choice').select(ref).run()
        return ref

    def test_initial_page_has_only_consult_button_and_no_implicit_selection(self):
        app=self.app()
        self.assertEqual(len(app.exception),0)
        self.assertEqual([t.label for t in app.tabs],['Cuenta','Con mi saldo','Preparar compañías','Cola real','Operaciones y resultados','Estado de la estrategia'])
        self.assertNotIn('real_workspace_view',[r.key for r in app.radio])
        self.assertEqual([b.label for b in app.button],['Consultar conexión y cuentas'])
        self.assertFalse(any('Preparar la conexión' in e.label for e in app.expander))
        self.register.assert_not_called()
        self.assertEqual(app.session_state['test_client'].method_calls,[])
        app.button(key='real_accounts_connect').click().run()
        self.assertIsNone(app.selectbox(key='real_account_choice').value)
        self.register.assert_not_called()
        app.session_state['test_client'].positions.assert_not_called()

    def test_selection_registers_once_and_survives_navigation_and_older_snapshot(self):
        app=self.app();ref=self.select(app)
        self.assertEqual(len(app.exception),0)
        self.register.assert_called_once()
        reader=app.session_state['real_account_reader'];binding=reader.preparation_binding(ref)
        runtime=app.session_state['real_execution_runtime']
        self.assertEqual(runtime.binding,binding)
        calls=list(app.session_state['test_client'].method_calls)
        app.session_state['test_clock'][0]+=timedelta(minutes=15)
        select_real_tab(app,'Preparar compañías')
        service=app.session_state['real_preparation_service']
        service.save(binding,[dict(symbol='AMZN',quantity=1,target='10')])
        select_real_tab(app,'Cola real')
        self.assertEqual(len(app.exception),0)
        self.assertNotIn('real_queue_connect',[b.key for b in app.button])
        self.assertFalse(any(b.key=='real_queue_arm' for b in app.button))
        runtime.arm.assert_not_called()
        select_real_tab(app,'Cuenta')
        self.assertEqual(app.selectbox(key='real_account_choice').value,ref)
        self.assertEqual(app.session_state['real_selected_account_ref'],ref)
        self.assertEqual(app.session_state['test_client'].method_calls,calls)
        self.register.assert_called_once()

    def test_same_consult_button_refreshes_account_without_reconnecting_in_queue(self):
        app=self.app();ref=self.select(app)
        app.session_state['test_clock'][0]+=timedelta(seconds=31)
        app.button(key='real_accounts_connect').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['real_selected_account_ref'],ref)
        self.assertEqual(app.session_state['test_client'].positions.call_count,2)
        self.assertEqual(self.register.call_count,2)
        self.assertEqual(len(self.proxies),1)
        self.proxies[0].arm.assert_not_called()

    def test_failed_identity_never_registers_or_arms_an_account(self):
        app=self.app()
        app.session_state['test_client'].positions.return_value['securitiesAccount']['accountNumber']='WRONG'
        self.select(app)
        self.assertEqual(len(app.exception),0)
        self.register.assert_not_called()
        self.assertEqual(self.proxies,[])
        app.session_state['test_client'].orders.assert_not_called()
        self.assertTrue(any('identidad' in w.value for w in app.warning))

    def test_registration_refusal_is_visible_and_private(self):
        self.register.side_effect=ValueError('LIVE_ACCOUNT_HAS_ACTIVE_QUEUE')
        app=self.app();self.select(app)
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('No se cambió la cuenta' in w.value for w in app.warning))
        self.assertEqual(self.proxies,[])
        self.register.side_effect=RuntimeError('SYNTHETIC_PRIVATE_ACCOUNT_BODY')
        app.session_state['test_clock'][0]+=timedelta(seconds=31)
        app.button(key='real_accounts_connect').click().run()
        self.assertFalse(any('SYNTHETIC_PRIVATE' in w.value for w in app.warning))
        self.assertEqual(self.proxies,[])
