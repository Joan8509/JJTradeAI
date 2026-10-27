"""Exit priority and post-order quote evidence; isolated simulator only."""
from datetime import timedelta
from pathlib import Path
import tempfile,json
from unittest import TestCase
from unittest.mock import Mock
from tests import test_automatic_entry_queue as fixtures
from observation_journal import ObservationJournal


class ExitLatencyTests(TestCase):
    def harness(self):
        h=fixtures.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm(target='10');h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
        h.f.quote(bid=2.23,ask=2.27,seconds=2);h.f.service.observe()
        self.assertEqual(len(h.f.service.pending_orders()),1)
        self.assertEqual(h.f.service.pending_orders()[0]['order']['instruction'],'SELL_TO_CLOSE')
        return h

    def test_pending_sale_bypasses_subsecond_pre_order_cache_without_duplicate_gets(self):
        h=self.harness();f=h.f
        # Previously force=False reused this pre-order cached quote for 1s.
        f.now+=timedelta(milliseconds=200)
        q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q['quoteTimeInLong']=int((f.now-timedelta(milliseconds=100)).timestamp()*1000)
        f.client.quotes.reset_mock();f.client.full_chain.reset_mock()
        journal=Mock();f.service.observation_journal=journal
        f.service.observe()
        f.client.quotes.assert_called_once();f.client.full_chain.assert_not_called()
        self.assertEqual(f.service.positions(),[])
        self.assertEqual(len(f.engine.ledger.orders()),2)
        self.assertIn('MATCH_APPLIED',[c.args[0] for c in journal.record.call_args_list])

    def test_fresh_bid_below_existing_limit_does_not_invent_a_sale(self):
        h=self.harness();f=h.f
        f.now+=timedelta(milliseconds=200)
        q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q.update(bid=2.20,ask=2.25,quoteTimeInLong=int((f.now-timedelta(milliseconds=100)).timestamp()*1000))
        journal=Mock();f.service.observation_journal=journal
        f.service.observe()
        self.assertEqual(f.service.positions()[0]['quantity'],2)
        self.assertIn('BID_BELOW_LIMIT',[c.args[0] for c in journal.record.call_args_list])
        self.assertEqual(f.service.pending_orders()[0]['order']['limit'],'2.23')

    def test_diagnostics_exception_never_prevents_sale(self):
        h=self.harness();f=h.f
        f.now+=timedelta(milliseconds=200)
        q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q['quoteTimeInLong']=int((f.now-timedelta(milliseconds=100)).timestamp()*1000)
        f.service.observation_journal=Mock();f.service.observation_journal.record.side_effect=OSError('private')
        f.service.observe();self.assertEqual(f.service.positions(),[])

    def test_journal_is_bounded_rotates_and_rejects_unapproved_fields(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'exit.jsonl';j=ObservationJournal(p,capacity=2,max_bytes=1)
            for _ in range(3):j.record('LOOKUP_STARTED',secret='PRIVATE_DETAIL',reason='PRIVATE_DETAIL',limit='2.07')
            self.assertFalse(p.exists());self.assertEqual(j.dropped,1)
            j.flush();self.assertEqual(len(p.read_text().splitlines()),2)
            self.assertNotIn('PRIVATE_DETAIL',p.read_text())
            j.record('MATCH_APPLIED',filled=1);j.flush()
            self.assertTrue(p.with_suffix('.previous.jsonl').is_file())
            self.assertEqual(json.loads(p.read_text())['filled'],'1')
