"""User06/11: reject already-outside openings without delaying valid entries."""
import unittest
from bollinger_phone_worker import bands_at_open, detect_values, opening_bands_from_moments


class InitialOriginTests(unittest.TestCase):
    def test_observed_meta_opening_outside_cannot_be_engulfed_into_validity(self):
        args=(616.27,614.2909384294312,598.9295615705687,606.61025,
              618.01,616.3333594456726,598.0416405543274,607.1875)
        for mirrored in (False,True):
            a=args if not mirrored else (-args[0],-args[2],-args[1],-args[3],
                                        -args[4],-args[6],-args[5],-args[7])
            opening=616.27 if not mirrored else -616.27
            initial=(615.8577557916279,598.3432442083721) if not mirrored else (-598.3432442083721,-615.8577557916279)
            self.assertIsNone(detect_values(*a,opening=opening,opening_upper=initial[0],opening_lower=initial[1]))

    def test_same_inside_origin_keeps_slv_first_valid_tick(self):
        self.assertEqual(detect_values(46.995,47.067054938862476,46.69044506113753,46.87875,
            47.11,47.08839080530211,46.67810919469788,46.88325,
            opening=47.015,opening_upper=47.06606598838809,opening_lower=46.690934011611915),'SUPERIOR')

    def test_initial_edges_inclusive_but_one_missing_edge_is_unknown(self):
        for opening in (98,102):
            self.assertEqual(detect_values(100,102,98,100,104,103,97,100.5,
                opening=opening,opening_upper=102,opening_lower=98),'SUPERIOR')
        self.assertIsNone(detect_values(100,102,98,100,104,103,97,100.5,
            opening=100,opening_upper=102))

    def test_moment_replacement_matches_nineteen_closes_across_scales(self):
        for shift,scale in ((0,1),(600,.1),(100000,10)):
            prior=[shift+scale*(100+(-1)**i*i/20) for i in range(19)]
            close=shift+scale*103;opening=shift+scale*100
            upper,lower=bands_at_open(prior,close);mid=(sum(prior)+close)/20
            actual=opening_bands_from_moments(close,upper,lower,mid,opening)
            expected=bands_at_open(prior,opening)
            for a,b in zip(actual,expected):self.assertAlmostEqual(a,b,places=8)
