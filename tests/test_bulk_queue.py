"""Atomic batch authorization on temporary queue databases; no orders or API."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest import TestCase
from tests import test_automatic_entry_queue as fixtures


class BulkQueueTests(TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        now=self.h.f.now
        self.session=(datetime.fromisoformat(self.h.f.state['session'][0]).date().isoformat(),*self.h.f.state['session'])
        self.rows=[dict(symbol='AAPL',quantity=2,target='20',baseline='a'),
                   dict(symbol='AMZN',quantity=1,target='MANUAL',baseline='b')]

    def arm(self,rows=None):
        return self.h.store.arm_many(self.rows if rows is None else rows,self.session[0],
            now=self.h.f.now,sessions=[self.session],symbols=('AAPL','AMZN','SPCX'))

    def test_preserves_per_company_values_and_never_dispatches(self):
        ids=self.arm();self.assertEqual(len(ids),2)
        plans={p['symbol']:p for p in self.h.store.plans()}
        self.assertEqual((plans['AAPL']['quantity'],plans['AAPL']['target'],plans['AAPL']['baseline_key']),(2,'20','a'))
        self.assertEqual((plans['AMZN']['quantity'],plans['AMZN']['target'],plans['AMZN']['baseline_key']),(1,'MANUAL','b'))
        self.assertTrue(all(p['state']=='ARMED' for p in plans.values()))
        self.assertEqual(self.h.f.engine.ledger.orders(),[])
        self.assertEqual(self.h.store.read('SELECT * FROM queue_attempts'),[])
        self.h.f.client.full_chain.assert_not_called()

    def test_all_approved_symbols_persist_atomically_without_orders(self):
        from automatic_entry_queue import watched_symbols
        from price_ranges import optimal_option_premium
        rows=[]
        for symbol in watched_symbols():
            try:optimal_option_premium(symbol)
            except ValueError:continue
            rows.append(dict(symbol=symbol,quantity=1,target='20'))
        identities=self.h.store.arm_many(rows,self.session[0],now=self.h.f.now,
            sessions=[self.session],symbols=watched_symbols())
        self.assertEqual(len(identities),len(rows))
        self.assertEqual({p['symbol'] for p in self.h.store.plans()},{r['symbol'] for r in rows})
        self.assertEqual(self.h.f.engine.ledger.orders(),[])
        self.assertEqual(self.h.store.read('SELECT * FROM queue_attempts'),[])

    def test_conflict_later_in_batch_rolls_back_earlier_insert(self):
        self.h.arm()
        with self.assertRaisesRegex(ValueError,'QUEUE_ALREADY_ARMED_OR_UNCERTAIN'):self.arm()
        self.assertEqual([p['symbol'] for p in self.h.store.plans()],['AMZN'])

    def test_uncertain_is_not_rearmed_and_failed_batch_leaves_it_intact(self):
        self.h.arm()
        with self.h.store.transaction() as d:d.execute("UPDATE queue_plans SET state='UNCERTAIN'")
        before=self.h.store.plans()
        with self.assertRaises(ValueError):self.arm()
        self.assertEqual(self.h.store.plans(),before)

    def test_invalid_quantity_target_duplicate_or_range_arms_nothing(self):
        variants=[[],[self.rows[0],self.rows[0]],
            [self.rows[0],dict(symbol='AMZN',quantity=0,target='20')],
            [self.rows[0],dict(symbol='AMZN',quantity=1,target='15')],
            [self.rows[0],dict(symbol='SPCX',quantity=1,target='20')]]
        for rows in variants:
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.arm(rows)
            self.assertEqual(self.h.store.plans(),[])

    def test_concurrent_double_submit_only_one_batch_is_saved(self):
        def submit():
            try:return len(self.arm())
            except ValueError:return 0
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:submit(),range(2)))
        self.assertEqual(sorted(results),[0,2]);self.assertEqual(len(self.h.store.plans()),2)


def bulk_test_page():
    import streamlit as st
    from unittest.mock import Mock,patch
    from datetime import datetime,timedelta,timezone
    from automatic_entry_panel import render_automatic_entry_panel
    if st.session_state.get('other_view'):
        st.write('Otra pestaña')
        return
    now=datetime.now(timezone.utc);store=Mock()
    def save(rows,*args,**kwargs):
        st.session_state['saved_rows']=rows
        st.session_state['batch_calls']=st.session_state.get('batch_calls',0)+1
        return ['a','b']
    store.arm_many.side_effect=save
    receipt=lambda state:dict(state=state,checked_at=now.isoformat())
    sessions=[(now.date().isoformat(),now.isoformat(),(now+timedelta(hours=6)).isoformat())]
    tomorrow=now+timedelta(days=1)
    sessions.append((tomorrow.date().isoformat(),tomorrow.isoformat(),(tomorrow+timedelta(hours=6)).isoformat()))
    with patch('automatic_entry_panel.queue_store',return_value=store),\
         patch('automatic_entry_panel.official_sessions',return_value=sessions),\
         patch('automatic_entry_panel.watched_symbols',return_value=st.session_state.get('test_symbols',['AAPL','AMZN'])),\
         patch('automatic_entry_panel.queue_connection',return_value=receipt(st.session_state.get('display_state','CONNECTED'))),\
         patch('automatic_entry_panel.probe_queue_connection',return_value=receipt(st.session_state.get('fresh_state','CONNECTED'))),\
         patch('automatic_entry_panel.read_manual_state',return_value={}),\
         patch('automatic_entry_panel.render_queue_status'):
        render_automatic_entry_panel(embedded=True)


class BulkQueueUITests(TestCase):
    def test_unapplied_common_values_explain_disabled_button(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(bulk_test_page).run(timeout=20)
        app.button(key='auto_bulk_select_all').click().run()
        app.number_input(key='auto_bulk_default_quantity').set_value(1).run()
        app.selectbox(key='auto_bulk_default_target').set_value('20').run()
        self.assertTrue(app.button(key='auto_bulk_arm').disabled)
        self.assertTrue(any('aún no están aplicados' in warning.value for warning in app.warning))
        app.button(key='auto_bulk_apply').click().run()
        self.assertFalse(app.button(key='auto_bulk_arm').disabled)

    def test_all_approved_companies_can_be_saved_after_pending_indicator(self):
        from streamlit.testing.v1 import AppTest
        from automatic_entry_queue import watched_symbols
        from price_ranges import optimal_option_premium
        approved=[]
        for symbol in watched_symbols():
            try:optimal_option_premium(symbol);approved.append(symbol)
            except ValueError:pass
        app=AppTest.from_function(bulk_test_page)
        app.session_state['test_symbols']=list(watched_symbols())
        app.session_state['display_state']='CHECKING'
        app.run(timeout=30)
        app.button(key='auto_bulk_select_all').click().run(timeout=30)
        app.number_input(key='auto_bulk_default_quantity').set_value(1).run(timeout=30)
        app.selectbox(key='auto_bulk_default_target').set_value('20').run(timeout=30)
        app.button(key='auto_bulk_apply').click().run(timeout=30)
        self.assertFalse(app.button(key='auto_bulk_arm').disabled)
        app.checkbox(key='auto_bulk_consent').check().run(timeout=30)
        app.button(key='auto_bulk_arm').click().run(timeout=30)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['batch_calls'],1)
        self.assertEqual([r['symbol'] for r in app.session_state['saved_rows']],approved)

    def prepare(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(bulk_test_page).run(timeout=20)
        app.multiselect(key='auto_bulk_symbols').set_value(['AAPL','AMZN']).run()
        app.number_input(key='auto_bulk_default_quantity').set_value(2).run()
        app.selectbox(key='auto_bulk_default_target').set_value('20').run()
        app.button(key='auto_bulk_apply').click().run()
        return app

    def test_common_then_individual_targets_and_one_submission(self):
        app=self.prepare()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AAPL').value,2)
        app.number_input(key='auto_bulk_quantity_AMZN').set_value(1).run()
        app.selectbox(key='auto_bulk_target_AMZN').set_value('MANUAL').run()
        app.checkbox(key='auto_bulk_consent').check().run()
        app.button(key='auto_bulk_arm').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['batch_calls'],1)
        rows=app.session_state['saved_rows']
        self.assertEqual([(r['symbol'],r['quantity'],r['target']) for r in rows],[('AAPL',2,'20'),('AMZN',1,'MANUAL')])

    def test_submit_follows_live_then_edit_pauses_only_display(self):
        app=self.prepare()
        app.checkbox(key='auto_bulk_consent').check().run()
        app.button(key='auto_bulk_arm').click().run()
        self.assertTrue(app.session_state['auto_queue_follow'])
        app.number_input(key='auto_bulk_quantity_AMZN').set_value(3).run()
        self.assertFalse(app.session_state['auto_queue_follow'])
        self.assertEqual(app.session_state['batch_calls'],1)
        self.assertEqual(app.session_state['saved_rows'][1]['quantity'],2)
        self.assertFalse(app.checkbox(key='auto_bulk_consent').value)

    def test_connection_lost_does_not_save_and_preserves_selection(self):
        app=self.prepare();app.session_state['fresh_state']='AUTHORIZATION_REQUIRED'
        app.checkbox(key='auto_bulk_consent').check().run()
        app.button(key='auto_bulk_arm').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertNotIn('batch_calls',app.session_state)
        self.assertEqual(app.multiselect(key='auto_bulk_symbols').value,['AAPL','AMZN'])
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AAPL').value,2)
        self.assertTrue(any('ninguna' in e.value for e in app.error))

    def test_editing_row_clears_consent_and_incomplete_selection_is_disabled(self):
        app=self.prepare();app.checkbox(key='auto_bulk_consent').check().run()
        app.number_input(key='auto_bulk_quantity_AMZN').set_value(0).run()
        self.assertFalse(app.checkbox(key='auto_bulk_consent').value)
        self.assertTrue(app.button(key='auto_bulk_arm').disabled)

    def test_changing_session_requires_authorization_again(self):
        app=self.prepare();app.checkbox(key='auto_bulk_consent').check().run()
        selector=app.selectbox(key='auto_queue_session')
        selector.select_index(1).run()
        self.assertFalse(app.checkbox(key='auto_bulk_consent').value)
        self.assertNotIn('batch_calls',app.session_state)

    def test_adding_company_inherits_last_applied_values_without_erasing_custom_row(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(bulk_test_page).run(timeout=20)
        app.multiselect(key='auto_bulk_symbols').set_value(['AAPL']).run()
        app.number_input(key='auto_bulk_default_quantity').set_value(2).run()
        app.selectbox(key='auto_bulk_default_target').set_value('20').run()
        app.button(key='auto_bulk_apply').click().run()
        app.number_input(key='auto_bulk_quantity_AAPL').set_value(3).run()
        app.multiselect(key='auto_bulk_symbols').set_value(['AAPL','AMZN']).run()
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AMZN').value,2)
        self.assertEqual(app.selectbox(key='auto_bulk_target_AMZN').value,'20')
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AAPL').value,3)

    def test_switching_mode_restores_draft_and_requires_new_consent(self):
        app=self.prepare();app.number_input(key='auto_bulk_quantity_AMZN').set_value(3).run()
        app.checkbox(key='auto_bulk_consent').check().run()
        app.radio(key='auto_queue_mode').set_value('Una compañía').run()
        app.radio(key='auto_queue_mode').set_value('Varias compañías').run()
        self.assertEqual(app.multiselect(key='auto_bulk_symbols').value,['AAPL','AMZN'])
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AMZN').value,3)
        self.assertFalse(app.checkbox(key='auto_bulk_consent').value)

    def test_target_only_applies_without_overwriting_individual_quantities(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(bulk_test_page).run(timeout=20)
        app.multiselect(key='auto_bulk_symbols').set_value(['AAPL','AMZN']).run()
        app.number_input(key='auto_bulk_quantity_AAPL').set_value(1).run()
        app.number_input(key='auto_bulk_quantity_AMZN').set_value(3).run()
        app.selectbox(key='auto_bulk_default_target').set_value('35').run()
        self.assertFalse(app.button(key='auto_bulk_apply').disabled)
        app.button(key='auto_bulk_apply').click().run()
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AAPL').value,1)
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AMZN').value,3)
        self.assertEqual(app.selectbox(key='auto_bulk_target_AAPL').value,'35')
        self.assertEqual(app.selectbox(key='auto_bulk_target_AMZN').value,'35')

    def test_explicit_target_button_preserves_custom_quantity_even_if_common_quantity_is_set(self):
        app=self.prepare()
        app.number_input(key='auto_bulk_quantity_AMZN').set_value(3).run()
        app.selectbox(key='auto_bulk_default_target').set_value('35').run()
        app.button(key='auto_bulk_apply_target').click().run()
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AAPL').value,2)
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AMZN').value,3)
        self.assertEqual(app.selectbox(key='auto_bulk_target_AAPL').value,'35')
        self.assertEqual(app.selectbox(key='auto_bulk_target_AMZN').value,'35')

    def test_explicit_quantity_button_preserves_custom_targets(self):
        app=self.prepare()
        app.selectbox(key='auto_bulk_target_AMZN').set_value('MANUAL').run()
        app.number_input(key='auto_bulk_default_quantity').set_value(4).run()
        app.button(key='auto_bulk_apply_quantity').click().run()
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AMZN').value,4)
        self.assertEqual(app.selectbox(key='auto_bulk_target_AAPL').value,'20')
        self.assertEqual(app.selectbox(key='auto_bulk_target_AMZN').value,'MANUAL')

    def test_hidden_tab_restores_selection_rows_and_session_without_authorizing(self):
        app=self.prepare();app.selectbox(key='auto_queue_session').select_index(1).run()
        day=app.selectbox(key='auto_queue_session').value
        app.checkbox(key='auto_bulk_consent').check().run()
        app.session_state['other_view']=True;app.run()
        app.session_state['other_view']=False;app.run()
        self.assertEqual(app.multiselect(key='auto_bulk_symbols').value,['AAPL','AMZN'])
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AAPL').value,2)
        self.assertEqual(app.selectbox(key='auto_bulk_target_AMZN').value,'20')
        self.assertEqual(app.selectbox(key='auto_queue_session').value,day)
        self.assertFalse(app.checkbox(key='auto_bulk_consent').value)

    def test_remove_all_then_reselect_keeps_row_adjustments(self):
        app=self.prepare();app.number_input(key='auto_bulk_quantity_AMZN').set_value(3).run()
        app.button(key='auto_bulk_select_none').click().run()
        self.assertEqual(app.multiselect(key='auto_bulk_symbols').value,[])
        app.button(key='auto_bulk_select_all').click().run()
        self.assertEqual(app.multiselect(key='auto_bulk_symbols').value,['AAPL','AMZN'])
        self.assertEqual(app.number_input(key='auto_bulk_quantity_AMZN').value,3)
        self.assertEqual(app.selectbox(key='auto_bulk_target_AMZN').value,'20')
