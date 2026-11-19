"""Observed zero-price cancellation legs are metadata, never invented fills."""
from copy import deepcopy
from unittest import TestCase
from schwab_execution_snapshot import normalize_execution_snapshot
from tests import test_schwab_execution_snapshot as snapshots
from tests import test_real_broker_target as targets
from tests import test_real_order_ledger as journal


def cancellation(row,records=(),*,stamp):
    p=snapshots.snapshot(row,records,'CANCELED');p['remainingQuantity']=0
    unfilled=p['quantity']-p['filledQuantity']
    p['orderActivityCollection'].append(dict(activityType='EXECUTION',executionType='CANCELED',
        quantity=unfilled,orderRemainingQuantity=0,executionLegs=[dict(legId=1,
            quantity=unfilled,mismarkedQuantity=0,price=0,time=stamp)]))
    return p


class CancelActivityTests(TestCase):
    def setUp(self):
        self.f=snapshots.CumulativeExecutionTests();self.f.setUp()

    def test_cancellation_with_zero_price_leg_has_no_fills_and_releases_only_unfilled_reservation(self):
        p=cancellation(self.f.row,stamp=self.f.now.isoformat())
        row=self.f.apply(p)
        self.assertEqual(row['state'],'CANCELED');self.assertEqual(row['issues'],[])
        self.assertEqual(row['fills'],{})
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,journal.CONTRACT),0)

    def test_partial_fill_preserved_but_cancellation_quantity_is_never_a_fill(self):
        self.f.apply(snapshots.snapshot(self.f.row,[self.f.first]))
        p=cancellation(self.f.row,[self.f.first],stamp=self.f.now.isoformat())
        row=self.f.apply(p)
        self.assertEqual(row['state'],'CANCELED')
        self.assertEqual(sum(f['quantity'] for f in row['fills'].values()),1)
        self.assertEqual(self.f.ledger.available_to_close(journal.BINDING,journal.CONTRACT),1)
        self.assertEqual(self.f.apply(p)['fills'],row['fills'])

    def test_unknown_or_inconsistent_nonfill_activity_still_blocks(self):
        base=cancellation(self.f.row,stamp=self.f.now.isoformat())
        cases=[('executionType','BUST'),('activityType','UNKNOWN'),('quantity',2),('orderRemainingQuantity',1)]
        for key,value in cases:
            p=deepcopy(base);p['orderActivityCollection'][0][key]=value
            result=normalize_execution_snapshot(p,account_number='12345678')
            self.assertIn('UNSUPPORTED_EXECUTION_ACTIVITY',result.issues)
        for key,value in [('legId',2),('quantity',2),('price',.01),('mismarkedQuantity',1),('time','bad')]:
            p=deepcopy(base);p['orderActivityCollection'][0]['executionLegs'][0][key]=value
            self.assertIn('UNSUPPORTED_EXECUTION_ACTIVITY',normalize_execution_snapshot(p,account_number='12345678').issues)
        p=deepcopy(base);p['status']='WORKING';p['remainingQuantity']=3
        self.assertIn('UNSUPPORTED_EXECUTION_ACTIVITY',normalize_execution_snapshot(p,account_number='12345678').issues)

    def test_stop_continues_after_real_cancel_shape_and_dispatches_remaining_once(self):
        for filled in (0,1):
            with self.subTest(target_fills=filled):
                t=targets.BrokerTargetTests();t.setUp();row=t.native();f=t.f
                f.broker(row,filled,'WORKING','1.10');f.service.observe_orders()
                f.bid='.80';f.ask='.82';f.service.monitor_positions()
                self.assertEqual(f.ledger.requests(journal.BINDING)[-1]['state'],'PENDING_CANCEL')
                records=[(filled,'1.10',f.now.isoformat())] if filled else []
                f.responses[row['broker_id']]=cancellation(row,records,stamp=f.now.isoformat())
                f.service.observe_orders()
                f.bid='.78';f.ask='.80'
                stop=f.service.monitor_positions()[-1]
                self.assertEqual(stop['instruction'],'SELL_TO_CLOSE');self.assertEqual(stop['limit'],'0.78')
                self.assertEqual(stop['quantity'],2-filled)
                calls=f.gateway.submit.call_count;f.service.monitor_positions()
                self.assertEqual(f.gateway.submit.call_count,calls)
                self.assertEqual(calls,3)

    def test_previously_blocked_cancel_recovers_only_from_matching_complete_get(self):
        p=cancellation(self.f.row,stamp=self.f.now.isoformat())
        stored=self.f.vault.data['requests'][self.f.row['id']]
        stored.update(state='RECONCILIATION_REQUIRED',issues=['UNSUPPORTED_EXECUTION_ACTIVITY'])
        wrong=deepcopy(p);wrong['accountNumber']='87654321'
        with self.assertRaises(ValueError):self.f.apply(wrong)
        self.assertEqual(stored['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(self.f.apply(p)['state'],'CANCELED')
