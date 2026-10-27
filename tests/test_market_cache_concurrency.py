"""Concurrent provider fixtures only: no private profile, APIs, or orders."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest import TestCase
from unittest.mock import Mock
from manual_trade_service import ManualMarketData,decode_manual_chain,ManualDataError
from schwab_connection import SchwabError
from tests import test_selected_option_quotes as fixtures


class MarketCacheConcurrencyTests(TestCase):
    def test_ready_automatic_entry_dispatches_while_other_quote_http_waits(self):
        from tests import test_automatic_entry_queue as queue_fixtures
        h=queue_fixtures.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm();h.f.market.get_chain('AMZN','CALL',h.f.now)
        entered=Event();release=Event();original=h.f.client.quotes.side_effect
        def delayed(*args):
            entered.set()
            if not release.wait(3):raise RuntimeError('TEST_TIMEOUT')
            return original(*args)
        h.f.client.quotes.side_effect=delayed
        with ThreadPoolExecutor(max_workers=2) as pool:
            quote=pool.submit(h.f.market.get_entry_chain,'AMZN','CALL',h.f.code,h.f.now)
            try:
                self.assertTrue(entered.wait(1))
                dispatch=pool.submit(h.runner.step)
                self.assertTrue(dispatch.result(timeout=1))
                self.assertEqual(h.plan()['state'],'SUBMITTED')
                self.assertEqual(len(h.f.engine.ledger.orders()),1)
                self.assertFalse(quote.done())
            finally:release.set()
            quote.result(timeout=2)
        # The durable queue remains consumed; another iteration cannot buy again.
        h.runner.step();self.assertEqual(len(h.f.engine.ledger.orders()),1)

    def test_slow_foreground_http_never_locks_cache_or_overwrites_newer_response(self):
        for mode in ('full','catalog','selected'):
            with self.subTest(mode=mode):
                f=fixtures.SelectedQuoteTests();f.setUp()
                now=fixtures.NOW;raw=fixtures.payload_fixture()
                client=Mock();data=ManualMarketData(client,direct_quotes=True)
                data.cache[('AMZN','CALL')]=f.market
                entered=Event();release=Event()
                def delayed(*args):
                    entered.set()
                    if not release.wait(3):raise RuntimeError('TEST_TIMEOUT')
                    return f.payload if mode=='selected' else raw
                method={'full':client.full_chain,'catalog':client.chain,'selected':client.quotes}[mode]
                method.side_effect=delayed
                def request():
                    if mode=='full':return data.get_chain('AMZN','CALL',now+timedelta(seconds=6),force=True)
                    if mode=='catalog':return data.get_catalog_chain('AMZN','CALL',now+timedelta(seconds=6))
                    return data.get_entry_chain('AMZN','CALL',f.code,now+timedelta(seconds=6))
                with ThreadPoolExecutor(max_workers=2) as pool:
                    future=pool.submit(request)
                    try:
                        self.assertTrue(entered.wait(1))
                        newer=decode_manual_chain(raw,'AMZN','CALL',now+timedelta(seconds=7))
                        acquired=data.lock.acquire(timeout=.2)
                        self.assertTrue(acquired,'Provider HTTP retained the shared cache lock')
                        try:
                            data.cache[('AMZN','CALL')]=newer
                            data.catalog_cache[('AMZN','CALL',newer.expirations[0])]=newer
                            data.selected_cache[('AMZN','CALL',f.code)]=newer
                        finally:data.lock.release()
                        # A new ready catalog is usable while the older HTTP is
                        # still in flight; this read must not issue another GET.
                        fast=pool.submit(data.get_catalog_chain,'AMZN','CALL',now+timedelta(seconds=7))
                        self.assertIs(fast.result(timeout=1),newer)
                    finally:release.set()
                    result=future.result(timeout=2)
                self.assertIs(data.cache[('AMZN','CALL')],newer)
                self.assertIs(data.catalog_cache[('AMZN','CALL',newer.expirations[0])],newer)
                self.assertIs(data.selected_cache[('AMZN','CALL',f.code)],newer)
                self.assertEqual(method.call_count,1)
                # Real provider timestamps are never advanced to request time.
                self.assertEqual(result.chain.contracts[0].snapshot.quote_timestamp,now)

    def test_out_of_order_failure_cannot_shorten_provider_retry_after(self):
        now=fixtures.NOW;data=ManualMarketData(Mock(),direct_quotes=True)
        data._record_retry(now,SchwabError('RATE_LIMITED',retry_after_seconds=60))
        data._record_retry(now,TimeoutError())
        self.assertEqual(data.retry_at,now+timedelta(seconds=60))
        for lookup in (lambda:data.get_chain('AMZN','CALL',now),
                       lambda:data.get_catalog_chain('AMZN','CALL',now)):
            with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_COOLDOWN'):lookup()
        data.client.full_chain.assert_not_called();data.client.chain.assert_not_called()
