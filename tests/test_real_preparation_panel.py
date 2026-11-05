"""Isolated dashboard interactions; no credentials, connections or orders."""
from unittest import TestCase
from unittest.mock import Mock
from streamlit.testing.v1 import AppTest


def select_real_tab(app,label):
    app.session_state['real_workspace_view']=label
    return app.run()


def page(initial_view='Preparar compañías'):
    import streamlit as st
    from real_account_readonly import AccountReadOnlySession
    from real_trade_preparation import RealPreparationSession
    from real_preparation_panel import render_real_workspace
    from tests.test_real_account_readonly import client_fixture,NOW
    from tests.test_real_trade_preparation import MemoryPreparationStore
    if 'real_account_reader' not in st.session_state:
        client=client_fixture()
        reader=AccountReadOnlySession(lambda:client,lambda:NOW)
        reference=reader.load_accounts()['choices'][0]['ref']
        reader.load_snapshot(reference)
        store=MemoryPreparationStore()
        st.session_state['real_account_reader']=reader
        st.session_state['real_selected_account_ref']=reference
        st.session_state['real_preparation_service']=RealPreparationSession(store_factory=lambda:store,clock=lambda:NOW)
        st.session_state['test_store']=store
        st.session_state['test_client']=client
        from unittest.mock import Mock
        runtime=Mock(binding=reader.preparation_binding(reference))
        runtime.can_arm.return_value=False;runtime.status.return_value=dict(ready_to_arm=False,blockers=[])
        runtime.queue.read.return_value=None;runtime.positions.return_value=[]
        runtime.trade_history.return_value=[]
        def arm(rows,**kwargs):
            runtime.queue.read.return_value=dict(id='ACTIVATED',paused=False,
                session_open='2099-01-01T14:30:00+00:00',session_close='2099-01-01T21:00:00+00:00',
                rows=[dict(row,id=row['symbol'],state='ARMED') for row in rows])
        runtime.arm.side_effect=arm
        st.session_state['real_execution_runtime']=runtime
        st.session_state['real_workspace_view']=initial_view
    render_real_workspace()


