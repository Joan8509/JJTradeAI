"""Diagnostic-only band comparison, isolated local quotes and databases."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch
from entry_band_comparison import compare_snapshot,attach_comparison,REVISION,summarize_entries
from bollinger_expansion import MINIMUM_BAND_EXPANSION_PCT
from tests import test_automatic_entry_queue as fixtures


class BandComparisonTests(TestCase):
    def snapshot(self,weak=3):
        return dict(source_timestamp='2026-10-28T14:00:00+00:00',
            geometry=dict(upper=110.5,lower=100-weak/10,previous_upper=110,previous_lower=100))

    def test_each_band_inclusive_five_and_active_three_stays_unchanged(self):
        self.assertEqual(MINIMUM_BAND_EXPANSION_PCT,3)
        for value,expected in [(3,False),(4.9,False),(5,True),(6,True)]:
            snapshot=self.snapshot(value);before=deepcopy(snapshot)
            result=compare_snapshot(snapshot)
            self.assertIs(result['meets_candidate'],expected)
            self.assertEqual(result['mode'],'OBSERVATION_ONLY')
            self.assertEqual(snapshot,before)
        snapshot=self.snapshot(6);snapshot['geometry']['upper']=110.2
        self.assertFalse(compare_snapshot(snapshot)['meets_candidate'])

    def test_missing_or_invalid_evidence_stays_unknown_without_private_exception(self):
        for snapshot in ({},None,self.snapshot(),self.snapshot()):
            if snapshot and snapshot.get('geometry'):snapshot['geometry']['upper']=float('nan')
            self.assertIsNone(compare_snapshot(snapshot)['meets_candidate'])
        snapshot=self.snapshot(6);snapshot['signal']=dict(band_expansion=snapshot.pop('geometry'))
        self.assertTrue(compare_snapshot(snapshot)['meets_candidate'])

    def harness(self):
        h=fixtures.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        return h

    def test_below_five_metadata_never_blocks_buy_or_changes_one_shot_quantity(self):
        h=self.harness();h.f.state['tick']['geometry']=self.snapshot(3)['geometry']
        h.arm();h.runner.step()
        orders=h.f.engine.ledger.orders();self.assertEqual(len(orders),1)
        row=orders[0];study=row['order']['entry_band_comparison']
        self.assertEqual(study['status'],'BELOW_5');self.assertEqual(study['revision'],REVISION)
        self.assertEqual(row['order']['quantity'],2)
        h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(len(h.f.service.positions()),1)
        h.runner.step();self.assertEqual(len(h.f.engine.ledger.orders()),1)

    def test_diagnostic_exception_cannot_prevent_purchase(self):
        h=self.harness();h.arm()
        with patch('entry_band_comparison.compare_snapshot',side_effect=RuntimeError('private fixture')):
            h.runner.step()
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertNotIn('entry_band_comparison',h.f.engine.ledger.orders()[0]['order'])

    def test_report_keeps_legacy_unknown_and_joins_actual_fills_after_close(self):
        from operation_results import read_operation_results
        h=self.harness();h.f.state['tick']['geometry']=self.snapshot(3)['geometry']
        h.arm(target='10');h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
        h.f.quote(bid=2.25,ask=2.28,seconds=2);h.f.service.observe()
        h.f.quote(bid=2.25,ask=2.28,seconds=3);h.f.service.observe()
        history=read_operation_results(h.f.engine.ledger.path,now=h.f.now)
        result=summarize_entries(history['entries'])
        self.assertEqual(result['groups']['BELOW_5']['closed'],1)
        self.assertEqual(result['groups']['BELOW_5']['wins'],1)
        self.assertFalse(result['hypothetical_five_percent_pnl'])
        legacy=deepcopy(history['entries'][0]);legacy.pop('entry_band_comparison')
        self.assertEqual(summarize_entries([legacy])['groups']['UNKNOWN']['closed'],1)
