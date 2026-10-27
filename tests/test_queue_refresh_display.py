"""Refresh display choices never pause the actual queue or create orders."""
from unittest import TestCase


def page():
    import streamlit as st
    from unittest.mock import Mock,patch
    from automatic_entry_panel import render_queue_status
    store=Mock()
    store.plans.return_value=[]
    store.status.return_value='READY'
    store.maintenance.return_value=False
    original_fragment=st.fragment
    def fragment(*args,**kwargs):
        if kwargs.get('key')=='auto_queue_status':
            st.session_state['observed_interval']=kwargs.get('run_every')
        return original_fragment(*args,**kwargs)
    with patch('automatic_entry_panel.st.fragment',side_effect=fragment):
        render_queue_status(store)
    store.pause.assert_not_called()
    store.arm.assert_not_called()
    store.arm_many.assert_not_called()
    store.archive.assert_not_called()


class QueueRefreshDisplayTests(TestCase):
    def test_preparation_has_no_timer_and_manual_refresh_never_pauses_queue(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(page).run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertIsNone(app.session_state['observed_interval'])
        app.button(key='auto_queue_refresh').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertIsNone(app.session_state['observed_interval'])

    def test_display_follow_is_explicit_and_can_be_switched_off_without_store_mutation(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(page).run(timeout=20)
        app.toggle(key='auto_queue_follow').set_value(True).run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['observed_interval'],'2s')
        app.toggle(key='auto_queue_follow').set_value(False).run()
        self.assertEqual(len(app.exception),0)
        self.assertIsNone(app.session_state['observed_interval'])
