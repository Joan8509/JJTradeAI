from unittest import TestCase
from datetime import datetime,timedelta,timezone
from entry_quality_research import WidthSample,reference_widths,observe,compare_policies,spread_observation,execution_observation,AUTHORITY

NOW=datetime(2026,10,29,14,tzinfo=timezone.utc)

def samples(n=20):
    return [WidthSample('AAPL','09:30',(NOW-timedelta(days=i+1)).date().isoformat(),
                        NOW-timedelta(days=i+1),float(i+1)) for i in range(n)]

class EntryQualityResearchTests(TestCase):
    def reference(self,rows=None):
        return reference_widths(rows if rows is not None else samples(),symbol='AAPL',slot='09:30',session_day='2026-10-29',now=NOW)

    def observation(self,reference=None):
        return observe(side='SUPERIOR',price=101.1,upper=101,lower=99,middle=100,
                       candle=NOW,at=NOW+timedelta(seconds=1),reference=reference or self.reference())

    def test_width_and_expansion_not_conflated(self):
        self.assertEqual(self.observation()['bandwidth_pct'],2)

    def test_prior_twenty_unique_days_only(self):
        self.assertEqual(self.reference()['count'],20)
        self.assertEqual(self.reference()['p20'],4)

    def test_future_cannot_change_reference(self):
        future=WidthSample('AAPL','09:30','2026-10-28',NOW+timedelta(seconds=1),100)
        self.assertEqual(self.reference(),self.reference(samples()+[future]))

    def test_same_day_not_used_even_if_already_closed(self):
        today=WidthSample('AAPL','09:30','2026-10-29',NOW-timedelta(minutes=1),100)
        self.assertEqual(self.reference(),self.reference(samples()+[today]))

    def test_symbol_and_slot_cannot_mix(self):
        other=[WidthSample('SPY','09:30','2026-10-28',NOW,100),WidthSample('AAPL','10:30','2026-10-28',NOW,100)]
        self.assertEqual(self.reference(),self.reference(samples()+other))

    def test_missing_reference_remains_unknown(self):
        policy=compare_policies(self.observation(self.reference(samples(9))))
        self.assertIsNone(policy['WIDTH_P20'])
        self.assertIsNone(policy['WIDTH_P20_EXPOSURE_1'])
        self.assertTrue(policy['BASELINE'])

    def test_duplicate_reference_rejected(self):
        with self.assertRaises(ValueError):self.reference(samples()+[samples()[0]])

    def test_directional_exposure_put(self):
        result=observe(side='INFERIOR',price=98.9,upper=101,lower=99,middle=100,
                       candle=NOW,at=NOW,reference=self.reference())
        self.assertAlmostEqual(result['exposure_pct_width'],5)

    def test_no_wait_or_order_authority(self):
        result=self.observation()
        self.assertEqual(result['authority'],AUTHORITY)
        self.assertEqual(result['delay_added_seconds'],0)
        self.assertNotIn('order',result)

    def test_naive_or_future_candle_rejected(self):
        with self.assertRaises(ValueError):
            observe(side='SUPERIOR',price=102,upper=101,lower=99,middle=100,candle=NOW,at=NOW-timedelta(seconds=1),reference=self.reference())
        with self.assertRaises(ValueError):reference_widths([],symbol='AAPL',slot='09:30',session_day='2026-10-29',now=datetime(2026,10,29))

    def test_invalid_prices_rejected(self):
        for value in (float('nan'),float('inf'),0,-1):
            with self.assertRaises(ValueError):spread_observation(bid=value,ask=1,stop_pct=20,target_pct=10)

    def test_spread_can_consume_stop_without_stock_move(self):
        result=spread_observation(bid=.32,ask=.4,stop_pct=20,target_pct=10)
        self.assertAlmostEqual(result['spread_pct_ask'],20)
        self.assertTrue(result['stop_consumed_by_spread'])

    def test_invalid_bid_above_ask(self):
        with self.assertRaises(ValueError):spread_observation(bid=2,ask=1,stop_pct=20,target_pct=10)

    def test_manual_target_stays_unknown(self):
        result=spread_observation(bid=.32,ask=.4,stop_pct=20,target_pct=None)
        self.assertIsNone(result['spread_to_target_ratio'])

    def test_execution_snapshot_retains_geometry_without_invented_reference(self):
        from types import SimpleNamespace
        quote=SimpleNamespace(bid=1,ask=1.05,bid_size=2,ask_size=3,quote_timestamp=NOW)
        tick=dict(source_timestamp=NOW.isoformat(),signal=dict(side='SUPERIOR',candle=NOW.isoformat()),
                  geometry=dict(upper=101,lower=99,mid=100,previous_upper=100.9,previous_lower=99.1,previous_mid=100,price=101.1,opening=100))
        result=execution_observation(tick,quote,stop_pct=20,target_pct=10,dispatched_at=NOW+timedelta(seconds=1),first_signal_at=NOW.isoformat())
        self.assertEqual(result['signal_quality']['bandwidth_pct'],2)
        self.assertEqual(result['volatility_reference_state'],'NOT_PRELOADED')
        self.assertFalse(result['entry_gate_enabled'])

    def test_execution_snapshot_rejects_future_quote(self):
        from types import SimpleNamespace
        quote=SimpleNamespace(bid=1,ask=1.05,bid_size=2,ask_size=3,quote_timestamp=NOW+timedelta(seconds=1))
        with self.assertRaises(ValueError):
            execution_observation(dict(source_timestamp=NOW.isoformat()),quote,stop_pct=20,target_pct=10,dispatched_at=NOW,first_signal_at=NOW.isoformat())
