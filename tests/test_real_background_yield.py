"""Metadata must not reserve a future request ahead of live prices."""
from datetime import timedelta
from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock
from urllib.error import HTTPError

from schwab_connection import SchwabTransport,SchwabReadOnlyClient,SchwabError
from manual_trade_service import ManualMarketData,ManualDataError
from tests.test_manual_trade_service import NOW,payload_fixture


class BackgroundYieldTests(TestCase):
    def setUp(self):
        self.now=0.;self.sleeps=[]
        def sleep(seconds):self.sleeps.append(seconds);self.now+=seconds
        self.opener=Mock();self.opener.open.side_effect=lambda *a,**k:BytesIO(b'{}')
        self.transport=SchwabTransport(opener=self.opener,clock=lambda:self.now,sleeper=sleep)

    def test_waiting_background_does_not_sleep_or_reserve_a_future_slot(self):
        self.transport.next_request=1.
        with self.assertRaisesRegex(SchwabError,'BACKGROUND_REQUEST_DEFERRED'):
            self.transport.request('GET','/marketdata/v1/chains',background=True)
        self.assertEqual(self.sleeps,[]);self.opener.open.assert_not_called()
        self.assertEqual(self.transport.next_request,1.)
        self.transport.request('GET','/marketdata/v1/quotes')
        self.assertEqual(self.sleeps,[1.])
        self.assertEqual(self.transport.next_request,2.)

    def test_busy_lock_defers_background_immediately_instead_of_joining_waiters(self):
        self.transport.lock.acquire()
        try:
            with self.assertRaisesRegex(SchwabError,'BACKGROUND_REQUEST_DEFERRED'):
                self.transport.request('GET','/marketdata/v1/chains',background=True)
        finally:self.transport.lock.release()
        self.assertEqual(self.sleeps,[]);self.opener.open.assert_not_called()

    def test_available_background_uses_normal_spacing_and_cannot_bypass_retry_after(self):
        self.transport.request('GET','/marketdata/v1/chains',background=True)
        self.assertEqual(self.transport.next_request,1.)
        self.opener.open.side_effect=HTTPError('https://synthetic.invalid',429,'',{'Retry-After':'60'},BytesIO())
        with self.assertRaisesRegex(SchwabError,'RATE_LIMITED'):
            self.transport.request('GET','/marketdata/v1/quotes')
        until=self.transport.next_request
        with self.assertRaisesRegex(SchwabError,'BACKGROUND_REQUEST_DEFERRED'):
            self.transport.request('GET','/marketdata/v1/chains',background=True)
        self.assertEqual(self.transport.next_request,until)
        self.assertEqual(self.opener.open.call_count,2)

    def test_background_flag_only_allowed_for_readonly_chain_metadata(self):
        for method,path in [('POST','/v1/oauth/token'),('GET','/marketdata/v1/quotes'),('GET','/trader/v1/accounts/accountNumbers')]:
            with self.assertRaisesRegex(SchwabError,'RESOURCE_NOT_ALLOWED'):
                self.transport.request(method,path,background=True)
        self.opener.open.assert_not_called()

    def test_client_passes_priority_locally_without_adding_a_provider_query_parameter(self):
        oauth=Mock();oauth.access.return_value='SYNTHETIC_ONLY';client=SchwabReadOnlyClient(oauth)
        client.full_chain('SLV','PUT',NOW,background=True)
        call=oauth.transport.request.call_args
        self.assertIs(call.kwargs['background'],True)
        self.assertNotIn('background',call.kwargs['params'])
        client.full_chain('SLV','PUT',NOW)
        self.assertNotIn('background',oauth.transport.request.call_args.kwargs)

    def test_yield_is_not_a_provider_failure_and_does_not_poison_entry_cache(self):
        client=Mock();client.full_chain.side_effect=SchwabError('BACKGROUND_REQUEST_DEFERRED')
        data=ManualMarketData(client,direct_quotes=True);data.background_yield=True
        with self.assertRaisesRegex(ManualDataError,'BACKGROUND_REQUEST_DEFERRED'):
            data.prepare_calendar('AMZN','CALL',NOW)
        client.full_chain.assert_called_once_with('AMZN','CALL',NOW,background=True)
        self.assertIsNone(data.retry_at);self.assertEqual(data.scoped_retries,{})
        self.assertEqual(data.error_counts,{})
        client.full_chain.side_effect=None;client.full_chain.return_value=payload_fixture()
        data.get_chain('AMZN','CALL',NOW,force=True)
        self.assertNotIn('background',client.full_chain.call_args.kwargs)

    def test_scheduler_does_not_add_fifteen_second_retry_after_yield(self):
        from tests.test_real_entry_preparation import RealEntryPreparationTests
        f=RealEntryPreparationTests();f.setUp()
        f.market.prepare_calendar.side_effect=ManualDataError('BACKGROUND_REQUEST_DEFERRED')
        f.preparation.step()
        self.assertEqual(f.preparation.status()['state'],'YIELDED_TO_LIVE_REQUEST')
        self.assertEqual(f.preparation._retry_after,{})
        f.preparation.step()
        self.assertEqual(f.market.prepare_calendar.call_count,2)
