"""Restore presentation in a fresh browser without activating trading."""
from contextlib import nullcontext
from hashlib import sha256
from unittest import TestCase
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest
from real_dashboard_selection import saved_selection


def fresh_page(view='Cola real',cleared=False):
    import streamlit as st
    from unittest.mock import Mock,patch
    from real_preparation_panel import _render_real_view
    binding='a'*64
    if 'test_runtime' not in st.session_state:
        # A widget's initial empty default is not an explicit deselection.
        st.session_state['real_selected_account_ref']=None
        st.session_state['real_account_choice']=None
        st.session_state['real_account_selection_cleared']=cleared
        runtime=Mock(binding=binding)
        runtime.can_arm.return_value=False
        runtime.status.return_value={'blockers':['LIVE_ACCOUNT_NOT_CURRENT']}
        runtime.positions.return_value=[];runtime.trade_history.return_value=[]
        runtime.queue.read.return_value=dict(id='SAVED',paused=False,first_entry_only=True,
            entry_consumed=False,entry_owner=None,session_open='2099-01-01T14:30:00+00:00',
            session_close='2099-01-01T21:00:00+00:00',rows=[dict(id='ONE',symbol='AAPL',quantity=1,target='10',state='ARMED')])
        service=Mock(account_binding=binding)
        service.load.return_value={'rows':[dict(symbol='AAPL',quantity=1,target='10')]}
        st.session_state['test_runtime']=runtime
        st.session_state['real_preparation_service']=service
    runtime=st.session_state['test_runtime']
    with patch('real_dashboard_selection.saved_selection',return_value=dict(binding=binding,label='Cuenta guardada')),\
         patch('real_live_control.RealRuntimeProxy',return_value=runtime),\
         patch('socket.socket.connect',side_effect=AssertionError('NO_NETWORK')):
        _render_real_view(view)


class RestoredDashboardTests(TestCase):
    def store(self,binding=None):
        identity='1234';key='SYNTHETIC'
        expected=sha256(('JJTRADE_ACCOUNT_PREPARATION_V1\0'+identity+'\0'+key).encode()).hexdigest()
        store=Mock();store.locked.side_effect=lambda:nullcontext()
        store.path.exists.return_value=True
        store.load.return_value=dict(purpose='REAL_CONTROL_V1',execution_authorized=False,
            account=dict(account_number=identity,account_hash=key,binding=binding or expected))
        return store,expected

    def test_reading_previous_selection_neither_grants_nor_writes_authorization(self):
        store,binding=self.store()
        self.assertEqual(saved_selection(store_factory=lambda:store),dict(binding=binding,label='Cuenta ••••1234'))
        store.save.assert_not_called()

    def test_mismatched_identity_cannot_restore_another_binding(self):
        store,_=self.store('b'*64)
        self.assertIsNone(saved_selection(store_factory=lambda:store));store.save.assert_not_called()

    def test_new_browser_displays_persisted_queue_even_when_executor_is_blocked(self):
        app=AppTest.from_function(fresh_page).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value['Compañía'].tolist(),['AAPL'])
        runtime=app.session_state['test_runtime']
        runtime.arm.assert_not_called();runtime.pause.assert_not_called()
        runtime.remove_waiting.assert_not_called()

    def test_saved_editor_loads_once_and_clearing_does_not_repopulate_or_rearm(self):
        app=AppTest.from_function(fresh_page,kwargs={'view':'Preparar compañías'}).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual(app.multiselect[0].value,['AAPL'])
        app.button(key='real_prep_none').click().run(timeout=20)
        self.assertFalse(app.exception);self.assertEqual(app.multiselect[0].value,[])
        app.session_state['real_preparation_service'].load.assert_called_once_with('a'*64)
        app.session_state['test_runtime'].arm.assert_not_called()

    def test_explicit_account_deselection_does_not_restore_a_different_context(self):
        app=AppTest.from_function(fresh_page,kwargs={'cleared':True}).run(timeout=20)
        self.assertFalse(app.exception);self.assertEqual(len(app.dataframe),0)
        app.session_state['test_runtime'].queue.read.assert_not_called()
