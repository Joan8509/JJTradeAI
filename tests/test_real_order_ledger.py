"""No production writes: durable protocol tests with an isolated memory vault."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from real_order_ledger import RealOrderLedger,RealOrderCoordinator,RealOrderBlocked,production_gateway,RealOrderStore

NOW=datetime(2026,10,30,19,tzinfo=timezone.utc)
BINDING='a'*64
CONTRACT='AAPL  261102C00350000'


class Vault:
    def __init__(self):
        self.data=None;self.mutex=RLock();self.path=SimpleNamespace(exists=lambda:self.data is not None)
    @contextmanager
    def locked(self):
        with self.mutex:yield
    def load(self):return deepcopy(self.data)
    def save(self,value):self.data=deepcopy(value)


def payload(row,*,status='WORKING',filled=0,price='1.00'):
    return dict(orderId=int(row['broker_id']),quantity=row['quantity'],filledQuantity=filled,
        remainingQuantity=row['quantity']-filled,status=status,orderStrategyType='SINGLE',
        orderLegCollection=[dict(instruction=row['instruction'],quantity=row['quantity'],
            instrument=dict(symbol=row['contract'],assetType='OPTION'))],
        orderActivityCollection=[dict(executionType='FILL',activityId=123,executionLegs=[
            dict(legId=1,quantity=filled,price=price,time=NOW.isoformat())])] if filled else [])


class RealOrderJournalTests(TestCase):
    def setUp(self):
        self.vault=Vault();self.now=NOW
        self.ledger=RealOrderLedger(lambda:self.vault,lambda:self.now)
        self.gateway=Mock();self.gateway.submit.return_value='100'
        self.coordinator=RealOrderCoordinator(self.ledger,self.gateway,lambda *args:True)

    def prepare(self,**changes):
        args=dict(intent='SIGNAL_1',contract=CONTRACT,instruction='BUY_TO_OPEN',quantity=3,
            limit='1.00',price_increment='.01',expires_at=self.now+timedelta(seconds=30))
        args.update(changes);return self.ledger.prepare(BINDING,**args)

    def submitted(self,**changes):
        row=self.prepare(**changes);return self.coordinator.submit(BINDING,row['id'])

    def own(self):
        row=self.submitted();return self.ledger.reconcile(BINDING,row['id'],payload(row,status='FILLED',filled=3))

    def test_construction_has_no_io_and_production_gateway_is_not_available(self):
        factory=Mock();RealOrderLedger(factory);factory.assert_not_called()
        self.assertEqual(RealOrderStore().path.name,'real_orders.dpapi')
        with self.assertRaisesRegex(RealOrderBlocked,'LIVE_PROTOCOL_NOT_VERIFIED'):production_gateway()

    def test_committed_before_gateway_and_acknowledgment_is_not_a_fill(self):
        def submit(row):
            self.assertEqual(self.vault.data['requests'][row['id']]['state'],'SUBMITTING')
            return '100'
        self.gateway.submit.side_effect=submit
        row=self.submitted()
        self.assertEqual(row['state'],'ACKNOWLEDGED')
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),0)

    def test_missing_grant_never_changes_state_or_calls_gateway(self):
        row=self.prepare();self.coordinator.grant=lambda *args:False
        with self.assertRaisesRegex(RealOrderBlocked,'NOT_AUTHORIZED'):self.coordinator.submit(BINDING,row['id'])
        self.gateway.submit.assert_not_called()
        self.assertEqual(self.ledger.requests(BINDING)[0]['state'],'PREPARED')

    def test_failed_durable_claim_prevents_any_network_call(self):
        row=self.prepare();self.vault.save=Mock(side_effect=OSError('SYNTHETIC_DISK_FULL'))
        with self.assertRaises(OSError):self.coordinator.submit(BINDING,row['id'])
        self.gateway.submit.assert_not_called()
        self.assertEqual(self.ledger.requests(BINDING)[0]['state'],'PREPARED')

    def test_ack_save_failure_leaves_claim_uncertain_and_cannot_duplicate(self):
        row=self.prepare();original=self.vault.save
        def save(doc):
            if doc['requests'][row['id']]['state']=='ACKNOWLEDGED':raise OSError('SYNTHETIC')
            original(doc)
        self.vault.save=save
        with self.assertRaises(OSError):self.coordinator.submit(BINDING,row['id'])
        self.assertEqual(self.ledger.requests(BINDING)[0]['state'],'SUBMITTING')
        with self.assertRaises(RealOrderBlocked):self.coordinator.submit(BINDING,row['id'])
        self.gateway.submit.assert_called_once()

    def test_timeout_and_restart_do_not_resubmit_or_adopt_similar_order(self):
        self.gateway.submit.side_effect=TimeoutError('SYNTHETIC')
        row=self.submitted();self.assertEqual(row['state'],'UNCERTAIN')
        restarted=RealOrderCoordinator(RealOrderLedger(lambda:self.vault,lambda:self.now),self.gateway,lambda *a:True)
        with self.assertRaisesRegex(RealOrderBlocked,'ALREADY_DISPATCHED'):restarted.submit(BINDING,row['id'])
        self.assertEqual(self.gateway.submit.call_count,1)
        similar=payload(dict(row,broker_id='100'),status='FILLED',filled=3)
        with self.assertRaisesRegex(RealOrderBlocked,'IDENTITY_MISMATCH'):self.ledger.reconcile(BINDING,row['id'],similar)
        with self.assertRaisesRegex(RealOrderBlocked,'UNCERTAIN_ORDER'):self.prepare(intent='OTHER',contract='MSFT  261102C00500000')

    def test_crash_after_claim_stays_blocked_on_restart(self):
        row=self.prepare();self.ledger.begin_submit(BINDING,row['id'])
        with self.assertRaisesRegex(RealOrderBlocked,'ALREADY_DISPATCHED'):self.coordinator.submit(BINDING,row['id'])
        self.gateway.submit.assert_not_called()

    def test_same_intent_is_bound_once_and_changed_payload_cannot_replace_it(self):
        row=self.prepare();self.assertEqual(self.prepare()['id'],row['id'])
        with self.assertRaisesRegex(RealOrderBlocked,'INTENT_ALREADY_BOUND'):self.prepare(quantity=2)

    def test_competing_dispatches_only_one_reaches_gateway(self):
        row=self.prepare()
        def send():
            try:return self.coordinator.submit(BINDING,row['id'])['state']
            except RealOrderBlocked:return 'BLOCKED'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:send(),range(2)))
        self.assertEqual(sorted(results),['ACKNOWLEDGED','BLOCKED'])
        self.gateway.submit.assert_called_once()

    def test_partial_fills_are_only_owned_quantity_and_close_is_reserved(self):
        row=self.submitted();self.ledger.reconcile(BINDING,row['id'],payload(row,filled=1))
        with self.assertRaisesRegex(RealOrderBlocked,'NOT_OWNED'):self.prepare(intent='SELL1',instruction='SELL_TO_CLOSE',quantity=2)
        close=self.prepare(intent='SELL1',instruction='SELL_TO_CLOSE',quantity=1)
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),0)
        with self.assertRaisesRegex(RealOrderBlocked,'NOT_OWNED'):self.prepare(intent='SELL2',instruction='SELL_TO_CLOSE',quantity=1)
        self.gateway.submit.return_value='101'
        close=self.coordinator.submit(BINDING,close['id'])
        self.ledger.reconcile(BINDING,close['id'],payload(close,status='FILLED',filled=1))
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),0)

    def test_external_position_is_never_owned_and_wrong_account_cannot_cancel(self):
        with self.assertRaisesRegex(RealOrderBlocked,'NOT_OWNED'):self.prepare(intent='EXTERNAL',instruction='SELL_TO_CLOSE')
        row=self.submitted()
        with self.assertRaisesRegex(RealOrderBlocked,'NOT_OWNED'):self.coordinator.cancel('b'*64,row['id'])
        self.gateway.cancel.assert_not_called()

    def test_cancel_acceptance_keeps_quantity_reserved_until_broker_confirms(self):
        self.own();row=self.prepare(intent='CLOSE',instruction='SELL_TO_CLOSE')
        self.gateway.submit.return_value='101';row=self.coordinator.submit(BINDING,row['id'])
        self.gateway.cancel.return_value=True;row=self.coordinator.cancel(BINDING,row['id'])
        self.assertEqual(row['state'],'PENDING_CANCEL')
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),0)
        self.ledger.reconcile(BINDING,row['id'],payload(row,status='CANCELED'))
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),3)

    def test_cancel_timeout_remains_uncertain_without_duplicate_request(self):
        row=self.submitted();self.gateway.cancel.side_effect=TimeoutError()
        row=self.coordinator.cancel(BINDING,row['id']);self.assertEqual(row['state'],'CANCEL_UNCERTAIN')
        with self.assertRaisesRegex(RealOrderBlocked,'NOT_READY'):self.coordinator.cancel(BINDING,row['id'])
        self.gateway.cancel.assert_called_once()

    def test_expired_request_never_dispatches(self):
        row=self.prepare();self.now+=timedelta(seconds=30)
        with self.assertRaisesRegex(RealOrderBlocked,'REQUEST_EXPIRED'):self.coordinator.submit(BINDING,row['id'])
        self.gateway.submit.assert_not_called()

    def test_duplicate_broker_id_is_uncertain(self):
        self.own();row=self.submitted(intent='NEW')
        self.assertEqual(row['state'],'UNCERTAIN');self.assertIsNone(row['broker_id'])

    def test_changed_fill_identity_or_limit_violation_is_not_accounted(self):
        row=self.submitted();self.ledger.reconcile(BINDING,row['id'],payload(row,filled=1))
        bad=payload(row,filled=1,price='1.01')
        result=self.ledger.reconcile(BINDING,row['id'],bad)
        self.assertEqual(result['state'],'RECONCILIATION_REQUIRED')
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),1)
        self.assertIn('LIMIT_PRICE_VIOLATION',result['issues'])

    def test_terminal_evidence_never_regresses_even_after_invalid_read(self):
        row=self.own();bad=payload(row,filled=0)
        first=self.ledger.reconcile(BINDING,row['id'],bad)
        second=self.ledger.reconcile(BINDING,row['id'],bad)
        self.assertIn('TERMINAL_STATE_CHANGED',first['issues'])
        self.assertIn('TERMINAL_STATE_CHANGED',second['issues'])
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),3)

    def test_fill_before_request_creation_is_not_owned(self):
        row=self.submitted();bad=payload(row,filled=1)
        bad['orderActivityCollection'][0]['executionLegs'][0]['time']=(NOW-timedelta(seconds=1)).isoformat()
        result=self.ledger.reconcile(BINDING,row['id'],bad)
        self.assertIn('EXECUTION_TIME_UNPROVEN',result['issues'])
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),0)

    def test_equivalent_price_and_timezone_representations_are_not_regressions(self):
        row=self.submitted();self.ledger.reconcile(BINDING,row['id'],payload(row,filled=1,price='1.00'))
        equivalent=payload(row,filled=1,price='1.0')
        equivalent['orderActivityCollection'][0]['executionLegs'][0]['time']=NOW.isoformat().replace('+00:00','Z')
        result=self.ledger.reconcile(BINDING,row['id'],equivalent)
        self.assertEqual(result['state'],'PARTIALLY_FILLED');self.assertEqual(result['issues'],[])

    def test_order_proven_not_attempted_expires_without_freezing_the_account(self):
        from schwab_order_gateway import OrderNotDispatched
        self.gateway.submit.side_effect=OrderNotDispatched('ORDER_REQUEST_NOT_CURRENT')
        row=self.submitted()
        self.assertEqual(row['state'],'EXPIRED');self.assertIn('ORDER_HTTP_NOT_ATTEMPTED',row['issues'])
        self.assertIsNone(row['broker_id']);self.assertEqual(row['fills'],{})
        self.prepare(intent='DIFFERENT_SIGNAL',contract='MSFT  261102C00500000')
        with self.assertRaises(RealOrderBlocked):self.coordinator.submit(BINDING,row['id'])
        self.gateway.submit.assert_called_once()

    def test_cancel_proven_not_attempted_retains_order_and_reserved_quantity(self):
        from schwab_order_gateway import OrderNotDispatched
        self.own();close=self.prepare(intent='CLOSE',instruction='SELL_TO_CLOSE')
        self.gateway.submit.return_value='101';close=self.coordinator.submit(BINDING,close['id'])
        self.gateway.cancel.side_effect=OrderNotDispatched('ORDER_AUTHORIZATION_UNAVAILABLE')
        result=self.coordinator.cancel(BINDING,close['id'])
        self.assertEqual(result['state'],'ACKNOWLEDGED');self.assertFalse(result['cancel_requested'])
        self.assertEqual(self.ledger.available_to_close(BINDING,CONTRACT),0)
        self.gateway.cancel.side_effect=None;self.gateway.cancel.return_value=True
        self.assertEqual(self.coordinator.cancel(BINDING,close['id'])['state'],'PENDING_CANCEL')
