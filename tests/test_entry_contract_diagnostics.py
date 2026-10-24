"""Observed prices explain rejection without becoming purchase candidates."""
from dataclasses import replace
from datetime import timedelta
import unittest

from entry_contract_diagnostics import contract_diagnostics
from manual_trade_service import ManualChain
from option_contract_selection import entry_candidates
from schwab_contracts import SchwabChain
from tests.test_schwab_simulation import NOW, synthetic_contract


class ContractDiagnosticsTests(unittest.TestCase):
    def diagnose(self, contracts, *, side='CALL', underlying=104., stamp=NOW):
        expiry=synthetic_contract().snapshot.expiration
        market=ManualChain('AMZN',side,(expiry,),SchwabChain(underlying,stamp,tuple(contracts),0),NOW)
        candidates=entry_candidates([c.snapshot for c in contracts],symbol='AMZN',side=side,
            underlying_price=underlying,underlying_stamp=stamp,as_of=NOW,listed_expirations=market.expirations)
        allowed={q.symbol for q in candidates}
        eligible=tuple(c for c in contracts if c.snapshot.symbol in allowed)
        result=contract_diagnostics(market,symbol='AMZN',side=side,expiration=expiry,as_of=NOW,
            underlying_price=underlying,underlying_stamp=stamp,optimal_range=('1.40','2.30'),eligible=eligible)
        self.assertEqual(result['counts']['eligible'],len(candidates))
        return result

    def test_cheap_otm_and_expensive_wide_itm_remain_non_actionable(self):
        contracts=(synthetic_contract(strike=103.,bid=2.81,ask=2.88),
            synthetic_contract(strike=105.,bid=1.57,ask=1.62))
        result=self.diagnose(contracts)
        self.assertTrue(result['read_only']);self.assertEqual(result['counts']['eligible'],0)
        itm,otm=result['observed']
        self.assertEqual(itm['reasons'],['ASK_OUTSIDE_RANGE'])
        self.assertEqual(otm['reasons'],['OUTSIDE_ALLOWED_MONEYNESS']);self.assertFalse(otm['eligible'])
        self.assertEqual([r['strike'] for r in result['itm_contracts']],['103.0'])
        self.assertFalse(result['itm_contracts'][0]['eligible'])
        self.assertEqual(result['itm_contracts'][0]['ask_size'],10)

    def test_exact_eight_cent_boundary_and_range_are_inclusive(self):
        for bid,ask in ((1.32,1.40),(2.22,2.30)):
            with self.subTest(ask=ask):
                result=self.diagnose((synthetic_contract(bid=bid,ask=ask),))
                self.assertEqual(result['counts']['eligible'],1)
                self.assertEqual(result['observed'][0]['reasons'],[])
                self.assertEqual(result['observed'][0]['spread'],'0.08')

    def test_stale_future_and_unknown_quotes_are_reported_not_admitted(self):
        for stamp in (NOW-timedelta(seconds=31),NOW+timedelta(microseconds=1),None):
            with self.subTest(stamp=stamp):
                q=synthetic_contract(quote_timestamp=stamp)
                result=self.diagnose((q,))
                self.assertEqual(result['counts']['eligible'],0)
                self.assertIn('QUOTE_NOT_CURRENT',result['observed'][0]['reasons'])

    def test_wrong_side_symbol_and_expiration_are_not_comparisons(self):
        q=synthetic_contract(); wrong=replace(q,snapshot=replace(q.snapshot,expiration=q.snapshot.expiration+timedelta(days=7)))
        other=replace(q,snapshot=replace(q.snapshot,underlying_symbol='AVGO'))
        result=self.diagnose((q,wrong,other,synthetic_contract(side='PUT')))
        self.assertEqual(result['counts']['observed'],1)
        self.assertEqual(result['counts']['eligible'],1)

    def test_put_itm_and_underlying_freshness_match_canonical_selection(self):
        q=synthetic_contract(side='PUT',strike=105.)
        current=self.diagnose((q,),side='PUT')
        self.assertTrue(current['observed'][0]['itm']);self.assertEqual(current['counts']['eligible'],1)
        stale=self.diagnose((q,),side='PUT',stamp=NOW-timedelta(seconds=31))
        self.assertEqual(stale['counts']['eligible'],0)
        self.assertIn('UNDERLYING_NOT_CURRENT',stale['observed'][0]['reasons'])


if __name__=='__main__':unittest.main()
