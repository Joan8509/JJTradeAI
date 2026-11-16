from copy import deepcopy
from unittest import TestCase

from breakout_quality_research import geometry_features,selected,comparison,rank_on_training,day_difference,fit_tree,tree_prediction,initial_rates
from scripts.study_breakout_common_factors import no_overlap
from scripts.study_waiting_for_five import first_five


class QualityResearchTests(TestCase):
    def test_geometry_features_are_direction_symmetric_and_do_not_read_outcomes(self):
        e=dict(price=104,opening=100,side='SUPERIOR',band_expansion=dict(upper=103,lower=97,
            previous_upper=102,previous_lower=98,upper_pct=25,lower_pct=25))
        original=deepcopy(e);r=geometry_features(e)
        self.assertEqual(r['exposure'],25);self.assertEqual(r['body_width_pct'],100)
        self.assertEqual(geometry_features(e|dict(outcomes={'return_1m':999})),r)
        p=e|dict(side='INFERIOR',price=96)
        self.assertEqual(geometry_features(p)['exposure'],25)
        self.assertEqual(geometry_features(p)['opposite'],25)
        self.assertEqual(e,original)

    def test_missing_is_not_false_and_known_false_dominates_conjunction(self):
        self.assertIsNone(selected({},'OPPOSITE_5'))
        self.assertIsNone(selected({'opposite':6},'OPPOSITE_5_VOLUME_15'))
        self.assertFalse(selected({'opposite':4},'OPPOSITE_5_VOLUME_15'))
        self.assertIsNone(selected({'opposite':float('nan')},'OPPOSITE_5'))
        self.assertIsNone(selected({'opposite':True},'OPPOSITE_5'))

    def test_missing_features_pass_in_effective_policy_but_are_reported(self):
        rows=[dict(features={'opposite':6},outcomes={'r':1}),
              dict(features={'opposite':4},outcomes={'r':-1}),
              dict(features={},outcomes={'r':2})]
        c=comparison(rows,'OPPOSITE_5','r')
        self.assertEqual(c['unknown']['signals'],1)
        self.assertEqual(c['known_baseline']['covered'],2)
        self.assertEqual(c['unknown_pass']['covered'],2)
        self.assertEqual(c['unknown_pass']['mean'],1.5)

    def test_missing_labels_are_not_losses_and_discarded_winners_counted(self):
        rows=[dict(features={'opposite':4},outcomes={'r':.2}),
              dict(features={'opposite':4},outcomes={'r':None})]
        c=comparison(rows,'OPPOSITE_5','r')
        self.assertEqual(c['discarded']['positive'],1)
        self.assertEqual(c['discarded']['missing'],1)
        self.assertEqual(c['discarded']['negative'],0)

    def test_training_can_abstain_and_cannot_infer_from_zero_covered(self):
        self.assertIsNone(rank_on_training([],'r'))
        rows=[dict(features={'opposite':6},outcomes={'r':None}) for _ in range(50)]
        self.assertIsNone(rank_on_training(rows,'r'))
        rows=[dict(features={'opposite':6},outcomes={'r':1}) for _ in range(50)]
        self.assertIsNone(rank_on_training(rows,'r'))

    def test_no_overlap_is_time_only_and_separates_symbols_and_versions(self):
        rows=[dict(at=t,symbol=s,cohort=c) for t,s,c in
              ((0,'A','v7'),(30,'A','v7'),(30,'B','v7'),(30,'A','v6'),(60,'A','v7'))]
        self.assertEqual(len(no_overlap(rows,60)),4)

    def test_one_day_does_not_generate_day_confidence_interval(self):
        rows=[dict(day='2026-11-11',symbol='A',features={'opposite':v},outcomes={'r':x})
              for v,x in ((6,1),(4,-1))]
        result=day_difference(rows,'OPPOSITE_5','r')
        self.assertEqual(result['days'],1);self.assertIsNone(result['ci95'])

    def test_opposite_band_is_different_from_both_bands_threshold(self):
        self.assertTrue(selected({'opposite':8,'minimum':3},'OPPOSITE_8'))
        self.assertFalse(selected({'opposite':8,'minimum':3},'BOTH_5'))

    def test_interaction_tree_fits_training_and_abstains_on_missing_split(self):
        rows=[dict(features={'volume_ratio':i},outcomes={'r':-1 if i<60 else 1}) for i in range(120)]
        tree=fit_tree(rows,'r',('volume_ratio',),max_depth=1,min_leaf=50)
        self.assertEqual(tree['feature'],'volume_ratio')
        self.assertFalse(tree_prediction({'volume_ratio':0},tree))
        self.assertTrue(tree_prediction({'volume_ratio':119},tree))
        self.assertIsNone(tree_prediction({},tree))
        self.assertFalse(tree_prediction({'volume_ratio':0,'future_return':999},tree))

    def test_interaction_tree_does_not_make_tiny_leaves_into_filters(self):
        rows=[dict(features={'volume_ratio':i},outcomes={'r':-1 if i<5 else 1}) for i in range(100)]
        tree=fit_tree(rows,'r',('volume_ratio',),min_leaf=50)
        self.assertTrue(tree_prediction({'volume_ratio':0},tree))
        def check(node):
            self.assertGreaterEqual(node['samples'],50)
            if 'feature' in node:
                check(node['left']);check(node['right'])
        check(tree)

    def test_initial_rate_uses_only_prior_same_reference_and_never_waits(self):
        e=dict(source_timestamp='2026-11-11T15:00:01+00:00',detected_at='2026-11-11T15:00:01.1+00:00',
               first_breakout_at='2026-11-11T15:00:00+00:00',side='SUPERIOR',
               band_expansion=dict(previous_upper=101,previous_lower=99,lower=98.9))
        row=dict(time='2026-11-11T15:00:00+00:00',received='2026-11-11T15:00:00+00:00',
                 processed='2026-11-11T15:00:00+00:00',previous_upper=101,previous_lower=99,lower=98.95)
        result=initial_rates(e,[row]);self.assertAlmostEqual(result['opposite_rate'],2.5)
        self.assertEqual(result['trigger_age'],1)
        self.assertEqual(result,initial_rates(e,[row,row|dict(time='2026-11-11T15:00:02+00:00',lower=80)]))
        self.assertIsNone(initial_rates(e,[row|dict(previous_lower=98)])['opposite_rate'])

    def test_waiting_simulation_cannot_renew_expired_breakout(self):
        event=dict(side='SUPERIOR',price=103.1,opening=100,
            source_timestamp='2026-11-11T15:00:00+00:00',detected_at='2026-11-11T15:00:00.1+00:00',
            candle='2026-11-11T15:00:00+00:00',breakout_deadline='2026-11-11T15:00:30+00:00',
            band_expansion=dict(previous_upper=102,previous_lower=98,upper=103,lower=97))
        row=dict(time='2026-11-11T15:00:30+00:00',received='2026-11-11T15:00:30+00:00',
            processed='2026-11-11T15:00:30+00:00',previous_upper=102,previous_lower=98,
            price=110,upper=106,lower=96)
        # Keep original below5% to isolate the late transition.
        event['band_expansion'].update(upper=102.12,lower=97.88)
        self.assertIsNone(first_five(event,[row],'BOTH_5'))
        earlier=row|dict(time='2026-11-11T15:00:29+00:00',received='2026-11-11T15:00:29+00:00',processed='2026-11-11T15:00:29+00:00')
        self.assertEqual(first_five(event,[earlier],'BOTH_5')['delay_seconds'],29)
