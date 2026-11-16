"""MA interpretation and shared display never change entry or order decisions."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,sqlite3,tempfile
from pathlib import Path
from unittest import TestCase

from ma_price_outlook import outlook,summary
from ma_outlook_panel import read_outlooks


def context():
    frames=[]
    for timeframe in ('1H','1D'):
        frames.append(dict(timeframe=timeframe,last_closed_at='2026-11-06T14:30:00+00:00',
            averages={'20':99,'40':98,'100':105,'200':110},
            slopes={'20':.2,'40':.1,'100':-.1,'200':-.1},
            pairs=[dict(periods=[20,40],validated=True,sessions_since_cross=3,phase='CORTO_PLAZO'),
                   dict(periods=[100,200],validated=True)]))
    levels=[dict(timeframe='1H',period=20,value=99,role='APOYO_POR_DETRAS'),
        dict(timeframe='1H',period=100,value=105,role='POSIBLE_TECHO'),
        dict(timeframe='1D',period=40,value=102,role='POSIBLE_CONTINUIDAD_ALCISTA'),
        dict(timeframe='1D',period=200,value=110,role='POSIBLE_TECHO')]
    return dict(state='DESCRIPTIVO',ma_type='SMA',price=100,
        available_at='2026-11-09T14:30:00+00:00',frames=frames,levels=levels)


class OutlookTests(TestCase):
    def test_forward_favorable_ma_is_not_automatically_a_limit(self):
        c=context();original=deepcopy(c);result=outlook(c,'SUPERIOR')
        self.assertEqual(c,original)
        self.assertEqual(result['reading'],'ALCISTA');self.assertTrue(result['aligned_with_signal'])
        self.assertEqual(result['route'][0]['value'],102)
        self.assertEqual(result['nearest_limit']['value'],105)
        self.assertEqual(result['behind'][0]['value'],99)
        self.assertIn('100/200 bajista',summary(result))

    def test_put_route_is_reversed_and_distances_use_original_signal_price(self):
        c=context();c['levels'] += [dict(timeframe='1D',period=100,value=95,role='POSIBLE_PISO')]
        for level in c['levels']:level['distance_pct']=999
        result=outlook(c,'INFERIOR')
        self.assertEqual([r['value'] for r in result['route']],[99,95])
        self.assertEqual(result['route'][0]['distance_pct'],1)
        self.assertEqual(result['nearest_limit']['value'],95)
        self.assertFalse(result['aligned_with_signal'])

    def test_hour_day_conflict_is_not_an_aligned_entry(self):
        c=context();f=c['frames'][1]
        f['averages'].update({'20':97,'40':98});f['slopes'].update({'20':-.2,'40':-.1})
        result=outlook(c,'SUPERIOR')
        self.assertEqual(result['reading'],'HORA_DIARIO_EN_CONFLICTO')
        self.assertIsNone(result['aligned_with_signal'])

    def test_missing_long_history_is_explicit_and_no_new_level_is_invented(self):
        c=context();c['frames'][1]['averages']['200']=None;c['levels']=[]
        result=outlook(c,'SUPERIOR')
        self.assertFalse(result['complete']);self.assertIsNone(result['nearest_limit'])
        self.assertEqual(result['route'],[])
        self.assertIn('Faltan datos',summary(result))

    def test_absent_or_invalid_context_never_becomes_a_price_prediction(self):
        for c in (None,{},dict(state='DESCRIPTIVO',price=float('nan')),dict(state='DESCRIPTIVO',price=True)):
            self.assertEqual(outlook(c,'SUPERIOR')['state'],'SIN_DATOS')
        c=context();c['frames'][1]['slopes']['20']=None
        self.assertEqual(outlook(c,'SUPERIOR')['reading'],'PARCIAL_ALCISTA')
        self.assertIsNone(outlook(c,'SUPERIOR')['aligned_with_signal'])

    def test_read_saved_only_current_day_version_no_future_or_production_writes(self):
        from bollinger_phone_worker import STRATEGY_VERSION
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'market.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('create table bollinger_live_events(detected_at text,payload_json text)')
                def put(symbol,stamp,**extra):
                    c=context();c['available_at']=stamp
                    e=dict(symbol=symbol,version=STRATEGY_VERSION,side='SUPERIOR',source_kind='TRADE',
                        source_timestamp=stamp,price=100,ma_context=c,**extra)
                    db.execute('insert into bollinger_live_events values(?,?)',(stamp,json.dumps(e)))
                put('AAPL','2026-11-09T14:30:00+00:00')
                put('QQQ','2026-11-10T14:30:00+00:00')
                put('SPY','2026-11-06T14:30:00+00:00')
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            result=read_outlooks(path,['AAPL','QQQ','SPY'],datetime(2026,11,9,15,tzinfo=timezone.utc))
            self.assertTrue(result['available']);self.assertEqual([e['symbol'] for e in result['events']],['AAPL'])
            self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_shared_panel_renders_without_broker_or_market_calculation(self):
        from streamlit.testing.v1 import AppTest
        def page(value):
            import streamlit as st
            from ma_outlook_panel import render_outlook
            render_outlook(value,st=st)
        app=AppTest.from_function(page,args=(outlook(context(),'SUPERIOR'),)).run(timeout=15)
        self.assertEqual(len(app.exception),0,str(app.exception))
        text='\n'.join(v.value for v in app.markdown)
        self.assertIn('Hora y Diario acompañan',text)
        self.assertEqual(len(app.dataframe),2)

    def test_future_context_cannot_replace_missing_latest_or_resurrect_old_context(self):
        from bollinger_phone_worker import STRATEGY_VERSION
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'market.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('create table bollinger_live_events(detected_at text,payload_json text)')
                for minute in (30,40):
                    source=f'2026-11-09T14:{minute}:00+00:00'
                    c=context()
                    if minute==40:c['available_at']='2026-11-09T14:41:00+00:00'
                    e=dict(symbol='AAPL',version=STRATEGY_VERSION,side='SUPERIOR',source_kind='TRADE',
                        source_timestamp=source,price=100,ma_context=c)
                    db.execute('insert into bollinger_live_events values(?,?)',(source,json.dumps(e)))
            result=read_outlooks(path,['AAPL'],datetime(2026,11,9,15,tzinfo=timezone.utc))
            self.assertEqual(len(result['events']),1)
            self.assertIn('14:40',result['events'][0]['source_timestamp'])
            self.assertEqual(result['events'][0]['outlook']['state'],'SIN_DATOS')

    def test_real_diagnostic_refresh_shows_saved_ma_reading(self):
        from streamlit.testing.v1 import AppTest
        def page(value):
            from unittest.mock import patch
            from tests.test_strategy_diagnostics import snapshot,NOW
            from strategy_diagnostics_panel import render_strategy_diagnostics
            saved=dict(available=True,events=[dict(symbol='QQQ',feed='iex',
                source_timestamp=NOW.isoformat(),outlook=value)])
            with patch('strategy_diagnostics.read_snapshot',return_value=snapshot()), \
                 patch('ma_outlook_panel.read_outlooks',return_value=saved):
                render_strategy_diagnostics(['QQQ'],now=NOW)
        app=AppTest.from_function(page,args=(outlook(context(),'SUPERIOR'),)).run(timeout=15)
        app.button(key='strategy_diagnostic_refresh').click().run(timeout=15)
        self.assertEqual(len(app.exception),0,str(app.exception))
        text='\n'.join(v.value for v in app.markdown)
        self.assertIn('Hora y Diario acompañan',text)
        self.assertEqual([b.label for b in app.button],['Actualizar diagnóstico'])

    def test_read_failure_is_not_mislabeled_as_absent_history(self):
        from streamlit.testing.v1 import AppTest
        def page():
            import streamlit as st
            from ma_outlook_panel import render_saved_outlooks
            render_saved_outlooks(dict(available=False,events=[]),st=st)
        app=AppTest.from_function(page).run(timeout=15)
        self.assertEqual(len(app.warning),1)
        self.assertEqual(len(app.info),0)
