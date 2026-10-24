"""Focused home navigation and current-signal projection on isolated data."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_live import read_live_strategies
from tests.test_manual_trade_service import state_fixture
from tests.test_schwab_simulation import NOW


def home_page():
    import streamlit as st
    from unittest.mock import patch
    from dashboard_home import render_dashboard_home
    with patch('dashboard_live.render_live_strategies',side_effect=lambda:st.write('LIVE_ONLY')), \
         patch('automatic_entry_panel.render_automatic_entry_panel',side_effect=lambda **kw:st.write('QUEUE_ONLY')), \
         patch('operation_results_panel.render_operation_results',side_effect=lambda **kw:st.write('HISTORY_ONLY')):
        render_dashboard_home()


class DashboardHomeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'isolated.db'
        self.state=state_fixture()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('CREATE TABLE market_sessions(session_date TEXT,opens_at TEXT,closes_at TEXT);'
                'CREATE TABLE bollinger_tick_runtime(id INTEGER,state TEXT,heartbeat TEXT,feed TEXT,symbols_json TEXT);'
                'CREATE TABLE bollinger_tick_latest(symbol TEXT,payload_json TEXT);')
            db.execute('INSERT INTO market_sessions VALUES(?,?,?)',('2026-10-16',*self.state['session']))
            db.execute('INSERT INTO bollinger_tick_runtime VALUES(1,?,?,?,?)',('CONECTADO',NOW.isoformat(),'iex','["AMZN"]'))
            db.execute('INSERT INTO bollinger_tick_latest VALUES(?,?)',('AMZN',json.dumps(self.state['tick'])))

    def read(self,now=NOW):
        before=self.path.read_bytes();view=read_live_strategies(self.path,now=now,symbols=['AMZN'])
        self.assertEqual(before,self.path.read_bytes());return view

    def test_live_view_reuses_current_gate_and_does_not_read_old_notifications(self):
        view=self.read();self.assertEqual(view['state'],'LIVE');self.assertEqual(len(view['entries']),1)
        self.assertEqual(view['entries'][0]['signal']['side'],'SUPERIOR')
        self.assertEqual(self.read(now=NOW+timedelta(seconds=4))['entries'],[])
        self.assertEqual(self.read(now=NOW-timedelta(seconds=1))['entries'],[])

    def test_retracted_quarantined_disconnected_and_closed_do_not_show_live_signals(self):
        for kind in ('retracted','quarantined','disconnected','closed'):
            state=deepcopy(self.state);runtime='CONECTADO'
            if kind=='retracted':state['tick']['signal']=None
            if kind=='quarantined':state['tick']['reason']='CORRECTION_QUARANTINE'
            if kind=='disconnected':runtime='RECONECTANDO'
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE bollinger_tick_latest SET payload_json=?',(json.dumps(state['tick']),))
                db.execute('UPDATE bollinger_tick_runtime SET state=?',(runtime,))
            with self.subTest(kind=kind):
                now=NOW.replace(hour=21) if kind=='closed' else NOW
                self.assertEqual(self.read(now=now)['entries'],[])

    def test_exactly_three_tabs_and_only_selected_panel_executes(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(home_page).run(timeout=15)
        self.assertEqual(len(app.exception),0)
        self.assertEqual([t.label for t in app.tabs],['Estrategia en Vivo','Operar Automáticamente','Mis operaciones'])
        text=' '.join(m.value for m in app.markdown)
        self.assertIn('LIVE_ONLY',text);self.assertNotIn('QUEUE_ONLY',text);self.assertNotIn('HISTORY_ONLY',text)
        for slug,marker,absent in [('automatico','QUEUE_ONLY','LIVE_ONLY'),('operaciones','HISTORY_ONLY','QUEUE_ONLY')]:
            app.query_params['vista']=slug;app.run(timeout=15)
            self.assertEqual(len(app.exception),0);text=' '.join(m.value for m in app.markdown)
            self.assertIn(marker,text);self.assertNotIn(absent,text)

    def test_existing_queue_and_results_links_select_corresponding_tab(self):
        from streamlit.testing.v1 import AppTest
        for param,marker in [('automaticas','QUEUE_ONLY'),('resultados','HISTORY_ONLY')]:
            app=AppTest.from_function(home_page);app.query_params[param]='1';app.run(timeout=15)
            self.assertEqual(len(app.exception),0)
            self.assertTrue(any(marker in m.value for m in app.markdown))


if __name__=='__main__':unittest.main()
