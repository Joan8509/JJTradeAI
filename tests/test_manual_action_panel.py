"""Streamlit confirmation controls with isolated synthetic broker, never network."""
from pathlib import Path
import tempfile
import unittest
from streamlit.testing.v1 import AppTest


def action_page(root,kind='buy'):
    from dataclasses import replace
    from datetime import datetime
    from decimal import Decimal
    from pathlib import Path
    from unittest.mock import Mock,patch
    import streamlit as st
    from manual_execution import ManualWorkflow,ManualReviews
    from manual_execution_panel import render_entry_actions,render_manual_positions
    from manual_trade_service import ManualMarketData
    from schwab_simulation import SimulationEngine,SimulationLedger,LocalPaperBroker
    from tests.test_manual_trade_service import state_fixture,payload_fixture
    from tests import test_schwab_simulation as f
    root=Path(root)
    client=Mock();client.full_chain.return_value=payload_fixture()
    contract=f.synthetic_contract()
    market=ManualMarketData(client,verified_increments={contract.snapshot.symbol:'.05'},fee_per_contract='.65')
    engine=SimulationEngine(SimulationLedger(root/'ledger.db'),LocalPaperBroker(root/'broker.db'),
        f.synthetic_policy(stop_loss_pct=Decimal('10')))
    service=ManualWorkflow(engine,ManualReviews(root/'reviews.db'),read_state=lambda s:state_fixture(),
        market_data=market,clock=lambda:f.NOW)
    with patch('socket.socket.connect',side_effect=AssertionError('No real network')):
        if kind=='buy':
            quantity=st.number_input('Cantidad de prueba',min_value=1,value=None,step=1)
            target=st.selectbox('Ganancia de prueba',['10','20','35','100','MANUAL'],index=None)
            review=None if quantity is None else {'quantity':quantity,'ask':2.,'entry_cost':Decimal('200.65')*quantity}
            render_entry_actions('AMZN','CALL',contract,review,target,f.NOW.isoformat(),workflow=service,owner='test')
        else:
            if kind in ('filled','pending') and not engine.ledger.orders():
                r=service.prepare_buy('test','AMZN','CALL',contract.snapshot.symbol,3,'MANUAL')
                result=service.confirm('test',r['id'])
                if kind=='filled':
                    engine.broker.match_quote(engine.ledger.order(result['client_key'])['broker_id'],contract,
                        now=f.NOW,execution_id='SYNTHETIC_UI_FILL')
                    engine.reconcile(f.NOW)
            if kind=='pending':
                payload=payload_fixture();payload['callExpDateMap']['2026-10-23:7']['100.0'][0].update(bid=2.,ask=2.05)
                client.full_chain.return_value=payload;market.cache.clear()
            render_manual_positions.__wrapped__(workflow=service,owner='test')
    st.session_state['order_count']=len(engine.ledger.orders())


class ManualActionPanelTests(unittest.TestCase):
    def page(self,root,**kwargs):
        page=AppTest.from_function(action_page,kwargs={'root':str(root),**kwargs}).run(timeout=30)
        self.assertEqual(len(page.exception),0,str(page.exception));return page

    def test_no_defaults_two_steps_and_no_double_click_submission(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root)
            self.assertIsNone(p.number_input[0].value);self.assertIsNone(p.selectbox[0].value)
            self.assertTrue(p.button[0].disabled)
            p.number_input[0].set_value(3).run();p.selectbox[0].set_value('35').run()
            self.assertFalse(p.button[0].disabled)
            p.button[0].click().run();self.assertEqual(p.session_state['order_count'],0)
            self.assertIn('Confirmar compra simulada',[b.label for b in p.button])
            p.button[1].click().run();self.assertEqual(len(p.exception),0,str(p.exception))
            self.assertEqual(p.session_state['order_count'],1)
            p.run();self.assertTrue(p.button[1].disabled)
            self.assertEqual(p.session_state['order_count'],1)

    def test_change_of_quantity_or_profit_clears_old_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root);p.number_input[0].set_value(2).run();p.selectbox[0].set_value('MANUAL').run()
            p.button[0].click().run();self.assertEqual(len(p.button),2)
            p.number_input[0].set_value(3).run();self.assertEqual(len(p.button),1)
            self.assertEqual(p.session_state['order_count'],0)

    def test_empty_positions_show_no_active_close_button(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root,kind='positions')
            self.assertEqual(len(p.exception),0,str(p.exception));self.assertEqual(len(p.button),0)
            self.assertTrue(any('Sin posiciones' in info.value for info in p.info))

    def test_manual_close_button_reviews_then_submits_only_once(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root,kind='filled')
            self.assertEqual([b.label for b in p.button],['Cerrar posición simulada'])
            p.button[0].click().run();self.assertEqual(p.session_state['order_count'],1)
            self.assertEqual(p.button[1].label,'Confirmar cierre simulado')
            p.button[1].click().run();self.assertEqual(len(p.exception),0,str(p.exception))
            self.assertEqual(p.session_state['order_count'],2)
            p.run();self.assertEqual(p.session_state['order_count'],2)

    def test_pending_order_cancel_has_its_own_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            p=self.page(root,kind='pending')
            self.assertEqual(p.button[0].label,'Preparar cancelación simulada')
            p.button[0].click().run();self.assertEqual(p.session_state['order_count'],1)
            p.button[1].click().run();self.assertEqual(len(p.exception),0,str(p.exception))
            from schwab_simulation import SimulationLedger
            self.assertEqual(SimulationLedger(Path(root)/'ledger.db').orders()[0]['status'],'CANCELED')


if __name__=='__main__':unittest.main()
