"""Real isolated queue/engine with synthetic clocks; never market requests."""
from datetime import timedelta
import json
import time
import unittest
from unittest.mock import Mock,patch
from tests import test_automatic_entry_queue as fixtures
from schwab_connection import SchwabError
from tests import test_telegram_manual_runtime as runtime_fixture


class AutomaticLatencyTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_subsecond_catalog_saves_second_request_and_keeps_claim_and_timing(self):
        h=self.h;h.arm();h.runner.step();h.runner.step()
        h.f.client.full_chain.assert_called_once();h.f.client.quotes.assert_not_called()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertEqual(len(h.store.read('SELECT * FROM queue_attempts')),1)
        rows=h.store.read("SELECT details_json FROM queue_decisions WHERE stage='ENTRY_REFRESH_RESULT'")
        self.assertTrue(json.loads(rows[0]['details_json'])['catalog_reused'])
        timing=json.loads(h.store.read("SELECT details_json FROM queue_decisions WHERE stage='ORDER_REGISTERED'")[0]['details_json'])
        self.assertGreaterEqual(timing['processing_ms'],0)
        self.assertEqual(timing['source_to_order_ms'],0)
        # Cannot fabricate a fill from the pre-order quote.
        self.assertEqual(h.f.engine.ledger.orders()[0]['status'],'WORKING')

    def test_quote_or_spot_at_one_second_or_older_forces_refresh(self):
        for field in ('spot','option'):
            h=fixtures.AutomaticQueueTests();h.setUp()
            try:
                stamp=int((h.f.now-timedelta(seconds=1)).timestamp()*1000)
                if field=='spot':h.f.payload['underlying']['quoteTime']=stamp
                else:h.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['quoteTimeInLong']=stamp
                h.arm();h.runner.step()
                h.f.client.quotes.assert_called_once()
                self.assertEqual(h.plan()['state'],'SUBMITTED')
            finally:h.doCleanups()

    def test_explicit_manual_force_still_fetches_when_catalog_is_fresh(self):
        h=self.h;market=h.f.market.get_catalog_chain('AMZN','CALL',h.f.now)
        code=market.chain.contracts[0].snapshot.symbol
        h.f.market.get_entry_chain('AMZN','CALL',code,h.f.now,force=True)
        h.f.client.quotes.assert_called_once()

    def test_catalog_age_boundary_requires_fresh_get(self):
        h=self.h;market=h.f.market.get_catalog_chain('AMZN','CALL',h.f.now)
        code=market.chain.contracts[0].snapshot.symbol
        later=h.f.now+timedelta(seconds=1)
        h.f.market.get_entry_chain('AMZN','CALL',code,later,force=False)
        h.f.client.quotes.assert_called_once()

    def test_waiting_for_market_lock_counts_toward_subsecond_age(self):
        h=self.h;market=h.f.market.get_catalog_chain('AMZN','CALL',h.f.now)
        code=market.chain.contracts[0].snapshot.symbol
        class DelayedLock:
            def __enter__(self):time.sleep(.03)
            def __exit__(self,*args):return False
        h.f.market.lock=DelayedLock()
        h.f.market.get_entry_chain('AMZN','CALL',code,h.f.now+timedelta(seconds=.99),force=False)
        h.f.client.quotes.assert_called_once()

    def test_new_trade_recovers_before_old_five_second_cooldown(self):
        h=self.h;h.arm();lookup=h.f.market.get_catalog_chain
        def slow(*args):
            result=lookup(*args);h.f.now+=timedelta(seconds=4)
            h.f.state['runtime']['heartbeat']=h.f.now.isoformat()
            return result
        with patch.object(h.f.market,'get_catalog_chain',side_effect=slow):h.runner.step()
        self.assertEqual(h.plan()['reason'],'TRADE_NOT_CURRENT')
        self.assertEqual(h.f.engine.ledger.orders(),[])
        # A NEW valid source at4.3s; old fixed5s gate would skip this chance.
        saved_catalog=dict(h.f.market.cache)
        h.f.quote(seconds=4)  # Fixture invalidates caches; restore real-life catalog.
        h.f.market.cache.update(saved_catalog)
        h.f.now+=timedelta(seconds=.3);h.runner.step()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(h.f.client.full_chain.call_count,1)
        h.f.client.quotes.assert_called_once()

    def test_rate_limit_backoff_survives_faster_polling(self):
        h=self.h;h.arm()
        h.f.client.full_chain.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        h.runner.step()
        for seconds in (1,6,15,59):
            h.f.quote(seconds=seconds);h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,1)
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_entry_poll_is_200ms_and_independent_of_telegram(self):
        fixture=runtime_fixture.TelegramRuntimeTests();companion=fixture.companion()
        companion.entry_queue=Mock()
        def stop(*args):companion.stop.set()
        with patch.object(companion.stop,'wait',side_effect=stop) as wait:
            companion._entries()
        wait.assert_called_once_with(.2)
        companion.api.assert_not_called()


if __name__=='__main__':unittest.main()
