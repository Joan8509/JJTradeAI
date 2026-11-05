"""Real preparation uses synthetic readers/quotes and encrypted-store substitutes."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
import json
from io import BytesIO

from real_trade_preparation import RealPreparationSession,RealPreparationStore,normalize_rows,PreparationError
from real_account_readonly import AccountReadOnlySession
from tests import test_automatic_entry_queue as queue_fixture
from tests.test_real_account_readonly import client_fixture


class MemoryPreparationStore:
    def __init__(self):self.value=None;self.path=SimpleNamespace(exists=lambda:self.value is not None)
    def locked(self):return nullcontext()
    def load(self):return deepcopy(self.value)
    def save(self,value):self.value=deepcopy(value)


class RealPreparationTests(TestCase):
    def setUp(self):
        self.h=queue_fixture.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.store=MemoryPreparationStore();self.account_client=client_fixture()
        self.reader=AccountReadOnlySession(lambda:self.account_client,lambda:self.h.f.now)
        self.reference=self.reader.load_accounts()['choices'][0]['ref'];self.reader.load_snapshot(self.reference)
        self.binding=self.reader.preparation_binding(self.reference)
        self.state=self.h.f.state
        self.state['detector_first_at']=self.h.f.now.isoformat()
        self.state['tick']['geometry']=dict(price=104,opening=100,upper=102.5,lower=96.75,mid=99.625,
            previous_upper=102,previous_lower=97,previous_mid=99.5)
        self.factory=Mock(return_value=self.h.f.market)
        self.service=RealPreparationSession(store_factory=lambda:self.store,market_factory=self.factory,
            read_state=lambda symbol:deepcopy(self.state),clock=lambda:self.h.f.now)
        self.rows=[dict(symbol='AMZN',quantity=2,target='20')]

    def save(self):return self.service.save(self.binding,self.rows)

    def broker(self,change=None):
        from schwab_preview_client import SchwabPreviewClient
        opener=Mock()
        def response(request,**kwargs):
            self.assertTrue(request.full_url.endswith('/previewOrder'))
            self.assertNotIn('/orders',request.full_url)
            strategy=json.loads(request.data)['orderStrategy']
            strategy.update(filledQuantity=0,remainingQuantity=strategy['quantity'],
                orderBalance=dict(projectedAvailableFund=500,projectedBuyingPower=500,projectedCommission=1))
            raw=dict(orderStrategy=strategy,orderValidationResult=dict(alerts=[],rejects=[],reviews=[],warns=[],
                accepts=[dict(originalSeverity='ACCEPT',overrideSeverity='ACCEPT')]))
            if change:change(raw)
            result=BytesIO(json.dumps(raw).encode());result.status=200
            return result
        opener.open.side_effect=response
        def factory(context):
            context.oauth.access.return_value='SYNTHETIC_ACCESS'
            return SchwabPreviewClient(context,opener=opener,utcnow=lambda:self.h.f.now)
        self.service._broker_client_factory=Mock(side_effect=factory)
        return opener

    def test_construction_and_editing_have_no_vault_or_market_effect(self):
        factory=Mock(side_effect=AssertionError('NO_IO'))
        RealPreparationSession(store_factory=factory,market_factory=factory)
        factory.assert_not_called()
        for row in [dict(symbol='AMZN',quantity=True,target='20'),dict(symbol='AMZN',quantity=0,target='20'),
                    dict(symbol='AMZN',quantity=1,target=None),dict(symbol='AMZN',quantity=1,target='15')]:
            with self.assertRaises(PreparationError):normalize_rows([row])
        with self.assertRaises(PreparationError):normalize_rows(self.rows*2)

    def test_separate_store_and_per_account_saved_plans_without_execution(self):
        from real_account_readonly import AccountReadOnlyStore
        from schwab_connection import EncryptedSchwabStore
        self.assertNotEqual(RealPreparationStore().path,AccountReadOnlyStore().path)
        self.assertNotEqual(RealPreparationStore().path,EncryptedSchwabStore().path)
        self.save();other='b'*64
        self.service.save(other,[dict(symbol='AAPL',quantity=1,target='MANUAL')])
        self.assertEqual(self.service.load(self.binding)['rows'],self.rows)
        self.assertFalse(self.service.preparation['real_orders_enabled'])
        self.assertFalse(self.service.preparation['live_risk_authorized'])
        self.assertEqual(self.h.f.engine.ledger.orders(),[]);self.assertEqual(self.h.store.plans(),[])
        self.factory.assert_not_called()

    def test_local_preview_chooses_eligible_contract_and_never_submits(self):
        self.save();result=self.service.preview(self.reader,self.reference,'AMZN')
        self.assertEqual(result['state'],'SHADOW_TICKET_PREPARED',result)
        ticket=result['ticket']
        self.assertFalse(ticket['sendable']);self.assertFalse(ticket['real_orders_enabled'])
        self.assertEqual(ticket['mode'],'REAL_SHADOW_ONLY');self.assertEqual(ticket['side'],'CALL')
        self.assertEqual(ticket['quantity'],2);self.assertEqual(ticket['premium_cost'],'400.0')
        self.assertIsNone(ticket['commissions']);self.assertIsNone(ticket['total_cost'])
        self.assertIn('OPTION_BUYING_POWER_NOT_VERIFIED',ticket['blockers'])
        self.assertIn('LIVE_EXECUTION_DISABLED',ticket['blockers'])
        self.assertEqual(self.h.f.engine.ledger.orders(),[]);self.assertEqual(self.h.store.plans(),[])
        self.assertNotIn('111122223333',json.dumps(ticket));self.assertNotIn('SYNTHETIC_ACCOUNT_HASH',json.dumps(ticket))
        self.assertEqual(len(self.store.value['profiles'][self.binding]['tickets']),1)

    def test_broker_preview_is_bound_to_ticket_and_still_cannot_send_or_fill(self):
        self.save();opener=self.broker()
        result=self.service.preview(self.reader,self.reference,'AMZN',consult_broker=True)
        self.assertEqual(result['state'],'SHADOW_TICKET_PREPARED',result)
        ticket=result['ticket'];report=ticket['broker_preview']
        self.assertEqual(ticket['mode'],'REAL_PREVIEW_ONLY')
        self.assertEqual(report['state'],'PREVIEW_ACCEPT_REPORTED')
        self.assertFalse(ticket['sendable']);self.assertFalse(report['send_authorized'])
        self.assertEqual(self.h.f.engine.ledger.orders(),[]);self.assertEqual(self.h.store.plans(),[])
        self.assertNotIn('111122223333',json.dumps(ticket))
        opener.open.assert_called_once()

    def test_broker_rejection_does_not_become_permission_or_an_order(self):
        self.save();self.broker(lambda raw:raw['orderValidationResult']['rejects'].append(dict(originalSeverity='REJECT')))
        result=self.service.preview(self.reader,self.reference,'AMZN',consult_broker=True)
        self.assertEqual(result['state'],'SHADOW_TICKET_PREPARED',result)
        ticket=result['ticket']
        self.assertEqual(ticket['broker_preview']['state'],'PREVIEW_REQUIRES_REVIEW')
        self.assertIn('BROKER_PREVIEW_REQUIRES_REVIEW',ticket['blockers'])
        self.assertFalse(ticket['sendable']);self.assertEqual(self.h.f.engine.ledger.orders(),[])

    def test_plan_changes_during_preview_discard_the_response_without_retry(self):
        self.save()
        def change(raw):self.service.save(self.binding,[dict(symbol='AMZN',quantity=9,target='100')])
        opener=self.broker(change)
        result=self.service.preview(self.reader,self.reference,'AMZN',consult_broker=True)
        self.assertEqual(result['state'],'PREPARATION_CHANGED',result)
        self.assertEqual(self.store.value['profiles'][self.binding]['tickets'],[])
        opener.open.assert_called_once()

    def test_preview_expiring_during_http_does_not_save_a_stale_ticket(self):
        self.save()
        def change(raw):self.h.f.now+=timedelta(seconds=4)
        opener=self.broker(change)
        result=self.service.preview(self.reader,self.reference,'AMZN',consult_broker=True)
        self.assertNotEqual(result['state'],'SHADOW_TICKET_PREPARED')
        self.assertEqual(self.store.value['profiles'][self.binding]['tickets'],[])
        self.assertEqual(self.h.f.engine.ledger.orders(),[]);opener.open.assert_called_once()

    def test_preview_context_is_private_and_requires_explicit_recent_selection(self):
        context=self.reader.preview_context(self.reference)
        self.assertEqual(context.binding,self.binding)
        self.assertNotIn('111122223333',repr(context));self.assertNotIn('SYNTHETIC_ACCOUNT_HASH',repr(context))
        with self.assertRaises(Exception):self.reader.preview_context(None)
        self.h.f.now+=timedelta(seconds=61)
        with self.assertRaises(Exception):self.reader.preview_context(self.reference)

    def test_stale_account_or_restricted_account_prevents_market_reads(self):
        self.save();self.h.f.now+=timedelta(seconds=61)
        self.assertEqual(self.service.preview(self.reader,self.reference,'AMZN')['state'],'ACCOUNT_READING_NOT_CURRENT')
        self.factory.assert_not_called()
        self.h.f.now-=timedelta(seconds=61);self.reader.snapshot['closing_only_restricted']=True
        self.assertEqual(self.service.preview(self.reader,self.reference,'AMZN')['state'],'ACCOUNT_CLOSING_ONLY')
        self.factory.assert_not_called()

    def test_invalid_signal_or_expired_window_prevents_contract_search(self):
        self.save();self.state['tick']['geometry']['upper']=102.1
        self.assertEqual(self.service.preview(self.reader,self.reference,'AMZN')['state'],'SIGNAL_GEOMETRY_NOT_VALID')
        self.factory.assert_not_called()
        self.state['tick']['geometry']['upper']=102.5
        self.state['detector_first_at']=(self.h.f.now-timedelta(seconds=30)).isoformat()
        self.assertEqual(self.service.preview(self.reader,self.reference,'AMZN')['state'],'SIGNAL_ENTRY_WINDOW_EXPIRED')
        self.factory.assert_not_called()

    def test_missing_first_evidence_does_not_invent_new_clock(self):
        self.save();self.state['detector_first_at']=None
        self.assertEqual(self.service.preview(self.reader,self.reference,'AMZN')['state'],'SIGNAL_CLOCK_UNAVAILABLE')
        self.factory.assert_not_called()

    def test_changed_preparation_during_lookup_does_not_save_stale_ticket(self):
        self.save();lookup=self.h.f.market.get_catalog_chain
        def changed(*args):
            self.service.save(self.binding,[dict(symbol='AMZN',quantity=9,target='100')])
            return lookup(*args)
        with patch.object(self.h.f.market,'get_catalog_chain',side_effect=changed):
            result=self.service.preview(self.reader,self.reference,'AMZN')
        self.assertEqual(result['state'],'PREPARATION_CHANGED')
        self.assertEqual(self.store.value['profiles'][self.binding]['tickets'],[])

    def test_failed_preview_clears_previous_success_but_preserves_history(self):
        self.save();self.assertEqual(self.service.preview(self.reader,self.reference,'AMZN')['state'],'SHADOW_TICKET_PREPARED')
        self.state['tick']['signal']=None
        result=self.service.preview(self.reader,self.reference,'AMZN')
        self.assertEqual(result['state'],'NO_CURRENT_SIGNAL');self.assertNotIn('ticket',result)
        self.assertEqual(len(self.store.value['profiles'][self.binding]['tickets']),1)

    def test_load_failure_clears_previous_account_view(self):
        self.save()
        with patch.object(self.store,'load',side_effect=RuntimeError('PRIVATE_DETAILS')):
            with self.assertRaises(RuntimeError):self.service.load('b'*64)
        self.assertIsNone(self.service.preparation)
        self.assertIsNone(self.service.account_binding)

    def test_put_maps_from_lower_signal_with_no_call_fallback(self):
        self.save();self.state['tick']['signal'].update(side='INFERIOR',price=96)
        self.state['tick']['geometry'].update(price=96,upper=102.25,lower=96.5,mid=99.375)
        self.state['tick']['opening']=100
        market=Mock();market.symbol='AMZN';market.side='PUT'
        # No PUT calendar/data in fixture: must remain blocked, not select CALL.
        self.h.f.client.full_chain.side_effect=lambda *args:dict(self.h.f.payload,callExpDateMap={},putExpDateMap={})
        result=self.service.preview(self.reader,self.reference,'AMZN')
        self.assertNotEqual(result['state'],'SHADOW_TICKET_PREPARED')
        self.h.f.client.full_chain.assert_called_once()
        self.assertEqual(self.h.f.client.full_chain.call_args.args[1],'PUT')
