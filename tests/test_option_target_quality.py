from unittest import TestCase
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from option_target_quality import target_effort,dominates,frontier
from tests import test_schwab_option_order_request as f

class OptionTargetQualityTests(TestCase):
    def metric(self,**changes):
        c=f.contract();q=replace(c.snapshot,bid=.55,ask=.63,delta=.5,**changes)
        return target_effort(replace(c,snapshot=q,price_increment=Decimal('.01')),spot=100,now=f.NOW)

    def test_spread_and_delta_effort_include_execution_hurdle(self):
        r=self.metric()
        self.assertAlmostEqual(r['spread_fraction'],.08/.63)
        self.assertAlmostEqual(r['spread_to_target_profit'],.08/.063)
        self.assertEqual(r['verified_tick_target_price'],'0.70')
        self.assertAlmostEqual(r['favorable_underlying_move_delta_only'],.30)
        self.assertFalse(r['order_authorized']);self.assertFalse(r['calibrated'])

    def test_cheaper_option_can_need_more_underlying_movement(self):
        a=self.metric();b=dict(a,contract='CHEAPER',spread_fraction=.2,favorable_underlying_move_pct_delta_only=.8)
        self.assertTrue(dominates(a,b));self.assertEqual(frontier([a,b])['dominated'],['CHEAPER'])

    def test_missing_delta_preserves_unknown_and_does_not_select(self):
        c=f.contract();r=target_effort(replace(c,snapshot=replace(c.snapshot,delta=None)),spot=100,now=f.NOW)
        self.assertIsNone(r['favorable_underlying_move_delta_only']);self.assertIsNone(dominates(r,self.metric()))
        result=frontier([r]);self.assertEqual(result['unknown'],[r['contract']]);self.assertIsNone(result['selected_contract'])

    def test_no_tick_is_invented(self):
        r=target_effort(replace(f.contract(),price_increment=None),spot=100,now=f.NOW)
        self.assertIsNone(r['verified_tick_target_price'])

    def test_stale_and_wrong_direction_greeks_are_not_promoted(self):
        c=f.contract()
        with self.assertRaisesRegex(ValueError,'QUOTE_NOT_CURRENT'):
            target_effort(replace(c,snapshot=replace(c.snapshot,quote_timestamp=f.NOW-timedelta(seconds=30))),spot=100,now=f.NOW)
        r=target_effort(replace(c,snapshot=replace(c.snapshot,delta=-.5)),spot=100,now=f.NOW)
        self.assertFalse(r['delta_direction_valid']);self.assertIsNone(r['favorable_underlying_move_delta_only'])
