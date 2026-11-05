"""Results navigation/filters are read-only and do not operate the queue."""
from tests.test_real_preparation_panel import select_real_tab
from unittest import TestCase
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from tests.test_real_preparation_panel import page
from tests.test_real_operation_results import trade,NOW
from real_operation_results import operation_results


class ResultPanelTests(TestCase):
    def test_won_lost_navigation_and_filters_never_operate_or_fetch_broker(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        runtime=app.session_state['real_execution_runtime'];client=app.session_state['test_client']
        calls=list(client.method_calls)
        report=operation_results(trade('win')+trade('loss',sell='.40'),now=NOW)
        with patch('real_results_panel.load_operation_results',return_value=report):
            select_real_tab(app,'Operaciones y resultados')
            self.assertEqual(len(app.exception),0)
            self.assertEqual(next(m.value for m in app.metric if m.label=='Ganadas'),'1')
            self.assertEqual(next(m.value for m in app.metric if m.label=='Perdidas'),'1')
            app.selectbox(key='real_results_filter').select('Perdidas').run()
            self.assertEqual(len(app.exception),0)
            labels=[m.value for m in app.markdown]
            self.assertTrue(any('· Perdida' in value for value in labels))
            self.assertFalse(any('· Ganada' in value for value in labels))
            app.radio(key='real_results_period').set_value('Todo el historial').run()
        self.assertEqual(client.method_calls,calls)
        runtime.arm.assert_not_called();runtime.pause.assert_not_called();runtime.close_manually.assert_not_called()

    def test_missing_account_and_unavailable_history_do_not_invent_totals(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        with patch('real_results_panel.load_operation_results',side_effect=RuntimeError('PRIVATE_STORAGE')):
            select_real_tab(app,'Operaciones y resultados')
            self.assertEqual(len(app.exception),0);self.assertTrue(app.error);self.assertEqual(len(app.metric),0)
            self.assertFalse(any('PRIVATE_STORAGE' in e.value for e in app.error))
        app.session_state['real_selected_account_ref']=None
        with patch('real_results_panel.load_operation_results') as load:
            app.run();load.assert_not_called()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any(b.label=='Consultar mi cuenta' for b in app.button))
