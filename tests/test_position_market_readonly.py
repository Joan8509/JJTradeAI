"""No submissions, SQLite changes or entry signal dependence when viewing marks."""
import hashlib
import unittest
from unittest.mock import patch
from tests import test_manual_execution as fixtures


class PositionMarketReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ManualExecutionTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.filled()

    def test_quote_and_costs_read_without_writes_or_dispatch(self):
        f=self.fixture;paths=[f.root/name for name in ('ledger.db','broker.db','reviews.db')]
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        with patch.object(f.engine,'enter',side_effect=AssertionError('No entries')), \
             patch.object(f.engine,'manage_exit',side_effect=AssertionError('No exits')), \
             patch.object(f.engine.broker,'match_quote',side_effect=AssertionError('No fill')):
            market=f.service.position_market(f.code);position=f.service.positions()[0]
        self.assertTrue(market['session_open']);self.assertEqual(position['entry_fees'],'1.95')
        self.assertEqual(position['exit_fee_per_contract'],'0.65')
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})

    def test_retracted_or_closed_signal_and_missing_tick_still_allow_reference_view(self):
        f=self.fixture;f.state['tick']['signal']=None;f.state['session']=None
        f.market.increments={};f.market.cache.clear()
        market=f.service.position_market(f.code)
        self.assertFalse(market['session_open'])
        self.assertEqual(market['snapshot'].symbol,f.code)
        self.assertEqual(len(f.engine.broker.snapshot()),1)


if __name__=='__main__':unittest.main()
