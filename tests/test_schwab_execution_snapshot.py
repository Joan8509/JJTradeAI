"""Cumulative evidence with no broker execution IDs; no production I/O."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase

from schwab_execution_snapshot import normalize_execution_snapshot
from real_order_ledger import RealOrderLedger, RealOrderCoordinator, RealOrderBlocked
from tests import test_real_order_ledger as fixture
from unittest.mock import Mock


def snapshot(row, records, status='WORKING'):
    filled=sum(r[0] for r in records)
    p=fixture.payload(row,status=status,filled=filled)
    p['accountNumber']='12345678'
    p['orderLegCollection'][0]['legId']=1
    p['orderActivityCollection']=[dict(activityType='EXECUTION',executionType='FILL',quantity=q,
        executionLegs=[dict(legId=1,quantity=q,price=price,time=stamp)]) for q,price,stamp in records]
    return p


class CumulativeExecutionTests(TestCase):
    def setUp(self):
        self.vault=fixture.Vault();self.now=fixture.NOW
        self.ledger=RealOrderLedger(lambda:self.vault,lambda:self.now)
        self.gateway=Mock();self.gateway.submit.return_value='123'
        self.coordinator=RealOrderCoordinator(self.ledger,self.gateway,lambda *a:True)
        r=self.ledger.prepare(fixture.BINDING,intent='TEST',contract=fixture.CONTRACT,
            instruction='BUY_TO_OPEN',quantity=3,limit='1',price_increment='.01',
            expires_at=self.now+timedelta(seconds=30))
        self.row=self.coordinator.submit(fixture.BINDING,r['id'])
        self.first=(1,'0.99',self.now.isoformat())

    def apply(self,p):
        return self.ledger.reconcile_snapshot(fixture.BINDING,self.row['id'],p,account_number='12345678')

    def test_receipt_is_not_fill_and_partial_can_be_closed_only_once(self):
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),0)
        r=self.apply(snapshot(self.row,[self.first]))
        self.assertEqual(r['state'],'PARTIALLY_FILLED')
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),1)
        self.assertNotIn('execution_id',next(iter(r['fills'].values())))
        self.assertEqual(r['evidence_mode'],'CUMULATIVE_EXECUTION_RECORD')
        self.apply(snapshot(self.row,[self.first]))
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),1)

    def test_duplicate_identical_records_preserve_multiplicity_and_reordering(self):
        rows=[self.first,self.first,(1,'.98',self.now.isoformat())]
        r=self.apply(snapshot(self.row,rows,'FILLED'))
        self.assertEqual(r['state'],'FILLED');self.assertEqual(len(r['fills']),3)
        self.assertEqual(self.apply(snapshot(self.row,list(reversed(rows)),'FILLED'))['fills'],r['fills'])
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),3)

    def test_restart_does_not_duplicate_and_lost_or_changed_history_blocks(self):
        self.apply(snapshot(self.row,[self.first]))
        self.ledger=RealOrderLedger(lambda:self.vault,lambda:self.now)
        r=self.apply(snapshot(self.row,[(1,'.98',self.now.isoformat())]))
        self.assertEqual(r['state'],'RECONCILIATION_REQUIRED')
        self.assertIn('EXECUTION_HISTORY_REGRESSION',r['issues'])
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),1)

    def test_wrong_account_order_contract_or_leg_never_adopted(self):
        for field,value in [('accountNumber','87654321'),('orderId',999)]:
            p=snapshot(self.row,[self.first]);p[field]=value
            with self.assertRaises((ValueError,RealOrderBlocked)):self.apply(p)
        p=snapshot(self.row,[self.first]);p['orderLegCollection'][0]['instrument']['symbol']='MSFT  261102C00500000'
        with self.assertRaises(RealOrderBlocked):self.apply(p)
        p=snapshot(self.row,[self.first]);p['orderActivityCollection'][0]['executionLegs'][0]['legId']=2
        with self.assertRaises(ValueError):self.apply(p)
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),0)

    def test_average_without_explicit_history_does_not_invent_fills(self):
        p=snapshot(self.row,[self.first]);p['orderActivityCollection']=[];p['averagePrice']=.99
        r=self.apply(p);self.assertEqual(r['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(r['fills'],{})

    def test_invalid_quantities_future_price_and_missing_activity_totals(self):
        for change in ['remaining','activity','future','price','mismarked']:
            with self.subTest(change=change):
                p=snapshot(self.row,[self.first])
                if change=='remaining':p['remainingQuantity']=3
                if change=='activity':p['orderActivityCollection'][0]['quantity']=2
                if change=='future':p['orderActivityCollection'][0]['executionLegs'][0]['time']=(self.now+timedelta(seconds=1)).isoformat()
                if change=='price':p['orderActivityCollection'][0]['executionLegs'][0]['price']='1.01'
                if change=='mismarked':p['orderActivityCollection'][0]['executionLegs'][0]['mismarkedQuantity']=1
                try:r=self.apply(p)
                except ValueError:continue
                self.assertEqual(r['state'],'RECONCILIATION_REQUIRED');self.assertEqual(r['fills'],{})

    def test_cancel_race_preserves_fill_and_releases_only_remainder(self):
        self.apply(snapshot(self.row,[self.first]))
        self.coordinator.cancel(fixture.BINDING,self.row['id'])
        r=self.apply(snapshot(self.row,[self.first],'CANCELED'))
        self.assertEqual(r['state'],'CANCELED')
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),1)
        self.assertEqual(self.apply(snapshot(self.row,[self.first]))['state'],'RECONCILIATION_REQUIRED')

    def test_terminal_zero_remaining_does_not_infer_any_additional_fill(self):
        p=snapshot(self.row,[self.first],'CANCELED');p['remainingQuantity']=0
        row=self.apply(p)
        self.assertEqual(row['state'],'CANCELED')
        self.assertEqual(self.ledger.available_to_close(fixture.BINDING,fixture.CONTRACT),1)

    def test_cannot_switch_evidence_model_and_no_anonymous_order_adoption(self):
        self.apply(snapshot(self.row,[self.first]))
        p=fixture.payload(self.row,filled=1,price='.99')
        r=self.ledger.reconcile(fixture.BINDING,self.row['id'],p)
        self.assertIn('EXECUTION_EVIDENCE_MODE_CHANGED',r['issues'])

    def test_snapshot_schema_requires_full_history_and_rejects_children(self):
        p=snapshot(self.row,[self.first])
        for mutate in [lambda p:p.pop('orderActivityCollection'),lambda p:p.update(childOrderStrategies=[{}]),
                       lambda p:p.update(replacingOrderCollection=[{}]),lambda p:p.update(quantity=True)]:
            other=deepcopy(p);mutate(other)
            with self.assertRaises((ValueError,KeyError)):
                normalize_execution_snapshot(other,account_number='12345678')

    def test_explicit_zero_fills_does_not_require_an_empty_activity_array(self):
        p=snapshot(self.row,[]);p.pop('orderActivityCollection')
        row=self.apply(p)
        self.assertEqual(row['state'],'WORKING');self.assertEqual(row['fills'],{})

    def test_rejected_zero_remaining_null_history_reconciles_uncertain_cancel(self):
        self.coordinator.cancel(fixture.BINDING,self.row['id'])
        p=snapshot(self.row,[],'REJECTED')
        p.update(remainingQuantity=0,orderActivityCollection=None)
        row=self.apply(p)
        self.assertEqual(row['state'],'REJECTED')
        self.assertEqual(row['fills'],{})
        self.assertEqual(row['terminal_state'],'REJECTED')

    def test_null_history_never_erases_or_invents_filled_executions(self):
        p=snapshot(self.row,[self.first]);p['orderActivityCollection']=None
        with self.assertRaisesRegex(ValueError,'COMPLETE_ACTIVITY'):self.apply(p)

    def test_order_observation_during_cancel_keeps_inflight_state_then_terminal_fill_wins(self):
        self.ledger.begin_cancel(fixture.BINDING,self.row['id'])
        row=self.apply(snapshot(self.row,[],'WORKING'))
        self.assertEqual(row['state'],'CANCEL_SUBMITTING')
        row=self.apply(snapshot(self.row,[(3,'.99',self.now.isoformat())],'FILLED'))
        self.assertEqual(row['state'],'FILLED')
        row=self.ledger.cancel_result(fixture.BINDING,self.row['id'],accepted=True)
        self.assertEqual(row['state'],'FILLED')
        self.assertEqual(sum(f['quantity'] for f in row['fills'].values()),3)
