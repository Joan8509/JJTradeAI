"""Causal offline MA comparisons: no operational configuration or accounts."""
from copy import deepcopy
from unittest import TestCase
from tests.test_ma_price_outlook import context
from ma_outcome_research import features,selected,nonoverlap,summarize,policies,paired_day_difference


def event():
    return dict(symbol='AAPL',side='SUPERIOR',price=100,source_kind='TRADE',
        source_timestamp='2026-11-09T14:30:00+00:00',detected_at='2026-11-09T14:30:00.1+00:00',ma_context=context())


class MAResearchTests(TestCase):
    def test_future_outcomes_cannot_change_features(self):
        e=event();expected=features(e)
        e['future_return']=9999;e['outcomes']={'return_10s':-9999};e['close']=1
        self.assertEqual(features(e),expected)
        self.assertTrue(expected['slope20_both_aligned'])

    def test_known_mixed_direction_is_false_not_missing(self):
        e=event();e['ma_context']['frames'][1]['slopes']['20']=-1
        result=features(e)
        self.assertFalse(result['slope20_both_aligned'])
        e['ma_context']['frames'][1]['slopes']['20']=None
        self.assertIsNone(features(e)['slope20_both_aligned'])

    def test_context_after_price_or_decision_is_not_admissible(self):
        e=event();e['ma_context']['available_at']='2026-11-09T14:30:01+00:00'
        self.assertEqual(features(e)['state'],'CONTEXTO_NO_CAUSAL')
        e['source_kind']='BAR';e['detected_at']='2026-11-09T14:31:01+00:00'
        self.assertEqual(features(e)['state'],'DESCRIPTIVO')

    def test_opportunity_cost_and_missing_returns_reported_separately(self):
        a=dict(symbol='A',cohort='x',features=features(event()),outcomes={'r':1})
        b=deepcopy(a);b['features']['order20_both_aligned']=False;b['outcomes']['r']=2
        c=deepcopy(a);c['features']={'state':'SIN_DATOS'};c['outcomes']['r']=None
        result=policies([a,b,c],['ORDEN_20_HORA_DIARIO'],'r')['ORDEN_20_HORA_DIARIO']
        self.assertEqual(result['retained']['positive'],1)
        self.assertEqual(result['discarded']['positive'],1)
        self.assertEqual(result['unknown']['missing'],1)
        self.assertIsNone(result['unknown']['positive_pct'])

    def test_nonoverlap_cannot_reselect_based_on_profit_or_cross_cohort(self):
        rows=[dict(symbol='A',cohort='x',source_timestamp='2026-11-09T14:30:00+00:00'),
              dict(symbol='A',cohort='x',source_timestamp='2026-11-09T14:30:30+00:00'),
              dict(symbol='A',cohort='y',source_timestamp='2026-11-09T14:30:30+00:00')]
        self.assertEqual(len(nonoverlap(rows,60)),2)
        self.assertEqual(rows[0]['source_timestamp'],nonoverlap(list(reversed(rows)),60)[0]['source_timestamp'])

    def test_one_day_does_not_produce_confident_bootstrap_interval(self):
        row=dict(symbol='A',day='2026-11-09',features=features(event()),outcomes={'r':1})
        result=paired_day_difference([row],'ORDEN_20_HORA_DIARIO','r')
        self.assertTrue(result['insufficient_days']);self.assertIsNone(result['confidence_interval'])

    def test_favorable_forward_ma_is_not_a_rejection_barrier(self):
        e=event();f=features(e)
        self.assertEqual(f['nearest_ma_distance_pct'],2)
        self.assertEqual(f['nearest_limit_distance_pct'],5)
        self.assertTrue(selected({'features':f},'LIMITE_VALIDADO_010'))
