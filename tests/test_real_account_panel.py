"""UI account selection and protected data views; no actual credentials/network."""
from unittest import TestCase
from streamlit.testing.v1 import AppTest


def page():
    import streamlit as st
    from real_account_panel import render_real_account_panel
    from real_account_readonly import AccountReadOnlySession
    from tests.test_real_account_readonly import client_fixture,NOW
    if 'real_account_reader' not in st.session_state:
        client=client_fixture()
        st.session_state['test_client']=client
        st.session_state['real_account_reader']=AccountReadOnlySession(lambda:client,lambda:NOW)
    render_real_account_panel()


class AccountPanelTests(TestCase):
    def test_no_reads_on_open_and_explicit_choice_before_snapshot(self):
        app=AppTest.from_function(page).run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['test_client'].method_calls,[])
        app.button(key='real_accounts_connect').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(app.button(key='real_account_read').disabled)
        self.assertIsNone(app.selectbox(key='real_account_choice').value)
        app.selectbox(key='real_account_choice').select_index(1).run()
        self.assertEqual(app.session_state['test_client'].positions.call_count,0)
        app.button(key='real_account_read').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.dataframe),3)
        self.assertFalse(any('comprar' in button.label.lower() or 'vender' in button.label.lower() for button in app.button))
        rendered=' '.join(element.value for kind in (app.caption,app.markdown,app.success) for element in kind)
        self.assertNotIn('111122223333',rendered);self.assertNotIn('SYNTHETIC_ACCOUNT_HASH',rendered)
