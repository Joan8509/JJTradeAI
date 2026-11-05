"""Mock HTTP only, with the separate PreviewOrder input schema."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from urllib.error import HTTPError
import json,traceback

from schwab_connection import SchwabError
from schwab_option_order_request import prepare_option_preview
from schwab_order_preview import preview_request_payload
from schwab_preview_client import SchwabPreviewClient
from tests import test_schwab_order_preview as report_fixture
from tests import test_schwab_option_order_request as draft_fixture
from tests import test_schwab_order_gateway as gateway_fixture

ACCOUNT='111122223333'
HASH='SYNTHETIC_ACCOUNT_HASH'
NOW=draft_fixture.NOW


class PreviewClientTests(TestCase):
    def setUp(self):
        self.now=NOW;self.elapsed=0.;self.opener=Mock();self.oauth=Mock()
        self.oauth.access.return_value='SYNTHETIC_ACCESS'
        self.context=SimpleNamespace(account_number=ACCOUNT,account_hash=HASH,oauth=self.oauth)
        self.draft=prepare_option_preview(replace(draft_fixture.contract(),price_increment=None),
            instruction='BUY_TO_OPEN',quantity=2,now=NOW,valid_until=NOW+timedelta(seconds=10))
        f=report_fixture.OrderPreviewTests();f.setUp();self.raw=deepcopy(f.raw)
        self.raw['orderStrategy']['accountNumber']=ACCOUNT
        self.client=SchwabPreviewClient(self.context,opener=self.opener,utcnow=lambda:self.now,
            clock=lambda:self.elapsed,sleeper=self.sleep)
        self.opener.open.return_value=gateway_fixture.Response(200,json.dumps(self.raw).encode())
    def sleep(self,seconds):self.elapsed+=seconds;self.now+=timedelta(seconds=seconds)

    def test_input_is_order_strategy_not_order_request_or_fake_response(self):
        payload=preview_request_payload(self.draft,account_number=ACCOUNT,as_of=NOW)
        self.assertEqual(set(payload),{'orderStrategy'})
        strategy=payload['orderStrategy'];self.assertEqual(strategy['accountNumber'],ACCOUNT)
        self.assertEqual(strategy['advancedOrderType'],'NONE');self.assertEqual(strategy['price'],1.)
        self.assertNotIn('orderLegCollection',strategy);self.assertNotIn('orderBalance',strategy)
        self.assertNotIn('orderValidationResult',payload);self.assertNotIn('commissionAndFee',payload)
        self.assertEqual(strategy['orderLegs'][0]['assetType'],'OPTION')
        self.assertEqual(strategy['orderLegs'][0]['finalSymbol'],self.draft.contract)

    def test_preview_only_draft_does_not_claim_a_price_increment_or_enable_mutations(self):
        self.assertEqual(self.draft.price_validation,'PREVIEW_ONLY')
        f=gateway_fixture.OrderGatewayTests();f.setUp();f.provider.return_value=self.draft
        with self.assertRaises(SchwabError):f.gateway.submit(f.row)
        f.opener.open.assert_not_called()

    def test_construction_has_no_io_and_preview_endpoint_does_not_create_an_order(self):
        self.oauth.access.assert_not_called();self.opener.open.assert_not_called()
        report=self.client.preview(self.draft)
        req=self.opener.open.call_args.args[0]
        self.assertEqual(req.get_method(),'POST')
        self.assertEqual(req.full_url,'https://api.schwabapi.com/trader/v1/accounts/'+HASH+'/previewOrder')
        self.assertNotIn('/orders',req.full_url)
        self.assertEqual(report['source'],'SCHWAB_PREVIEW_ENDPOINT');self.assertEqual(report['orders_sent'],0)
        self.assertFalse(report['send_authorized']);self.assertFalse(report['real_orders_enabled'])
        self.assertNotIn(ACCOUNT,str(report));self.assertNotIn(HASH,repr(self.client))

    def test_expired_while_refreshing_never_reaches_http(self):
        def refresh(_):self.now+=timedelta(seconds=20);return 'SYNTHETIC_ACCESS'
        self.oauth.access.side_effect=refresh
        with self.assertRaises(SchwabError):self.client.preview(self.draft)
        self.opener.open.assert_not_called()

    def test_foreign_account_rejection_and_unknown_strategy_are_not_accepted(self):
        for change in ({'accountNumber':'OTHER'},{'advancedOrderType':'OCO'},{'quantity':5}):
            raw=deepcopy(self.raw);raw['orderStrategy'].update(change)
            self.opener.open.return_value=gateway_fixture.Response(200,json.dumps(raw).encode())
            with self.assertRaises(SchwabError):self.client.preview(self.draft)

    def test_reject_and_review_reports_are_kept_without_silent_override(self):
        self.raw['orderValidationResult']['rejects']=[dict(originalSeverity='REJECT',overrideSeverity='ACCEPT')]
        self.opener.open.return_value=gateway_fixture.Response(200,json.dumps(self.raw).encode())
        report=self.client.preview(self.draft)
        self.assertEqual(report['state'],'PREVIEW_REQUIRES_REVIEW');self.assertIn('REJECTS_REPORTED',report['blockers'])

    def test_status_body_or_timeout_does_not_retry_or_leak(self):
        for response in (gateway_fixture.Response(201),gateway_fixture.Response(200,b'not JSON'),
            TimeoutError('SYNTHETIC_SECRET'),HTTPError('https://private/SYNTHETIC_SECRET',400,
            'SYNTHETIC_SECRET',{},BytesIO(b'SYNTHETIC_SECRET'))):
            self.opener.open.reset_mock()
            if isinstance(response,Exception):self.opener.open.side_effect=response
            else:self.opener.open.side_effect=None;self.opener.open.return_value=response
            with self.assertRaises(SchwabError) as error:self.client.preview(self.draft)
            self.assertNotIn('SYNTHETIC_SECRET',''.join(traceback.format_exception(error.exception)))
            self.opener.open.assert_called_once()

    def test_rate_limit_backoff_is_not_automatically_retried_or_shortened(self):
        self.opener.open.side_effect=HTTPError('https://private',429,'x',{'Retry-After':'5'},BytesIO())
        with self.assertRaisesRegex(SchwabError,'RATE_LIMITED'):self.client.preview(self.draft)
        self.opener.open.assert_called_once()
        self.opener.open.side_effect=None;self.opener.open.return_value=gateway_fixture.Response(200,json.dumps(self.raw).encode())
        self.client.preview(self.draft);self.assertGreaterEqual(self.elapsed,5)
