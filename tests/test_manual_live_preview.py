"""Both real entry routes and contract/quantity UI on isolated synthetic data."""
from copy import deepcopy
from datetime import datetime
from urllib.parse import urlsplit,parse_qs
import unittest
from streamlit.testing.v1 import AppTest


def manual_page(origin='telegram',retracted=False,closed=False):
    from copy import deepcopy
    from datetime import datetime
    from urllib.parse import urlsplit,parse_qs
    from unittest.mock import Mock,patch
    import streamlit as st
    import manual_trade_panel as panel
    import manual_execution_panel as actions
    from manual_trade_links import signal_link
    from manual_trade_service import ManualMarketData
    from tests.test_manual_trade_service import state_fixture,payload_fixture
    from tests.test_schwab_simulation import NOW
    from manual_alert_entry import AlertReference
    from manual_execution import ManualWorkflow
    from schwab_simulation import ManualPracticePolicy
    first=state_fixture();second=deepcopy(first)
    if retracted:second['tick']['signal']=None
    if closed:first['session']=None;second['session']=None
    if origin=='telegram':
        url=signal_link('AMZN',first['tick']['signal'],NOW,base_url='https://jj.example/')
        params={key:values[0] for key,values in parse_qs(urlsplit(url).query).items()}
    else:params={'operar':'AMZN','lado':'CALL','senal':NOW.isoformat()}
    st.query_params.update(params)
    client=Mock();client.full_chain.return_value=payload_fixture()
    service=ManualMarketData(client,fee_per_contract='.65')
    reference=AlertReference('AMZN','CALL',first['tick']['signal']['candle'],NOW.isoformat(),NOW.isoformat(),
        first['tick']['version'],'ALPACA','iex',100.,104.,'ENVIADO')
    workflow=Mock()
    workflow.engine.policy=ManualPracticePolicy()
    workflow.alert_reader=lambda *args:reference
    workflow._controls=ManualWorkflow._controls
    #Strip fragment scheduling only for this AppTest so patches encompass reruns.
    body=panel.render_live_manual_ticket.__wrapped__
    with patch.object(panel,'render_live_manual_ticket',body), \
         patch.object(actions,'shared_manual_workflow',return_value=workflow), \
         patch.object(actions,'render_manual_positions'), \
         patch.object(panel,'read_manual_state',side_effect=[first,second]), \
         patch.object(panel,'_shared_market_data',return_value=service), \
         patch.object(panel,'_render_manual_chart'), \
         patch.object(panel,'load_watchlist',return_value={'symbols':['AMZN']}), \
         patch.object(panel,'datetime',wraps=datetime) as clock, \
         patch('socket.socket.connect',side_effect=AssertionError('No real network in UI test')):
        clock.now.return_value=NOW
        panel.render_manual_trade(st.query_params['operar'],st.query_params['lado'],st.query_params['senal'])
    st.session_state['market_requests']=client.full_chain.call_count


class ManualLivePreviewTests(unittest.TestCase):
    def render(self,**kwargs):
        page=AppTest.from_function(manual_page,kwargs=kwargs).run(timeout=30)
        self.assertEqual(len(page.exception),0,str(page.exception))
        return page

    def test_telegram_and_dashboard_open_same_live_contract_and_quantity_review(self):
        for origin in ('telegram','dashboard'):
            with self.subTest(origin=origin):
                page=self.render(origin=origin)
                self.assertEqual(len(page.selectbox),1)
                page.selectbox[0].set_value('AMZN  261023C00100000').run()
                self.assertEqual(len(page.exception),0,str(page.exception))
                self.assertIsNone(page.number_input[0].value)
                page.number_input[0].set_value(3).run()
                self.assertEqual(len(page.exception),0,str(page.exception))
                self.assertIn('$600.00 USD',[metric.value for metric in page.metric])
                self.assertTrue(all(button.disabled for button in page.button))

    def test_retraction_after_delivered_alert_does_not_block_manual_preparation(self):
        page=self.render(retracted=True)
        self.assertEqual(len(page.selectbox),1);self.assertEqual(len(page.number_input),0)
        self.assertTrue(any('Entrada manual por aviso' in item.value for item in page.success))
        self.assertEqual(page.session_state['market_requests'],1)

    def test_closed_session_does_not_call_schwab_or_create_a_buy_proposal(self):
        page=self.render(closed=True)
        self.assertEqual(page.session_state['market_requests'],0)
        self.assertEqual(len(page.selectbox),0)
        self.assertTrue(page.button[0].disabled)


if __name__=='__main__':unittest.main()
