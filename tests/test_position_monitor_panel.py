"""Mobile view and readonly service on isolated synthetic positions."""
from pathlib import Path
import tempfile
import unittest
from streamlit.testing.v1 import AppTest


def monitor_page(root,profit='35'):
    from copy import deepcopy
    from datetime import timedelta
    from decimal import Decimal
    from pathlib import Path
    from unittest.mock import Mock,patch
    import streamlit as st
    from manual_execution import ManualWorkflow,ManualReviews
    from manual_execution_panel import render_manual_positions
    from manual_trade_service import ManualMarketData
    from schwab_simulation import SimulationEngine,SimulationLedger,LocalPaperBroker
    from tests.test_manual_trade_service import state_fixture,payload_fixture
    from tests import test_schwab_simulation as f
    root=Path(root);q=f.synthetic_contract();state=state_fixture()
    client=Mock();payload=payload_fixture();client.full_chain.return_value=payload
    market=ManualMarketData(client,verified_increments={q.snapshot.symbol:'.05'},fee_per_contract='.65')
    engine=SimulationEngine(SimulationLedger(root/'ledger.db'),LocalPaperBroker(root/'broker.db'),
        f.synthetic_policy(stop_loss_pct=Decimal('10')))
    workflow=ManualWorkflow(engine,ManualReviews(root/'reviews.db'),read_state=lambda s:deepcopy(state),
        market_data=market,clock=lambda:f.NOW)
    if not engine.ledger.orders():
        review=workflow.prepare_buy('test','AMZN','CALL',q.snapshot.symbol,3,profit)
        key=workflow.confirm('test',review['id'])['client_key']
        engine.broker.match_quote(engine.ledger.order(key)['broker_id'],q,now=f.NOW,execution_id='SYNTHETIC_VIEW_FILL')
        engine.reconcile(f.NOW)
    mode=st.selectbox('Estado de prueba',['Vigente','Anterior','Sin conexión','Cerrado'])
    payload['callExpDateMap']['2026-10-23:7']['100.0'][0].update(bid=2.30,ask=2.35)
    if mode=='Anterior':
        payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['quoteTimeInLong']=int((f.NOW-timedelta(seconds=31)).timestamp()*1000)
    if mode=='Sin conexión':client.full_chain.side_effect=RuntimeError('SYNTHETIC_PRIVATE_DETAIL')
    if mode=='Cerrado':state['session']=None
    market.cache.clear()
    with patch('socket.socket.connect',side_effect=AssertionError('No actual network')), \
         patch('manual_trade_panel._render_manual_chart') as chart:
        chart.__wrapped__=Mock(side_effect=lambda *a,**k:st.caption('Gráfico de acción de prueba'))
        render_manual_positions.__wrapped__(workflow=workflow,owner='test')
        st.session_state['stock_chart_calls']=chart.__wrapped__.call_count
    st.session_state['orders']=len(engine.ledger.orders())


class PositionMonitorPanelTests(unittest.TestCase):
    def test_fractional_vwap_and_stop_are_not_silently_rounded_to_cents(self):
        from decimal import Decimal
        from position_monitor_panel import _premium
        self.assertEqual(_premium(Decimal('1.58666666666666666666666')),'≈$1.586667')
        self.assertEqual(_premium(Decimal('1.98333333333333333333333')),'≈$1.983333')
        self.assertEqual(_premium(Decimal('2.30')),'$2.30')
        self.assertEqual(_premium(Decimal('0')),'$0.00')

    def page(self,root,**kwargs):
        p=AppTest.from_function(monitor_page,kwargs={'root':str(root),**kwargs}).run(timeout=30)
        self.assertEqual(len(p.exception),0,str(p.exception));return p

    def test_metrics_levels_chart_and_manual_close_remain_together(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root);metrics={m.label:m for m in p.metric}
            self.assertEqual(metrics['Bid actual'].value,'$2.30')
            self.assertEqual(metrics['Ganancia / pérdida bruta estimada'].value,'$90.00')
            self.assertEqual(metrics['Ganancia / pérdida bruta estimada'].delta,'+15.00%')
            self.assertEqual(metrics['Resultado neto estimado'].value,'$86.10')
            self.assertEqual(metrics['Objetivo de venta'].value,'$2.70')
            self.assertEqual(metrics['Umbral del stop'].value,'$1.80')
            self.assertEqual(p.button[0].label,'Cerrar posición simulada');self.assertEqual(p.session_state['orders'],1)
            self.assertEqual(p.session_state['stock_chart_calls'],0)
            p.checkbox[0].check().run();self.assertEqual(len(p.exception),0,str(p.exception))
            self.assertEqual(p.session_state['stock_chart_calls'],1)
            self.assertEqual(p.session_state['orders'],1)

    def test_stale_closed_and_outage_clear_profit_without_losing_manual_close(self):
        for mode in ('Anterior','Sin conexión','Cerrado'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                p=self.page(root);p.selectbox[0].set_value(mode).run()
                self.assertEqual(len(p.exception),0,str(p.exception))
                metrics={m.label:m.value for m in p.metric}
                self.assertEqual(metrics['Ganancia / pérdida bruta estimada'],'—')
                self.assertIn('Último Bid · no vigente',metrics)
                self.assertEqual(metrics['Último Bid · no vigente'],'$2.30')
                self.assertEqual(p.button[0].label,'Cerrar posición simulada')
                self.assertFalse(any('SYNTHETIC_PRIVATE_DETAIL' in info.value for info in p.info))
                self.assertEqual(p.session_state['orders'],1)

    def test_manual_profit_has_no_target_but_retains_stop(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root,profit='MANUAL');metrics={m.label:m.value for m in p.metric}
            self.assertEqual(metrics['Objetivo de venta'],'Cierre manual')
            self.assertEqual(metrics['Umbral del stop'],'$1.80')


if __name__=='__main__':unittest.main()
