from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import json,sqlite3

from strategy_diagnostics import describe,read_snapshot
from bollinger_phone_worker import STRATEGY_VERSION

NOW=datetime(2026,11,2,15,tzinfo=timezone.utc)

def snapshot():
    return dict(available=True,captured_at=NOW.isoformat(),runtime=dict(state='CONECTADO',heartbeat=NOW.isoformat(),feed='iex'),
        session=[NOW.isoformat(),(NOW+timedelta(hours=6)).isoformat()],ticks={'QQQ':dict(symbol='QQQ',
        version=STRATEGY_VERSION,feed='iex',source_timestamp=NOW.isoformat(),reason='EXIT',signal=dict(side='SUPERIOR'),
        geometry=dict(upper=203,lower=97,previous_upper=200,previous_lower=100,
            mid=150.5,previous_mid=150,opening=150,price=204))})

class StrategyDiagnosticsTests(TestCase):
    def test_each_band_three_and_reflected_direction(self):
        s=snapshot();before=deepcopy(s)
        r=describe(s,'QQQ',NOW)
        self.assertEqual(r['status'],'GEOMETRY_MATCH');self.assertEqual(r['missing'],[])
        self.assertEqual(r['upper_pct'],3);self.assertEqual(r['lower_pct'],3)
        g=s['ticks']['QQQ']['geometry'];g.update(price=96,mid=149.5)
        s['ticks']['QQQ']['signal']['side']='INFERIOR'
        self.assertEqual(describe(s,'QQQ',NOW)['geometry_side'],'INFERIOR')
        self.assertEqual(before,snapshot())

    def test_weak_opposite_band_and_outside_open_explained(self):
        s=snapshot();s['ticks']['QQQ']['geometry']['lower']=97.01
        r=describe(s,'QQQ',NOW)
        self.assertIn('lower_expansion',r['missing']);self.assertIsNone(r['geometry_side'])
        self.assertNotEqual(r['status'],'GEOMETRY_MATCH')
        s=snapshot();s['ticks']['QQQ']['geometry']['opening']=204
        self.assertIn('opening_inside',describe(s,'QQQ',NOW)['missing'])

    def test_geometry_never_overrides_freshness_or_session_or_quarantine(self):
        for delta,status in [(4,'TRADE_NOT_CURRENT'),(-1,'TRADE_NOT_CURRENT')]:
            s=snapshot();s['ticks']['QQQ']['source_timestamp']=(NOW-timedelta(seconds=delta)).isoformat()
            r=describe(s,'QQQ',NOW);self.assertEqual(r['status'],status)
            self.assertEqual(r['geometry_side'],'SUPERIOR')
        s=snapshot();s['session'][1]=NOW.isoformat()
        self.assertEqual(describe(s,'QQQ',NOW)['status'],'OUTSIDE_SESSION')
        s=snapshot();s['ticks']['QQQ']['reason']='CORRECTION_QUARANTINE'
        self.assertEqual(describe(s,'QQQ',NOW)['status'],'DETECTOR_NOT_EXIT')
        s=snapshot();s['runtime']['heartbeat']=(NOW-timedelta(seconds=4)).isoformat()
        self.assertEqual(describe(s,'QQQ',NOW)['status'],'COLLECTOR_NOT_CURRENT')

    def test_invalid_and_mismatched_evidence_is_never_current(self):
        for key,value in [('upper',float('nan')),('previous_upper',100),('opening',None)]:
            s=snapshot();s['ticks']['QQQ']['geometry'][key]=value
            self.assertEqual(describe(s,'QQQ',NOW)['status'],'INVALID_OR_INCOMPLETE')
        s=snapshot();s['ticks']['QQQ']['version']='old'
        self.assertEqual(describe(s,'QQQ',NOW)['status'],'VERSION_MISMATCH')
        s=snapshot();s['runtime']['feed']='sip'
        self.assertEqual(describe(s,'QQQ',NOW)['status'],'FEED_MISMATCH')
        s=snapshot();s['ticks']['QQQ']['signal']['side']='INFERIOR'
        self.assertEqual(describe(s,'QQQ',NOW)['status'],'DETECTOR_MISMATCH')

    def test_read_only_snapshot_and_missing_database_does_not_create(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'market.db'
            self.assertFalse(read_snapshot(path,['QQQ'],NOW)['available']);self.assertFalse(path.exists())
            with sqlite3.connect(path) as db:
                db.executescript('CREATE TABLE bollinger_tick_runtime(id,state,heartbeat,feed);'
                    'CREATE TABLE market_sessions(session_date,opens_at,closes_at);'
                    'CREATE TABLE bollinger_tick_latest(symbol,payload_json);')
                s=snapshot();db.execute('INSERT INTO bollinger_tick_runtime VALUES(1,?,?,?)',('CONECTADO',NOW.isoformat(),'iex'))
                db.execute('INSERT INTO market_sessions VALUES(?,?,?)',('2026-11-02',*s['session']))
                db.execute('INSERT INTO bollinger_tick_latest VALUES(?,?)',('QQQ',json.dumps(s['ticks']['QQQ'])))
            db.close()
            before=path.read_bytes();r=read_snapshot(path,['QQQ'],NOW)
            self.assertEqual(describe(r,'QQQ',NOW)['status'],'GEOMETRY_MATCH')
            self.assertEqual(path.read_bytes(),before)
            for symbols in ([],['QQQ;DROP TABLE'],['X'+str(i) for i in range(31)]):
                with self.assertRaises(ValueError):read_snapshot(path,symbols,NOW)


def diagnostic_page():
    from tests.test_strategy_diagnostics import snapshot,NOW
    from unittest.mock import patch
    from strategy_diagnostics_panel import render_strategy_diagnostics
    with patch('strategy_diagnostics.read_snapshot',return_value=snapshot()) as reader:
        render_strategy_diagnostics(['QQQ'],now=NOW)
        import streamlit as st
        st.session_state['diagnostic_reads']=reader.call_count

class DiagnosticPanelTests(TestCase):
    def test_refresh_is_explicit_and_contains_no_order_buttons(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_function(diagnostic_page,default_timeout=15).run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['diagnostic_reads'],0)
        app.button(key='strategy_diagnostic_refresh').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['diagnostic_reads'],1)
        self.assertEqual(app.dataframe[0].value.iloc[0]['Superior %'],3)
        app.run();self.assertEqual(app.session_state['diagnostic_reads'],0)
        self.assertEqual([b.label for b in app.button],['Actualizar diagnóstico'])
