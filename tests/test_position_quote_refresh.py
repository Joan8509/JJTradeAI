"""Owned-contract refresh, isolated quotes and SQLite; no private API access."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock

from manual_trade_service import ManualMarketData,ManualDataError
from observation_journal import ObservationJournal,observation_error_code
from tests import test_selected_option_quotes as quotes
from tests import test_automatic_entry_queue as queued
from tests.test_manual_trade_service import NOW,payload_fixture,state_fixture


class PositionQuoteRefreshTests(TestCase):
    def fixture(self):
        h=quotes.SelectedQuoteTests();h.setUp()
        client=Mock();client.full_chain.return_value=payload_fixture()
        client.quotes.return_value=h.payload
        data=ManualMarketData(client,direct_quotes=True)
        data.get_chain('AMZN','CALL',NOW)
        return h,client,data

    def test_expired_calendar_does_not_block_owned_quote_or_refresh_entry_calendar(self):
        h,client,data=self.fixture()
        later=NOW+timedelta(minutes=12)
        client.full_chain.side_effect=TimeoutError('private')
        result=data.get_position_chain('AMZN','CALL',h.code,later)
        client.quotes.assert_called_once_with(['AMZN',h.code],later)
        self.assertEqual(client.full_chain.call_count,1)
        self.assertEqual(result.chain.contracts[0].snapshot.quote_timestamp,NOW)
        self.assertEqual(data.cache[('AMZN','CALL')].fetched_at,NOW)
        self.assertFalse(data.catalog_cache);self.assertFalse(data.selected_cache)
        # Buying still requires a current, complete calendar: exit metadata
        # must never bypass or renew the entry-calendar check.
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_UNAVAILABLE'):
            data.get_entry_chain('AMZN','CALL',h.code,later)
        self.assertEqual(client.full_chain.call_count,2)

    def test_owned_quote_rejects_identity_change_and_respects_shared_cooldown(self):
        h,client,data=self.fixture()
        broken=deepcopy(h.payload);broken[h.code]['reference']['strikePrice']=101
        client.quotes.return_value=broken
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_UNAVAILABLE'):
            data.get_position_chain('AMZN','CALL',h.code,NOW)
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_COOLDOWN'):
            data.get_position_chain('AMZN','CALL',h.code,NOW+timedelta(seconds=.5))
        self.assertEqual(client.quotes.call_count,1)

    def test_unknown_contract_does_not_invent_metadata_from_order(self):
        h,client,data=self.fixture();data.cache.clear()
        client.full_chain.side_effect=TimeoutError('private')
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_UNAVAILABLE'):
            data.get_position_chain('AMZN','CALL',h.code,NOW)
        client.quotes.assert_not_called()

    def test_owned_quote_preserves_provider_retry_after_without_private_error_text(self):
        from schwab_connection import SchwabError
        h,client,data=self.fixture()
        client.quotes.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        with self.assertRaisesRegex(ManualDataError,'RATE_LIMITED'):
            data.get_position_chain('AMZN','CALL',h.code,NOW)
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_COOLDOWN'):
            data.get_position_chain('AMZN','CALL',h.code,NOW+timedelta(seconds=59))
        self.assertEqual(client.quotes.call_count,1)

    def test_pending_sale_survives_expired_calendar_but_requires_new_quote(self):
        h=queued.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm(target='10');h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
        h.f.quote(bid=2.23,ask=2.27,seconds=2);h.f.service.observe()
        f=h.f;self.assertEqual(len(f.service.pending_orders()),1)
        f.now=NOW+timedelta(minutes=12);f.state=state_fixture(f.now)
        q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q['quoteTimeInLong']=int(f.now.timestamp()*1000)
        f.client.full_chain.side_effect=TimeoutError('private')
        f.client.full_chain.reset_mock();f.client.quotes.reset_mock()
        f.service.observe()
        self.assertEqual(f.service.positions(),[])
        f.client.full_chain.assert_not_called();f.client.quotes.assert_called_once()
        self.assertEqual(len(f.engine.ledger.orders()),2)

    def test_lookup_diagnostics_only_keep_fixed_error_codes(self):
        import tempfile,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            journal=ObservationJournal(Path(root)/'journal.jsonl')
            for error in (ManualDataError('MARKET_DATA_COOLDOWN'),RuntimeError('PRIVATE_SECRET_URL')):
                journal.record('LOOKUP_FAILED',error_code=observation_error_code(error))
            journal.record('LOOKUP_FAILED',error_code='PRIVATE_SECRET_URL')
            journal.flush();body=journal.path.read_text()
            self.assertNotIn('PRIVATE_SECRET_URL',body)
            rows=[json.loads(s) for s in body.splitlines()]
            self.assertEqual(rows[0]['error_code'],'MARKET_DATA_COOLDOWN')
            self.assertEqual(rows[1]['error_code'],'OBSERVATION_FAILED')
            self.assertNotIn('error_code',rows[2])
