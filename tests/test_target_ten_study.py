from unittest import TestCase
from scripts.study_target_ten import quote_hurdle,execution_rows,execution_summary

class TargetTenStudyTests(TestCase):
    def test_spread_cost_and_net_target_use_sell_bid_and_tick(self):
        wide=quote_hurdle('.63','.55',buy_fee='.65',sell_fee='.65')
        narrow=quote_hurdle('.63','.61',buy_fee='.65',sell_fee='.65')
        self.assertEqual(wide['gross_target_limit'],'0.70')
        self.assertEqual(wide['net_target_price'],'0.71')
        self.assertGreater(wide['bid_rise_to_gross_target_pct'],narrow['bid_rise_to_gross_target_pct'])
        self.assertAlmostEqual(wide['net_return_at_gross_target_pct'],100*5.7/63.65)

    def evidence(self,closed=True):
        buy=dict(id='B',contract='GLD   261116P00354000',instruction='BUY_TO_OPEN',
            fills={'1':dict(quantity=1,price='.63',time='2026-11-16T15:20:32+00:00')},exit_plan={'target':'10'})
        sale=dict(id='S',parent_id='B',instruction='SELL_TO_CLOSE',exit_role='BROKER_TARGET',
            created_at='2026-11-16T15:20:34+00:00',
            fills={'2':dict(quantity=1,price='.70',time='2026-11-16T15:21:16+00:00')} if closed else {})
        return [buy,sale]

    def test_execution_endpoint_is_not_first_touch_or_net_profit(self):
        row=execution_rows(self.evidence())[0]
        self.assertEqual(row['buy_to_full_exit_seconds'],44)
        self.assertEqual(row['target_order_delay_seconds'],2)
        self.assertAlmostEqual(row['gross_return_pct'],100*7/63)
        for key in ('first_target_touch_seconds','target_before_stop','mae_before_target','net_return_pct'):
            self.assertIsNone(row[key])
        summary=execution_summary([row])
        self.assertEqual(summary['observed_execution_with_10_by_seconds']['30'],0)
        self.assertEqual(summary['observed_execution_with_10_by_seconds']['60'],1)

    def test_unclosed_trade_is_unknown_instead_of_a_loss(self):
        row=execution_rows(self.evidence(False))[0]
        self.assertFalse(row['fully_closed']);self.assertIsNone(row['gross_return_pct'])
        summary=execution_summary([row])
        self.assertEqual(summary['trades'],1);self.assertEqual(summary['closed_negative'],0)
        self.assertEqual(summary['closed'],0)

    def test_partial_fills_are_quantity_weighted(self):
        rows=self.evidence();rows[0]['fills']['3']=dict(quantity=1,price='.65',time='2026-11-16T15:20:33+00:00')
        row=execution_rows(rows)[0]
        self.assertEqual(row['entry_price'],'0.64');self.assertFalse(row['fully_closed'])
        rows[1]['fills']['4']=dict(quantity=1,price='.72',time='2026-11-16T15:21:17+00:00')
        row=execution_rows(rows)[0]
        self.assertEqual(row['exit_average'],'0.71');self.assertEqual(row['buy_to_full_exit_seconds'],45)

    def test_overclosed_evidence_is_rejected_and_no_fills_are_ignored(self):
        rows=self.evidence();rows[1]['fills']['2']['quantity']=2
        with self.assertRaisesRegex(ValueError,'OVER_CLOSED'):execution_rows(rows)
        rows=self.evidence();rows[0]['fills']={}
        self.assertEqual(execution_rows(rows),[])
