"""Injected HTTP responses only. Production gateway factory is never enabled."""
from datetime import timedelta
from io import BytesIO
import json,traceback
from unittest import TestCase
from unittest.mock import Mock,patch
from urllib.error import HTTPError

from schwab_connection import SchwabError
from schwab_order_gateway import SchwabOrderGateway,OrderNotDispatched
from schwab_order_receipt import cancellation_accepted
from schwab_option_order_request import prepare_option_limit
from real_order_ledger import RealOrderCoordinator
from tests import test_real_order_ledger as journal_fixture
from tests import test_schwab_option_order_request as request_fixture

ACCOUNT='SYNTHETIC_ACCOUNT_HASH'
BINDING=journal_fixture.BINDING
NOW=request_fixture.NOW


class Response(BytesIO):
    def __init__(self,status,body=b'',headers=None):
        super().__init__(body);self.status=status;self.headers=headers or {}


class OrderGatewayTests(TestCase):
    def setUp(self):
        self.now=NOW;self.elapsed=0.
        self.opener=Mock();self.oauth=Mock();self.oauth.access.return_value='SYNTHETIC_ACCESS'
        self.guard=Mock(return_value=True)
        self.draft=prepare_option_limit(request_fixture.contract(),instruction='BUY_TO_OPEN',quantity=2,
            now=NOW,valid_until=NOW+timedelta(seconds=20))
        self.provider=Mock(return_value=self.draft)
        self.row=dict(id='1'*32,account=BINDING,state='SUBMITTING',contract=self.draft.contract,
            instruction=self.draft.instruction,quantity=self.draft.quantity,limit=str(self.draft.limit),
            expires_at=(NOW+timedelta(seconds=20)).isoformat(),broker_id=None)
        self.gateway=SchwabOrderGateway(account_hash=ACCOUNT,account_binding=BINDING,oauth=self.oauth,
            draft_provider=self.provider,commit_guard=self.guard,opener=self.opener,
            clock=lambda:self.elapsed,sleeper=self.sleep,utcnow=lambda:self.now)
    def sleep(self,seconds):
        self.elapsed+=seconds;self.now+=timedelta(seconds=seconds)
    def good_submit(self):
        return Response(201,headers={'Location':'https://api.schwabapi.com/trader/v1/accounts/'+ACCOUNT+'/orders/100'})

    def test_construction_does_not_connect_or_expose_profile(self):
        self.opener.open.assert_not_called();self.oauth.access.assert_not_called();self.provider.assert_not_called()
        self.assertNotIn(ACCOUNT,repr(self.gateway));self.assertNotIn(BINDING,repr(self.gateway))

    def test_preparing_tls_once_does_not_access_account_or_send_http(self):
        self.gateway._opener=None
        with patch('schwab_order_gateway.ssl.create_default_context') as tls,patch(
                'schwab_order_gateway.build_opener',return_value=self.opener) as build:
            self.gateway.prepare_transport();self.gateway.prepare_transport()
        tls.assert_called_once();build.assert_called_once()
        self.oauth.access.assert_not_called();self.opener.open.assert_not_called()
        self.provider.assert_not_called();self.guard.assert_not_called()

    def test_proven_pre_http_failure_is_distinct_from_ambiguous_network_failure(self):
        self.guard.return_value=False
        with self.assertRaises(OrderNotDispatched):self.gateway.submit(self.row)
        self.opener.open.assert_not_called()
        self.guard.return_value=True;self.opener.open.side_effect=TimeoutError()
        with self.assertRaises(SchwabError) as failed:self.gateway.submit(self.row)
        self.assertNotIsInstance(failed.exception,OrderNotDispatched)

    def test_post_uses_frozen_limit_payload_bound_account_and_documented_receipt(self):
        self.opener.open.return_value=self.good_submit()
        self.assertEqual(self.gateway.submit(self.row),'100')
        call=self.opener.open.call_args;req=call.args[0]
        self.assertEqual(req.get_method(),'POST');self.assertEqual(call.kwargs['timeout'],15)
        self.assertEqual(req.full_url,'https://api.schwabapi.com/trader/v1/accounts/'+ACCOUNT+'/orders')
        self.assertEqual(json.loads(req.data),self.draft.payload(self.now));self.assertEqual(self.guard.call_count,2)

    def test_wrong_account_uncommitted_state_or_denied_guard_never_connects(self):
        for row in (dict(self.row,account='b'*64),dict(self.row,state='PREPARED'),dict(self.row,id='INVALID')):
            with self.assertRaises(SchwabError):self.gateway.submit(row)
        self.guard.return_value=False
        with self.assertRaises(SchwabError):self.gateway.submit(self.row)
        self.opener.open.assert_not_called();self.oauth.access.assert_not_called()

    def test_payload_mutation_cannot_change_committed_contract_limit_or_quantity(self):
        for field,value in (('quantity',3),('limit','1.01'),('instruction','SELL_TO_OPEN'),('contract','OTHER')):
            with self.subTest(field=field),self.assertRaises(SchwabError):self.gateway.submit(dict(self.row,**{field:value}))
        self.opener.open.assert_not_called()

    def test_expiry_and_readiness_rechecked_after_token_refresh_and_wait(self):
        def expire(_):self.now+=timedelta(seconds=30);return 'SYNTHETIC_ACCESS'
        self.oauth.access.side_effect=expire
        with self.assertRaisesRegex(SchwabError,'NOT_CURRENT'):self.gateway.submit(self.row)
        self.opener.open.assert_not_called()
        self.now=NOW;self.oauth.access.side_effect=None;self.guard.side_effect=[True,False]
        with self.assertRaisesRegex(SchwabError,'NOT_READY'):self.gateway.submit(self.row)
        self.opener.open.assert_not_called()

    def test_no_retry_after_timeout_invalid_receipt_or_http_error(self):
        for response in (TimeoutError('SYNTHETIC_SECRET'),Response(201),
            HTTPError('https://private/SYNTHETIC_SECRET',503,'SYNTHETIC_SECRET',{},BytesIO())):
            self.opener.open.reset_mock()
            if isinstance(response,Exception):self.opener.open.side_effect=response
            else:self.opener.open.side_effect=None;self.opener.open.return_value=response
            try:self.gateway.submit(self.row)
            except SchwabError as error:self.assertNotIn('SYNTHETIC_SECRET',''.join(traceback.format_exception(error)))
            else:self.fail('Unconfirmed submission accepted')
            self.opener.open.assert_called_once()

    def test_rate_limit_is_respected_without_automatic_retry(self):
        self.opener.open.side_effect=HTTPError('https://private',429,'x',{'Retry-After':'7'},BytesIO())
        with self.assertRaisesRegex(SchwabError,'RATE_LIMITED') as error:self.gateway.submit(self.row)
        self.assertEqual(error.exception.retry_after_seconds,7);self.opener.open.assert_called_once()
        self.opener.open.side_effect=None;self.opener.open.return_value=self.good_submit()
        self.assertEqual(self.gateway.submit(self.row),'100');self.assertGreaterEqual(self.elapsed,7)

    def test_cancel_200_requires_bound_known_order_and_has_no_payload(self):
        row=dict(self.row,state='CANCEL_SUBMITTING',broker_id='100')
        self.opener.open.return_value=Response(200)
        self.assertTrue(self.gateway.cancel(row))
        req=self.opener.open.call_args.args[0]
        self.assertEqual(req.get_method(),'DELETE');self.assertTrue(req.full_url.endswith('/orders/100'))
        self.assertIsNone(req.data);self.provider.assert_not_called()
        # An original entry quote may expire while its working order still needs cancellation.
        self.now+=timedelta(minutes=5);self.opener.open.return_value=Response(200)
        self.assertTrue(self.gateway.cancel(row))

    def test_unknown_order_id_and_non200_cancel_do_not_become_canceled(self):
        for identity in (None,'-1','0','100/../101','9223372036854775808'):
            with self.assertRaises(SchwabError):self.gateway.cancel(dict(self.row,state='CANCEL_SUBMITTING',broker_id=identity))
        self.opener.open.assert_not_called()
        for status in (201,204,400,401,403,404,500,503,'200',True):
            with self.assertRaises(SchwabError):cancellation_accepted(status)
        with self.assertRaises(SchwabError):cancellation_accepted(200,body=b'{}')

    def test_invalid_token_never_reaches_http_or_leaks_it(self):
        for token in (None,'','SYNTHETIC_SECRET\r\nX:y'):
            self.oauth.access.return_value=token
            with self.assertRaisesRegex(SchwabError,'AUTHORIZATION_UNAVAILABLE') as error:self.gateway.submit(self.row)
            self.assertNotIn('SYNTHETIC_SECRET',str(error.exception))
        self.opener.open.assert_not_called()

    def test_cancel_ack_keeps_reservation_until_confirmed_canceled_with_partial_fill(self):
        h=journal_fixture.RealOrderJournalTests();h.setUp();h.own()
        sell=h.prepare(intent='CLOSE',instruction='SELL_TO_CLOSE')
        h.gateway.submit.return_value='101';sell=h.coordinator.submit(BINDING,sell['id'])
        h.gateway.cancel.side_effect=lambda _:cancellation_accepted(200)
        result=h.coordinator.cancel(BINDING,sell['id'])
        self.assertEqual(result['state'],'PENDING_CANCEL')
        self.assertEqual(h.ledger.available_to_close(BINDING,sell['contract']),0)
        final=journal_fixture.payload(sell,status='CANCELED',filled=1)
        h.ledger.reconcile(BINDING,sell['id'],final)
        self.assertEqual(h.ledger.available_to_close(BINDING,sell['contract']),2)

    def test_actual_journal_coordinator_and_http_transport_never_resend_uncertain_post(self):
        h=journal_fixture.RealOrderJournalTests();h.setUp();h.now=NOW
        row=h.prepare(quantity=2)
        def guard(candidate,action):
            saved=next(r for r in h.ledger.requests(BINDING) if r['id']==candidate['id'])
            return saved['state']==candidate['state'] and saved['updated_at']==candidate['updated_at']
        self.gateway._guard=guard
        self.opener.open.side_effect=TimeoutError('SYNTHETIC_SECRET')
        coordinator=RealOrderCoordinator(h.ledger,self.gateway,lambda *a:True)
        result=coordinator.submit(BINDING,row['id'])
        self.assertEqual(result['state'],'UNCERTAIN')
        with self.assertRaises(RuntimeError):coordinator.submit(BINDING,row['id'])
        self.opener.open.assert_called_once()
        self.assertEqual(h.ledger.available_to_close(BINDING,row['contract']),0)

    def test_documented_http_errors_are_sanitized_and_not_automatic_retries(self):
        codes={400:'ORDER_VALIDATION_REJECTED',401:'REAUTHORIZATION_REQUIRED',403:'ORDER_ACCESS_FORBIDDEN',
            404:'ORDER_RESOURCE_NOT_FOUND',500:'ORDER_DELIVERY_UNCERTAIN',503:'ORDER_DELIVERY_UNCERTAIN'}
        for status,code in codes.items():
            self.opener.open.reset_mock()
            self.opener.open.side_effect=HTTPError('https://private/SYNTHETIC_SECRET',status,
                'SYNTHETIC_SECRET',{},BytesIO(b'SYNTHETIC_SECRET'))
            with self.assertRaisesRegex(SchwabError,code) as error:self.gateway.cancel(dict(self.row,state='CANCEL_SUBMITTING',broker_id='100'))
            self.assertEqual(error.exception.http_status,status)
            self.assertNotIn('SYNTHETIC_SECRET',''.join(traceback.format_exception(error.exception)))
            self.opener.open.assert_called_once()
