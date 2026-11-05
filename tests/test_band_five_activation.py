from unittest import TestCase
from bollinger_phone_worker import detect_values
from entry_band_comparison import summarize_entries,REVISION,ACTIVE_FIVE_REVISION


class FivePercentActivationTests(TestCase):
    def test_nflx_above_three_is_accepted_in_both_directions(self):
        # Frozen geometry reported by the user: upper3.0278%, lower10.0231%.
        p_u,p_l=62.909013228542605,61.7939867714574
        u,l=62.94277375004834,61.68222624995166
        self.assertEqual(detect_values(62, p_u,p_l,62.3515,61.665,u,l,62.3125,opening=61.96),'INFERIOR')
        self.assertEqual(detect_values(-62,-p_l,-p_u,-62.3515,-61.665,-l,-u,-62.3125,opening=-61.96),'SUPERIOR')

    def test_old_and_new_policy_results_are_not_mixed_or_rewritten(self):
        from copy import deepcopy
        old=dict(status='CLOSED',report=dict(gross_pnl='10'),entry_band_comparison=dict(
            revision=REVISION,mode='OBSERVATION_ONLY',active_minimum_pct=3,candidate_minimum_pct=5,status='BELOW_5'))
        new=dict(status='CLOSED',report=dict(gross_pnl='-2'),entry_band_comparison=dict(
            revision=ACTIVE_FIVE_REVISION,mode='ACTIVE_THRESHOLD_AUDIT',active_minimum_pct=5,candidate_minimum_pct=5,status='PASS_5'))
        entries=[old,new];before=deepcopy(entries);result=summarize_entries(entries)
        self.assertEqual(result['groups']['BELOW_5']['wins'],1)
        self.assertEqual(result['active_five_groups']['PASS_5']['losses'],1)
        self.assertEqual(entries,before)
