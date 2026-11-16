"""Research boundaries and current-rule geometry, without live data or orders."""
from datetime import datetime
from unittest import TestCase

from scripts.study_opening_strength import group, current_side, aggregate_minutes


class OpeningStrengthStudyTests(TestCase):
    def test_session_labels_follow_eastern_dst_and_exclude_premarket(self):
        def label(value):return group(datetime.fromisoformat(value).timestamp())
        self.assertIsNone(label('2026-11-06T14:29:59+00:00'))
        self.assertEqual(label('2026-11-06T14:30:00+00:00'),'C1')
        self.assertEqual(label('2026-11-06T14:45:00+00:00'),'C2')
        self.assertEqual(label('2026-11-06T15:00:00+00:00'),'C3')
        self.assertEqual(label('2026-11-06T15:15:00+00:00'),'LATER')
        self.assertIsNone(label('2026-11-06T21:00:00+00:00'))
        self.assertEqual(label('2026-10-30T13:30:00+00:00'),'C1')

    def test_expanded_current_bands_do_not_rescue_an_open_outside_initial_bands(self):
        g=dict(previous_mid=100,previous_upper=101,previous_lower=99,
            price=104,mid=100.1,upper=103,lower=97,opening=100,
            initial_opening_upper=101,initial_opening_lower=99)
        self.assertEqual(current_side(g),'SUPERIOR')
        g['opening']=101.5
        self.assertIsNone(current_side(g))
        g['opening']=100;g['price']=102
        self.assertIsNone(current_side(g))

    def test_missing_horizon_is_excluded_and_disjoint_comparison_is_preserved(self):
        def event(name,available,ret=0):
            result=dict(available=available,return_pct=ret,mfe_pct=.2,mae_pct=.1)
            return dict(group=name,day='2026-11-06',future={str(h):result for h in (1,3,5)})
        rows=[event('C1',True,1),event('C2',False),event('C3',True,-1)]
        summary=aggregate_minutes(rows)
        self.assertEqual(summary['C1']['horizons']['1']['positive_pct'],100)
        self.assertEqual(summary['C2_C3']['signals'],2)
        self.assertEqual(summary['C2_C3']['horizons']['1']['n'],1)
        self.assertEqual(summary['C2_C3']['horizons']['1']['missing'],1)
        self.assertEqual(summary['C2_C3']['horizons']['1']['mean_return_pct'],-1)
