"""Mode navigation cannot activate a broker, workers, or an operational panel."""
import unittest
from streamlit.testing.v1 import AppTest


def mode_page():
    import streamlit as st
    from unittest.mock import patch
    import app
    # The welcome/real page must not even ask for access to the active DB.
    with patch('socket.socket.connect', side_effect=AssertionError('NETWORK_FORBIDDEN')), \
         patch('sqlite_runtime_guard.require_safe_wal_runtime') as guard, \
         patch('dashboard_home.render_dashboard_home',
               side_effect=lambda **kw: st.write('SIMULATION_DASHBOARD')), \
         patch.object(app, '_render_dashboard_visuals',
                      side_effect=lambda: st.write('EXISTING_BRAND')):
        app.main()
        st.session_state['guard_calls'] = guard.call_count


class OperatingModePageTests(unittest.TestCase):
    def run_page(self, **params):
        page = AppTest.from_function(mode_page)
        page.query_params.update(params)
        page.run(timeout=25)
        self.assertEqual(len(page.exception), 0, str(page.exception))
        return page

    def test_first_page_then_simulation_and_back(self):
        page = self.run_page()
        self.assertEqual(page.session_state['guard_calls'], 0)
        self.assertEqual([b.label for b in page.button],
                         ['Operar en Real', 'Operar en Simulación'])
        page.button(key='jj_select_simulation').click().run(timeout=25)
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.query_params['modo'], 'simulacion')
        self.assertTrue(any(m.value == 'SIMULATION_DASHBOARD' for m in page.markdown))
        page.button(key='jj_mode_back').click().run(timeout=25)
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.session_state['guard_calls'], 0)
        self.assertIn('jj_select_simulation', [b.key for b in page.button])

    def test_real_is_informational_and_cannot_reach_dashboard(self):
        page = self.run_page()
        page.button(key='jj_select_real').click().run(timeout=25)
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.session_state['guard_calls'], 0)
        self.assertTrue(any('no está habilitado' in i.value for i in page.info))
        self.assertFalse(any(m.value == 'SIMULATION_DASHBOARD' for m in page.markdown))
        page.button(key='jj_real_to_simulation').click().run(timeout=25)
        self.assertEqual(len(page.exception), 0)
        self.assertTrue(any(m.value == 'SIMULATION_DASHBOARD' for m in page.markdown))

    def test_existing_telegram_dashboard_link_enters_simulation(self):
        page = self.run_page(resultados='1')
        self.assertEqual(page.query_params['resultados'], '1')
        self.assertEqual(page.query_params['modo'], 'simulacion')
        self.assertTrue(any(m.value == 'SIMULATION_DASHBOARD' for m in page.markdown))

    def test_real_overrides_operational_link_and_unknown_mode_returns_home(self):
        page = self.run_page(modo='real', operar='AAPL', operaciones='1')
        self.assertEqual(page.session_state['guard_calls'], 0)
        self.assertFalse(any(m.value == 'SIMULATION_DASHBOARD' for m in page.markdown))
        page = self.run_page(modo='unexpected', vista='automatico')
        self.assertEqual(page.session_state['guard_calls'], 0)
        self.assertIn('jj_select_simulation', [b.key for b in page.button])


if __name__ == '__main__':
    unittest.main()
