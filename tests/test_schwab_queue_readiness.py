from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import Mock
from schwab_connection import SchwabError
from schwab_queue_readiness import probe_queue_connection, connection_is_recent

NOW = datetime(2026, 10, 26, 17, tzinfo=timezone.utc)


def queue_test_page():
    import streamlit as st
    from unittest.mock import Mock, patch
    from datetime import datetime, timezone, timedelta
    from automatic_entry_panel import render_automatic_entry_panel
    now = datetime.now(timezone.utc)
    store = Mock()
    store.arm.side_effect = lambda *a, **k: st.session_state.update(armed=st.session_state.get('armed',0)+1)
    result = {'state':st.session_state.get('display_state','CONNECTED'),'checked_at':now.isoformat()}
    fresh = {'state':st.session_state.get('fresh_state','CONNECTED'),'checked_at':now.isoformat()}
    sessions = [(now.date().isoformat(), now.isoformat(), (now+timedelta(hours=6)).isoformat())]
    with patch('automatic_entry_panel.queue_store',return_value=store), \
         patch('automatic_entry_panel.official_sessions',return_value=sessions), \
         patch('automatic_entry_panel.watched_symbols',return_value=['AAPL']), \
         patch('automatic_entry_panel.queue_connection',return_value=result), \
         patch('automatic_entry_panel.probe_queue_connection',return_value=fresh), \
         patch('automatic_entry_panel.read_manual_state',return_value={}), \
         patch('automatic_entry_panel.render_queue_status',side_effect=lambda s: st.write('Queue preserved')):
        render_automatic_entry_panel(embedded=True)


class QueueConnectionTests(TestCase):
    def test_requires_authenticated_quotes_and_exposes_no_payload(self):
        market = Mock()
        market.client.quotes.return_value = {'AAPL': {'private':'SYNTHETIC'}, 'SPY': {'quote':{}}}
        result = probe_queue_connection(market_factory=lambda: market, clock=lambda: NOW)
        self.assertEqual(result, {'state':'CONNECTED', 'checked_at':NOW.isoformat()})
        market.client.quotes.assert_called_once_with(['AAPL','SPY'], NOW)
        self.assertNotIn('SYNTHETIC', str(result))

    def test_unauthorized_is_distinct_from_transport_failure(self):
        for code, expected in [('REAUTHORIZATION_REQUIRED','AUTHORIZATION_REQUIRED'),
                               ('TRANSPORT_FAILURE','UNAVAILABLE')]:
            market = Mock();market.client.quotes.side_effect = SchwabError(code)
            result = probe_queue_connection(market_factory=lambda: market, clock=lambda: NOW)
            self.assertEqual(result['state'], expected)

    def test_partial_response_does_not_enable_arming(self):
        market = Mock(); market.client.quotes.return_value = {'AAPL': {'quote':{}}}
        result = probe_queue_connection(market_factory=lambda: market, clock=lambda: NOW)
        self.assertFalse(connection_is_recent(result, NOW))

    def test_stale_future_and_naive_receipts_cannot_authorize_queue(self):
        for stamp in (NOW-timedelta(seconds=31), NOW+timedelta(seconds=1), NOW.replace(tzinfo=None)):
            self.assertFalse(connection_is_recent({'state':'CONNECTED','checked_at':stamp.isoformat()}, NOW))
        self.assertTrue(connection_is_recent({'state':'CONNECTED','checked_at':NOW.isoformat()}, NOW))

    def test_unexpected_error_never_exposes_secret(self):
        result = probe_queue_connection(market_factory=Mock(side_effect=ValueError('SYNTHETIC_PRIVATE')), clock=lambda: NOW)
        self.assertEqual(result['state'],'UNAVAILABLE')
        self.assertNotIn('SYNTHETIC',str(result))

    def test_ui_shows_disconnected_before_arming(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_function(queue_test_page)
        app.session_state['auto_queue_mode']='Una compañía'
        app.session_state['display_state'] = 'AUTHORIZATION_REQUIRED'
        app.run(timeout=20)
        self.assertEqual(len(app.exception),0)
        # Viewing receipt never authorizes a write; the submit always checks fresh.
        self.assertFalse(app.button(key='auto_queue_arm').disabled)
        self.assertTrue(any('renovar' in e.value for e in app.error))

    def test_ui_rechecks_on_submit_and_does_not_arm_if_connection_was_lost(self):
        from streamlit.testing.v1 import AppTest
        for fresh, expected in [('CONNECTED',1), ('AUTHORIZATION_REQUIRED',0)]:
            app = AppTest.from_function(queue_test_page)
            app.session_state['auto_queue_mode']='Una compañía'
            app.run(timeout=20)
            app.number_input(key='auto_queue_quantity').set_value(1).run()
            app.selectbox(key='auto_queue_target').set_value('20').run()
            app.checkbox(key='auto_queue_consent').check().run()
            app.session_state['fresh_state'] = fresh
            app.button(key='auto_queue_arm').click().run(timeout=20)
            self.assertEqual(len(app.exception),0)
            self.assertEqual(app.session_state['armed'] if 'armed' in app.session_state else 0,expected)
