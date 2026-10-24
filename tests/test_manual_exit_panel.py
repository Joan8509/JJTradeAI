"""The real target widget, isolated from broker, market DB and Telegram."""
from decimal import Decimal
import unittest
from streamlit.testing.v1 import AppTest


def target_page(valid_policy=True):
    from contextlib import nullcontext
    from unittest.mock import patch
    import streamlit as st
    from manual_trade_panel import render_exit_target_review
    contract=st.selectbox('Contrato de prueba',['SYNTHETIC_ONE','SYNTHETIC_TWO'])
    candle=st.selectbox('Vela de prueba',['2026-10-16T14:00:00Z','2026-10-16T14:15:00Z'])
    policy_check=(nullcontext() if valid_policy else
        patch('manual_trade_panel.load_global_exit_policy',side_effect=ValueError('Unavailable')))
    with patch('socket.socket.connect',side_effect=AssertionError('No network in UI test')),policy_check:
        target=render_exit_target_review('AMZN','CALL',contract,candle)
    st.session_state['reviewed_target']=str(target) if target is not None else None


class ManualExitPanelTests(unittest.TestCase):
    def page(self,**kwargs):
        page=AppTest.from_function(target_page,kwargs=kwargs).run(timeout=25)
        self.assertEqual(len(page.exception),0,str(page.exception))
        return page

    def test_target_has_no_default_and_all_four_choices_are_explicit(self):
        page=self.page()
        self.assertIsNone(page.selectbox[2].value)
        self.assertEqual(page.selectbox[2].options,['10% bruto','20% bruto','35% bruto','100% bruto','Cierre manual'])
        for pct in ('10','20','35','100'):
            page.selectbox[2].set_value(Decimal(pct)).run()
            self.assertEqual(len(page.exception),0,str(page.exception))
            self.assertEqual(page.session_state['reviewed_target'],pct)
        self.assertTrue(any('no hay salidas ni compras activadas' in info.value for info in page.info))
        self.assertTrue(any('Stop loss global: 20%' in caption.value for caption in page.caption))
        self.assertTrue(any('Cierre manual conservado en todas las modalidades' in caption.value for caption in page.caption))

    def test_manual_means_personal_close_and_not_custom_percentage(self):
        page=self.page();page.selectbox[2].set_value('MANUAL').run()
        self.assertEqual(len(page.exception),0,str(page.exception))
        self.assertEqual(page.session_state['reviewed_target'],'MANUAL')
        self.assertTrue(any('Tú decides cuándo cerrar' in caption.value for caption in page.caption))
        self.assertTrue(any('stop loss global del 20%' in caption.value for caption in page.caption))
        self.assertEqual(len(page.number_input),0)

    def test_new_contract_or_signal_does_not_inherit_target(self):
        page=self.page();page.selectbox[2].set_value(Decimal('35')).run()
        page.selectbox[0].set_value('SYNTHETIC_TWO').run()
        self.assertIsNone(page.selectbox[2].value)
        page.selectbox[2].set_value(Decimal('10')).run()
        page.selectbox[1].set_value('2026-10-16T14:15:00Z').run()
        self.assertIsNone(page.selectbox[2].value)

    def test_unavailable_policy_blocks_review_without_a_default_stop(self):
        page=self.page(valid_policy=False)
        self.assertEqual(len(page.selectbox),2)
        self.assertIsNone(page.session_state['reviewed_target'])
        self.assertTrue(any('política global' in warning.value for warning in page.warning))


if __name__=='__main__':unittest.main()
