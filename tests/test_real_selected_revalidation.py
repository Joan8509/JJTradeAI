"""Final admission must stay equivalent when unrelated quotes are omitted."""
from dataclasses import replace
from datetime import timedelta
from unittest import TestCase
from unittest.mock import patch

from manual_trade_service import manual_candidates, ManualDataError
from tests import test_real_trade_preparation as preparation


class SelectedRevalidationTests(TestCase):
    def setUp(self):
        self.f=preparation.RealPreparationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.now=self.f.h.f.now
        self.market=self.f.h.f.market.get_catalog_chain('AMZN','CALL',self.now)
        _,_,self.eligible=self.read()
        self.selected=self.eligible[0].snapshot.symbol

    def read(self,**kwargs):
        return manual_candidates(self.f.state,self.market,'AMZN','CALL',self.now,**kwargs)

    def test_same_result_for_each_contract_without_revalidating_other_quotes(self):
        import manual_trade_service
        original=manual_trade_service.entry_candidates
        for contract in self.market.chain.contracts:
            key=contract.snapshot.symbol
            with patch('manual_trade_service.entry_candidates',wraps=original) as observed:
                _,_,actual=self.read(contract_symbol=key)
            self.assertEqual(actual,tuple(c for c in self.eligible if c.snapshot.symbol==key))
            self.assertEqual(len(observed.call_args.args[0]),1)
            self.assertEqual(observed.call_args.kwargs['strike_inventory'],self.market.strike_inventory)
            self.assertEqual(observed.call_args.kwargs['listed_expirations'],self.market.expirations)

    def test_complete_inventory_still_excludes_sixth_otm_without_quotes_for_first_five(self):
        base=self.eligible[0];expiry=base.snapshot.expiration
        def contract(strike):
            return replace(base,snapshot=replace(base.snapshot,strike=float(strike),
                symbol=base.snapshot.symbol[:-8]+f'{strike*1000:08d}'))
        near,far=contract(105),contract(110)
        self.market=replace(self.market,chain=replace(self.market.chain,contracts=(near,far)),
            strike_inventory=tuple((expiry,strike) for strike in range(105,111)))
        self.assertEqual(self.read(contract_symbol=near.snapshot.symbol)[2],(near,))
        self.assertEqual(self.read(contract_symbol=far.snapshot.symbol)[2],())

    def test_changed_quote_and_retracted_signal_are_not_replaced_by_earlier_success(self):
        self.assertTrue(self.read(contract_symbol=self.selected)[2])
        selected=next(c for c in self.market.chain.contracts if c.snapshot.symbol==self.selected)
        stale=replace(selected,snapshot=replace(selected.snapshot,quote_timestamp=self.now-timedelta(seconds=31)))
        self.market=replace(self.market,chain=replace(self.market.chain,contracts=(stale,)))
        self.assertEqual(self.read(contract_symbol=self.selected)[2],())
        self.f.state['tick']['signal']=None
        with self.assertRaises(ManualDataError):self.read(contract_symbol=self.selected)

    def test_missing_selected_contract_does_not_substitute_another_candidate(self):
        self.assertEqual(self.read(contract_symbol='MISSING')[2],())
        self.assertTrue(self.read()[2])

    def test_stale_chain_and_changed_side_still_block(self):
        with self.assertRaises(ManualDataError):
            manual_candidates(self.f.state,self.market,'AMZN','PUT',self.now,contract_symbol=self.selected)
        self.market=replace(self.market,fetched_at=self.now-timedelta(seconds=31))
        with self.assertRaisesRegex(ManualDataError,'OPTION_CHAIN_NOT_CURRENT'):
            self.read(contract_symbol=self.selected)
