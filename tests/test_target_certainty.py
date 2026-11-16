from unittest import TestCase
from copy import deepcopy
from scripts.study_target_certainty import causal_features,delay_comparison,primary_outcomes

class CertaintyStudyTests(TestCase):
    def event(self):
        return dict(side='SUPERIOR',price=103,opening=100,source_kind='TRADE',
            source_timestamp='2026-11-16T15:00:00+00:00',detected_at='2026-11-16T15:00:00.1+00:00',
            first_breakout_at='2026-11-16T15:00:00+00:00',
            band_expansion=dict(upper=102.9,lower=97,previous_upper=102,previous_lower=98,
                upper_pct=22.5,lower_pct=25,required_pct=3))

    def test_future_and_late_arriving_ticks_cannot_change_entry_features(self):
        event=self.event();base=causal_features(event,[])
        row=dict(time='2026-11-16T15:00:01+00:00',received='2026-11-16T15:00:01+00:00',
            processed='2026-11-16T15:00:01+00:00',price=999,upper=200,lower=1,previous_upper=102,previous_lower=98)
        late=dict(row,time='2026-11-16T14:59:57+00:00')
        self.assertEqual(causal_features(event,[row,late]),base)

    def test_missing_endpoints_are_unknown_and_delay_uses_same_exit_instant(self):
        event=self.event();self.assertIsNone(primary_outcomes(event,[])['return_10s'])
        self.assertIsNone(delay_comparison(event,[],3))
        ticks=[dict(time='2026-11-16T15:00:03+00:00',price=104),dict(time='2026-11-16T15:00:10+00:00',price=105)]
        r=delay_comparison(event,ticks,3)
        self.assertGreater(r['difference_pp'],0)
        ticks[0]['price']=102
        self.assertLess(delay_comparison(event,ticks,3)['difference_pp'],0)
