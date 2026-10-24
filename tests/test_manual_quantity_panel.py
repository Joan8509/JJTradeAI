"""Real quantity widget and totals on synthetic quotes only; no DB or network."""
import unittest
from streamlit.testing.v1 import AppTest


def quantity_page(has_quote=True,fee='.65',stale=False,observed=False):
    from datetime import timedelta
    from unittest.mock import patch
    import streamlit as st
    from manual_trade_panel import render_quantity_review
    from tests.test_schwab_simulation import NOW,synthetic_contract
    strike=st.selectbox('Contrato de prueba',[100.,101.])
    quote=synthetic_contract(strike=strike).snapshot if has_quote else None
    with patch('socket.socket.connect',side_effect=AssertionError('No network in UI test')):
        render_quantity_review('AMZN','CALL',quote=quote,fee_per_contract=fee,
            as_of=NOW+timedelta(seconds=31 if stale else 0),observed_practice=observed)


class ManualQuantityPanelTests(unittest.TestCase):
    def page(self,**args):
        result=AppTest.from_function(quantity_page,kwargs=args).run(timeout=20)
        self.assertEqual(len(result.exception),0,str(result.exception))
        return result

    def test_no_default_quantity_and_total_follows_user_input(self):
        page=self.page()
        self.assertIsNone(page.number_input[0].value)
        self.assertEqual(len(page.metric),0)
        page.number_input[0].set_value(2).run()
        self.assertEqual(len(page.exception),0,str(page.exception))
        self.assertIn('$401.30 USD',[metric.value for metric in page.metric])
        page.number_input[0].set_value(4).run()
        self.assertIn('$802.60 USD',[metric.value for metric in page.metric])

    def test_changing_contract_does_not_reuse_quantity(self):
        page=self.page();page.number_input[0].set_value(3).run()
        page.selectbox[0].set_value(101.).run()
        self.assertEqual(len(page.exception),0,str(page.exception))
        self.assertIsNone(page.number_input[0].value)
        self.assertEqual(len(page.metric),0)

    def test_missing_or_stale_quote_disables_quantity_without_fabricated_price(self):
        for params in ({'has_quote':False},{'stale':True}):
            with self.subTest(params=params):
                page=self.page(**params)
                self.assertTrue(page.number_input[0].disabled)
                self.assertEqual(len(page.metric),0)

    def test_unknown_costs_cannot_be_displayed_as_free(self):
        page=self.page(fee=None);page.number_input[0].set_value(2).run()
        self.assertEqual(len(page.exception),0,str(page.exception))
        self.assertEqual([metric.label for metric in page.metric],['Prima por la cantidad elegida'])
        self.assertTrue(any('Faltan los costos' in item.value for item in page.info))

    def test_observed_practice_accepts_explicit_quantity_and_labels_unknown_fees(self):
        page=self.page(fee=None,observed=True);page.number_input[0].set_value(2).run()
        self.assertEqual(len(page.exception),0,str(page.exception))
        self.assertTrue(any('Solo importe de primas' in item.value for item in page.info))
        self.assertEqual(page.metric[-1].value,'$400.00 USD')


if __name__=='__main__':unittest.main()
