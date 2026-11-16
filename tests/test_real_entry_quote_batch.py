"""Synthetic complete-calendar fast path; no account, network or orders."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock

from manual_trade_service import ManualMarketData, ManualDataError, manual_candidates
from tests.test_manual_trade_service import NOW, payload_fixture, state_fixture
from tests.test_selected_option_quotes import SelectedQuoteTests


class RealEntryQuoteBatchTests(TestCase):
    def setUp(self):
        SelectedQuoteTests.setUp(self)
        self.client=Mock()
        self.client.full_chain.return_value=payload_fixture()
        self.client.chain.return_value=payload_fixture()
        self.client.quotes.return_value=self.payload
        self.data=ManualMarketData(self.client,direct_quotes=True,entry_quote_batches=True)
        self.full=self.data.get_chain('AMZN','CALL',NOW)
        self.at=NOW+timedelta(seconds=8)

    def test_one_quote_batch_replaces_chain_get_without_mutating_metadata(self):
        result=self.data.get_catalog_chain('AMZN','CALL',self.at)
        self.client.quotes.assert_called_once_with(['AMZN',self.code],self.at)
        self.client.chain.assert_not_called()
        self.assertEqual(self.client.full_chain.call_count,1)
        self.assertIs(self.data.cache[('AMZN','CALL')],self.full)
        self.assertEqual(result.expirations,self.full.expirations)
        self.assertEqual(result.strike_inventory,self.full.strike_inventory)
        self.assertEqual(result.chain.contracts[0].snapshot.ask,2.01)
        self.assertEqual(result.chain.contracts[0].snapshot.quote_timestamp,NOW)
        self.assertIs(self.data.get_catalog_chain('AMZN','CALL',self.at+timedelta(seconds=1)),result)
        self.assertEqual(self.client.quotes.call_count,1)

    def test_stale_prices_remain_ineligible_and_are_never_restamped(self):
        self.at=NOW+timedelta(seconds=40)
        result=self.data.get_catalog_chain('AMZN','CALL',self.at)
        self.assertEqual(manual_candidates(state_fixture(self.at),result,'AMZN','CALL',self.at)[2],())

    def test_all_invalid_quotes_block_instead_of_returning_old_chain(self):
        self.payload[self.code]['realtime']=False
        with self.assertRaises(ManualDataError):self.data.get_catalog_chain('AMZN','CALL',self.at)
        self.assertFalse(self.data.catalog_cache)
        self.client.chain.assert_not_called()

    def test_one_invalid_contract_does_not_hide_a_valid_contract_or_return_old_quote(self):
        first=self.full.chain.contracts[0]
        bad=replace(first,snapshot=replace(first.snapshot,symbol='AMZN  261023C00101000',strike=101.))
        self.data.cache[('AMZN','CALL')]=replace(self.full,chain=replace(self.full.chain,contracts=(first,bad)))
        result=self.data.get_catalog_chain('AMZN','CALL',self.at)
        self.assertEqual([c.snapshot.symbol for c in result.chain.contracts],[self.code])
        self.assertEqual(len(self.client.quotes.call_args.args[0]),3)

    def test_large_expiry_uses_existing_chain_without_truncating_strikes(self):
        c=self.full.chain.contracts[0]
        contracts=tuple(replace(c,snapshot=replace(c.snapshot,strike=100.+i,
            symbol=f'AMZN  261023C{(100+i)*1000:08}')) for i in range(50))
        self.data.cache[('AMZN','CALL')]=replace(self.full,chain=replace(self.full.chain,contracts=contracts))
        self.data.get_catalog_chain('AMZN','CALL',self.at)
        self.client.chain.assert_called_once()
        self.client.quotes.assert_not_called()

    def test_expired_metadata_requires_full_calendar_and_no_quote_shortcut(self):
        self.data.get_catalog_chain('AMZN','CALL',NOW+timedelta(seconds=301))
        self.assertEqual(self.client.full_chain.call_count,2)
        self.client.quotes.assert_not_called()

    def test_default_simulation_path_unchanged(self):
        self.data.entry_quote_batches=False
        self.data.get_catalog_chain('AMZN','CALL',self.at)
        self.client.chain.assert_called_once()
        self.client.quotes.assert_not_called()

    def test_failure_retains_cooldown_without_second_http_or_stale_fallback(self):
        self.client.quotes.side_effect=TimeoutError()
        with self.assertRaises(ManualDataError):self.data.get_catalog_chain('AMZN','CALL',self.at)
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_COOLDOWN'):
            self.data.get_catalog_chain('AMZN','CALL',self.at+timedelta(seconds=1))
        self.client.quotes.assert_called_once()
        self.client.chain.assert_not_called()