class RealPreparationPanelTests(TestCase):
    def test_paused_queue_displays_confirmed_manual_close_as_closed_without_orders(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        runtime=app.session_state['real_execution_runtime']
        runtime.queue.read.return_value=dict(id='PLAN',paused=True,
            session_open='2099-01-01T14:30:00+00:00',session_close='2099-01-01T21:00:00+00:00',
            rows=[dict(id='AAPL',symbol='AAPL',quantity=1,target='10',state='COMPLETED')])
        runtime.trade_history.return_value=[dict(contract='AAPL TEST CONTRACT',bought=1,sold=1,
            entry_average='1',entered_at='2099-01-01T14:35:00+00:00',state='CLOSED',manual_close=True)]
        select_real_tab(app,'Cola real')
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.dataframe[-1].value.iloc[0]['Estado'],'Cerrada')
        self.assertTrue(any('Compras reales pausadas' in x.value for x in app.warning))
        runtime.arm.assert_not_called();runtime.close_manually.assert_not_called()

    def test_remove_control_withdraws_only_selected_pending_company(self):
        from copy import deepcopy
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        runtime=app.session_state['real_execution_runtime']
        plan=dict(id='PLAN',session_open='2099-01-01T14:30:00+00:00',session_close='2099-01-01T21:00:00+00:00',
            rows=[dict(id=s,symbol=s,state='ARMED',quantity=1,target='10') for s in ('AAPL','DIA')])
        runtime.queue.read.side_effect=lambda binding:deepcopy(plan)
        def remove(plan_id,row_id):
            self.assertEqual(plan_id,'PLAN')
            next(r for r in plan['rows'] if r['id']==row_id)['state']='REMOVED'
        runtime.remove.side_effect=remove
        select_real_tab(app,'Cola real')
        app.selectbox(key='real_queue_remove_choice_PLAN').select('DIA').run()
        app.button(key='real_queue_remove').click().run()
        self.assertEqual(len(app.exception),0)
        runtime.remove.assert_called_once_with('PLAN','DIA')
        self.assertEqual(app.dataframe[-1].value['Compañía'].tolist(),['AAPL'])
        self.assertTrue(any('DIA quitada' in x.value for x in app.success))
        runtime.arm.assert_not_called();runtime.pause.assert_not_called()

    def test_diagnostic_view_does_not_read_broker_or_arm_or_poll_database_on_load(self):
        from unittest.mock import patch
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        client=app.session_state['test_client'];calls=list(client.method_calls)
        runtime=app.session_state['real_execution_runtime']
        with patch('strategy_diagnostics.read_snapshot',side_effect=AssertionError('EXPLICIT_REFRESH_ONLY')):
            select_real_tab(app,'Estado de la estrategia')
        self.assertEqual(len(app.exception),0)
        self.assertEqual(client.method_calls,calls)
        runtime.arm.assert_not_called()
        self.assertTrue(any(x.label=='Actualizar diagnóstico' for x in app.button))

    def test_saved_draft_is_not_shown_as_active_and_queue_has_no_duplicate_buttons(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        service=app.session_state['real_preparation_service']
        reader=app.session_state['real_account_reader'];reference=app.session_state['real_selected_account_ref']
        service.save(reader.preparation_binding(reference),[dict(symbol='AMZN',quantity=2,target='10')])
        calls=list(app.session_state['test_client'].method_calls)
        select_real_tab(app,'Cola real')
        self.assertEqual(len(app.exception),0)
        self.assertFalse(any(b.key in ('real_queue_arm','real_queue_load','real_queue_refresh') for b in app.button))
        self.assertEqual(len(app.dataframe),0)
        app.session_state['real_execution_runtime'].arm.assert_not_called()
        self.assertEqual(app.session_state['test_client'].method_calls,calls)

    def test_editor_activation_saves_and_arms_exact_selection_in_one_explicit_action(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        self.assertNotIn('real_prep_load',[b.key for b in app.button])
        service=app.session_state['real_preparation_service'];reader=app.session_state['real_account_reader']
        binding=reader.preparation_binding(app.session_state['real_selected_account_ref'])
        rows=[dict(symbol='AMZN',quantity=2,target='10')]
        runtime=app.session_state['real_execution_runtime'];runtime.can_arm.return_value=True
        app.multiselect(key='real_prep_symbols').set_value(['AMZN']).run()
        app.number_input(key='real_prep_common_quantity').set_value(2)
        app.selectbox(key='real_prep_common_target').select('10').run()
        app.button(key='real_prep_apply').click().run()
        runtime.arm.assert_not_called()
        app.button(key='real_prep_activate').click().run()
        self.assertEqual(len(app.exception),0);runtime.arm.assert_called_once_with(rows,repeat_new_signals=False,first_entry_only=True)
        self.assertEqual(service.preparation['rows'],rows)
        self.assertEqual(app.session_state['real_workspace_view'],'Cola real')
        self.assertEqual(app.dataframe[0].value.iloc[0]['Estado'],'Bajo el radar')

    def test_option_reauthorization_problem_is_visible_without_arming(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        runtime=app.session_state['real_execution_runtime']
        runtime.status.return_value=dict(ready_to_arm=False,blockers=['LIVE_OPTION_DATA_REAUTHORIZE'])
        select_real_tab(app,'Cola real')
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('reconectar JJTradeAI-Datos' in x.value for x in app.caption))
        self.assertFalse(any(b.key=='real_queue_arm' for b in app.button))
        runtime.arm.assert_not_called()

    def test_removed_proposals_view_migrates_without_fetching_or_arming(self):
        app=AppTest.from_function(page,args=('Propuestas',),default_timeout=20).run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['real_workspace_view'],'Preparar compañías')
        self.assertNotIn('Propuestas',[t.label for t in app.tabs])
        self.assertFalse(any((b.key or '').startswith('real_proposal_') for b in app.button))
        client=app.session_state['test_client'];calls=list(client.method_calls)
        select_real_tab(app,'Cola real')
        self.assertEqual(len(app.exception),0)
        self.assertEqual(client.method_calls,calls)
        app.session_state['real_execution_runtime'].arm.assert_not_called()

    def test_select_all_apply_save_and_switch_view(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        self.assertEqual(len(app.exception),0)
        app.session_state['real_execution_runtime'].can_arm.return_value=True
        app.button(key='real_prep_all').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertGreater(len(app.multiselect(key='real_prep_symbols').value),10)
        self.assertTrue(app.button(key='real_prep_apply').disabled)
        app.number_input(key='real_prep_common_quantity').set_value(2)
        app.selectbox(key='real_prep_common_target').select('20').run()
        app.button(key='real_prep_apply').click().run()
        app.button(key='real_prep_activate').click().run()
        self.assertEqual(len(app.exception),0)
        service=app.session_state['real_preparation_service']
        self.assertTrue(all(r['quantity']==2 and r['target']=='20' for r in service.preparation['rows']))
        self.assertFalse(service.preparation['real_orders_enabled'])
        select_real_tab(app,'Cola real')
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.dataframe[0].value),len(service.preparation['rows']))
        select_real_tab(app,'Preparar compañías')
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.multiselect(key='real_prep_symbols').value),len(service.preparation['rows']))
        app.button(key='real_prep_none').click().run()
        self.assertEqual(app.multiselect(key='real_prep_symbols').value,[])
        self.assertIsNotNone(service.preparation)

    def test_missing_target_cannot_save_and_render_does_not_fetch(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        app.session_state['real_execution_runtime'].can_arm.return_value=True
        client=app.session_state['test_client']
        calls=list(client.method_calls)
        app.multiselect(key='real_prep_symbols').set_value(['AMZN']).run()
        app.button(key='real_prep_activate').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(app.error)
        self.assertIsNone(app.session_state['real_preparation_service'].preparation)
        self.assertEqual(client.method_calls,calls)
        app.session_state['real_execution_runtime'].arm.assert_not_called()

    def test_activation_is_disabled_until_executor_is_ready(self):
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        app.multiselect(key='real_prep_symbols').set_value(['AMZN']).run()
        self.assertTrue(app.button(key='real_prep_activate').disabled)
        app.session_state['real_execution_runtime'].arm.assert_not_called()

    def test_pause_button_becomes_activate_and_resumes_same_plan_without_arming(self):
        from copy import deepcopy
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        runtime=app.session_state['real_execution_runtime'];runtime.can_arm.return_value=True
        plan=dict(id='SAME_PLAN',paused=False,session_open='2099-01-01T14:30:00+00:00',session_close='2099-01-01T21:00:00+00:00',
            rows=[dict(id='AAPL',symbol='AAPL',state='ARMED',quantity=1,target='10')])
        runtime.queue.read.side_effect=lambda binding:deepcopy(plan)
        def pause():plan.update(paused=True);plan['rows'][0]['state']='PAUSED'
        def resume(plan_id):
            self.assertEqual(plan_id,'SAME_PLAN');plan.update(paused=False);plan['rows'][0]['state']='ARMED'
        runtime.pause.side_effect=pause;runtime.resume.side_effect=resume
        select_real_tab(app,'Cola real')
        self.assertEqual(app.button(key='real_queue_toggle').label,'Pausar')
        app.button(key='real_queue_toggle').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.button(key='real_queue_toggle').label,'Activar')
        self.assertEqual(app.dataframe[0].value.iloc[0]['Estado'],'Pausada')
        app.button(key='real_queue_toggle').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.button(key='real_queue_toggle').label,'Pausar')
        self.assertEqual(app.dataframe[0].value.iloc[0]['Estado'],'Bajo el radar')
        runtime.resume.assert_called_once_with('SAME_PLAN');runtime.arm.assert_not_called()

    def test_clear_waiting_keeps_order_in_progress_visible_and_never_closes_it(self):
        from copy import deepcopy
        app=AppTest.from_function(page,default_timeout=20).run(timeout=20)
        runtime=app.session_state['real_execution_runtime']
        plan=dict(id='PLAN',paused=False,entry_owner='ACTIVE',session_open='2099-01-01T14:30:00+00:00',session_close='2099-01-01T21:00:00+00:00',
            rows=[dict(id='ACTIVE',symbol='AAPL',state='ORDER_SENT',request_id='ORDER',claim='USED',quantity=1,target='10'),
                  dict(id='WAITING',symbol='MSFT',state='ARMED',quantity=1,target='10')])
        runtime.queue.read.side_effect=lambda binding:deepcopy(plan)
        def clear(plan_id):plan['rows'][1]['state']='REMOVED';plan['paused']=True
        runtime.remove_waiting.side_effect=clear
        select_real_tab(app,'Cola real')
        app.button(key='real_queue_clear').click().run()
        self.assertEqual(len(app.exception),0)
        runtime.remove_waiting.assert_called_once_with('PLAN')
        self.assertEqual(app.dataframe[0].value['Compañía'].tolist(),['AAPL'])
        self.assertEqual(app.dataframe[0].value.iloc[0]['Estado'],'Operación en seguimiento')
        self.assertIn('vigilando',app.dataframe[0].value.iloc[0]['Seguimiento'])
        runtime.close_manually.assert_not_called();runtime.arm.assert_not_called()
