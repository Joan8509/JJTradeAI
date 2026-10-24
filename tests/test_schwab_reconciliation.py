import unittest

from schwab_reconciliation import normalize_order,reconcile_read_only


def order_payload():
    return {'orderId':100,'quantity':3,'filledQuantity':1,'remainingQuantity':2,'status':'WORKING',
        'orderStrategyType':'SINGLE','orderLegCollection':[{'instruction':'BUY_TO_OPEN','quantity':3,
        'instrument':{'assetType':'OPTION','symbol':'SYNTHETIC_OPTION'}}],
        'orderActivityCollection':[{'executionType':'FILL','activityId':1,'executionLegs':[
            {'legId':1,'quantity':1,'price':2.,'time':'2026-10-16T14:00:01Z'}]}]}


class SchwabReconciliationTests(unittest.TestCase):
    def test_partial_execution_and_cancel_request_are_separate_from_canceled(self):
        payload=order_payload()
        self.assertEqual(normalize_order(payload).status,'PARTIALLY_FILLED')
        payload['status']='PENDING_CANCEL'
        self.assertEqual(normalize_order(payload).status,'PENDING_CANCEL')
        payload['status']='CANCELED'
        result=normalize_order(payload)
        self.assertEqual(result.status,'CANCELED');self.assertEqual(result.filled_quantity,1)

    def test_average_or_filled_quantity_cannot_invent_missing_executions(self):
        payload=order_payload();payload['orderActivityCollection']=[]
        result=normalize_order(payload)
        self.assertEqual(result.fills,())
        self.assertIn('EXECUTION_DETAILS_INCOMPLETE',result.issues)

    def test_unstable_execution_identity_and_unknown_status_block(self):
        payload=order_payload();del payload['orderActivityCollection'][0]['activityId'];payload['status']='FUTURE_NEW_STATE'
        result=normalize_order(payload)
        self.assertIn('EXECUTION_IDENTITY_UNPROVEN',result.issues)
        self.assertIn('UNKNOWN_BROKER_STATE',result.issues)

    def test_ambiguous_unknown_submission_never_adopted_by_similar_symbol(self):
        actual=normalize_order(order_payload())
        expected=[{'broker_id':None,'contract':actual.contract,'instruction':actual.instruction,'quantity':3}]
        result=reconcile_read_only(expected,[actual],[],{})
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('UNCERTAIN_SUBMISSION_REQUIRES_REVIEW',result['issues'])
        self.assertEqual(result['orders_sent'],0)

    def test_known_identity_and_exact_account_positions_reconcile_without_writes(self):
        actual=normalize_order(order_payload())
        expected=[{'broker_id':'100','contract':actual.contract,'instruction':actual.instruction,'quantity':3,'filled_quantity':1}]
        positions=[{'instrument':{'assetType':'OPTION','symbol':actual.contract},'longQuantity':1,'shortQuantity':0}]
        result=reconcile_read_only(expected,[actual],positions,{actual.contract:1})
        self.assertEqual(result['status'],'RECONCILED')
        self.assertEqual(result['positions_modified'],0)

    def test_unexplained_manual_position_drift_does_not_get_erased_or_attached(self):
        positions=[{'instrument':{'assetType':'OPTION','symbol':'MANUAL_CONTRACT'},'longQuantity':2,'shortQuantity':0}]
        result=reconcile_read_only([],[],positions,{})
        self.assertIn('POSITION_MISMATCH',result['issues']);self.assertEqual(len(positions),1)

    def test_complex_short_fractional_or_overfilled_orders_rejected(self):
        for changes in ({'quantity':.5},{'filledQuantity':4},{'childOrderStrategies':[{}]}):
            payload=order_payload();payload.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):normalize_order(payload)


if __name__=='__main__':unittest.main()
