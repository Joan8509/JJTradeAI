from unittest import TestCase
from copy import deepcopy
from bollinger_bandwidth_research import bandwidth,measurements,cutpoints,quartile
from scripts.study_current_bandwidth import history_widths


class BandwidthTests(TestCase):
    def test_current_width_is_not_three_percent_expansion(self):
        e=dict(price=100,band_expansion=dict(upper=100.106,lower=99.894,previous_upper=100.1,previous_lower=99.9))
        m=measurements(e)
        self.assertAlmostEqual(m['bandwidth_pct'],.212)
        self.assertAlmostEqual(m['total_width_growth_pct'],6)
        self.assertNotEqual(m['bandwidth_pct'],3)

    def test_price_scale_does_not_change_normalized_width(self):
        a,b=bandwidth(101,99),bandwidth(1010,990)
        self.assertEqual(a['bandwidth_pct'],b['bandwidth_pct'])
        self.assertEqual(b['width_usd'],10*a['width_usd'])

    def test_current_width_can_be_narrow_despite_fast_expansion(self):
        e=dict(price=100,band_expansion=dict(upper=100.1,lower=99.9,previous_upper=100.05,previous_lower=99.95))
        m=measurements(e,[1]*20)
        self.assertAlmostEqual(m['relative_to_prior20'],.2)
        self.assertAlmostEqual(m['total_width_growth_pct'],100)

    def test_history_baseline_requires_ten_values_and_does_not_mutate(self):
        e=dict(price=100,band_expansion=dict(upper=101,lower=99));original=deepcopy(e)
        self.assertIsNone(measurements(e,[1]*9)['relative_to_prior20'])
        self.assertEqual(measurements(e,[1]*10)['relative_to_prior20'],2)
        self.assertEqual(e,original)

    def test_invalid_geometry_and_training_edges_are_explicit(self):
        self.assertIsNone(bandwidth(99,101));self.assertIsNone(bandwidth(True,1))
        self.assertIsNone(bandwidth(float('nan'),1));self.assertIsNone(cutpoints([1]*7))
        edges=cutpoints(list(range(20)))
        self.assertEqual(quartile(0,edges),'Q1');self.assertEqual(quartile(19,edges),'Q4')
        self.assertEqual(quartile(3,None),'SIN_REFERENCIA')
        self.assertEqual(quartile(float('nan'),edges),'SIN_REFERENCIA')
        self.assertEqual(quartile(True,edges),'SIN_REFERENCIA')

    def test_future_candles_cannot_change_prior_completed_baseline(self):
        periods=list(range(100));closes={i:100+i%3 for i in range(100)}
        before=history_widths(closes,periods,50)
        closes.update({i:900 for i in range(50,100)})
        self.assertEqual(history_widths(closes,periods,50),before)
        self.assertEqual(len(before),20)
