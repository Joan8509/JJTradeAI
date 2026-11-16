"""Processing equivalence and scheduling gates, all synthetic/no network."""
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock

from schwab_connection import SchwabTransport
from schwab_connection import SchwabError
from tests import test_real_entry_quote_batch as batch_fixtures
from tests import test_schwab_preview_client as preview_fixtures
from tests import test_schwab_order_gateway as gateway_fixtures


class EntryProcessingCostTests(TestCase):
    def test_batch_result_excludes_unrequested_expiries_and_keeps_complete_inventory(self):
        f=batch_fixtures.RealEntryQuoteBatchTests();f.setUp()
        first=f.full.chain.contracts[0]
        extras=tuple(replace(first,snapshot=replace(first.snapshot,
            expiration=first.snapshot.expiration+timedelta(days=i+1),
            symbol='AMZN  '+(first.snapshot.expiration+timedelta(days=i+1)).strftime('%y%m%d')+'C00100000')) for i in range(1000))
        complete=replace(f.full,chain=replace(f.full.chain,contracts=(*extras,first)))
        f.data.cache[('AMZN','CALL')]=complete
        result=f.data.get_catalog_chain('AMZN','CALL',f.at)
        self.assertEqual([c.snapshot.symbol for c in result.chain.contracts],[f.code])
        self.assertEqual(result.chain.contracts[0].snapshot.ask,2.01)
        self.assertEqual(result.chain.contracts[0].snapshot.quote_timestamp,first.snapshot.quote_timestamp)
        self.assertEqual(result.expirations,complete.expirations)
        self.assertEqual(result.strike_inventory,complete.strike_inventory)
        self.assertIs(f.data.cache[('AMZN','CALL')],complete)
        f.client.quotes.assert_called_once_with(['AMZN',f.code],f.at)

    def test_read_get_skips_zero_sleep_but_preserves_next_request_wait(self):
        elapsed=[0.];sleep=Mock(side_effect=lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds))
        opener=Mock();opener.open.side_effect=lambda *a,**k:BytesIO(b'{}')
        transport=SchwabTransport(opener=opener,clock=lambda:elapsed[0],sleeper=sleep)
        transport.request('GET','/marketdata/v1/quotes');sleep.assert_not_called()
        transport.request('GET','/marketdata/v1/quotes');sleep.assert_called_once_with(1.)

    def test_preview_skips_zero_sleep_and_preserves_positive_wait(self):
        f=preview_fixtures.PreviewClientTests();f.setUp();sleep=Mock(side_effect=f.sleep);f.client._sleep=sleep
        # _prepare validation/HTTP response still run normally, only sleep(0) removed.
        f.client.preview(f.draft);sleep.assert_not_called()
        f.opener.open.return_value=f.opener.open.return_value.__class__(200,b'{}')
        with self.assertRaises(SchwabError):f.client.preview(f.draft)
        sleep.assert_called_once_with(1.)

    def test_order_skips_zero_sleep_but_preserves_validation_spacing_and_no_resend(self):
        f=gateway_fixtures.OrderGatewayTests();f.setUp();sleep=Mock(side_effect=f.sleep);f.gateway._sleep=sleep
        f.opener.open.return_value=f.good_submit()
        self.assertEqual(f.gateway.submit(f.row),'100');sleep.assert_not_called()
        self.assertEqual(f.guard.call_count,2)
        f.opener.open.side_effect=TimeoutError()
        with self.assertRaisesRegex(SchwabError,'ORDER_DELIVERY_UNCERTAIN'):f.gateway.submit(f.row)
        sleep.assert_called_once_with(1.)
        self.assertEqual(f.opener.open.call_count,2)  # One HTTP per explicit call, no retry.
