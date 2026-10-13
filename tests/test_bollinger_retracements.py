import unittest
from scripts.study_bollinger_retracements import exit_plan,path_metrics
from scripts.review_bollinger_retracements import conditional_continuity


class RetracementTests(unittest.TestCase):
    def test_continuity_outcome_excludes_gain_used_to_select_the_pattern(self):
        row={'period':'TRAIN','side':'SUPERIOR','first_pullback_minutes':None,'first_reentry_minutes':None,
             'plans':{'TIME_2':{'return_pct':2},'TIME_5':{'return_pct':2},
                      'TIME_10':{'return_pct':3},'TIME_15':{'return_pct':1}}}
        group=next(r for r in conditional_continuity([row]) if r['period']=='TRAIN' and r['continuity_observed_after_two_minutes'])
        self.assertEqual(group['outcomes_after_observation']['5']['mean_return_from_minute3_pct'],0)
    def test_target_uses_next_open_not_the_observed_profitable_close(self):
        result=exit_plan([100.3]*15,[100,99]+[100]*14,[False]*15,1,100,'TP020_STOP010_MAX5')
        self.assertEqual(result['reason'],'TARGET_CLOSE')
        self.assertEqual(result['held_minutes'],1)
        self.assertAlmostEqual(result['return_pct'],-1)

    def test_first_adverse_close_has_zero_before_pullback(self):
        result=path_metrics([99.9,100.2,100.1],[True,False,False],1,100)
        self.assertEqual(result['first_pullback_minutes'],1)
        self.assertEqual(result['advance_before_pullback_pct'],0)
        self.assertEqual(result['advance_before_reentry_pct'],0)

    def test_short_direction_and_no_pullback_are_censored(self):
        result=path_metrics([99.9,99.8,99.7],[False]*3,-1,100)
        self.assertTrue(result['pullback_censored'])
        self.assertIsNone(result['first_pullback_minutes'])
        self.assertAlmostEqual(result['advance_before_pullback_pct'],.3)
