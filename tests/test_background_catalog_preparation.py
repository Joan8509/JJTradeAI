"""Isolated metadata preparation; no external requests, messages or live DBs."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Event
from unittest import TestCase
from unittest.mock import patch, Mock
from tests import test_opening_preparation as fixtures
from manual_trade_service import ManualDataError
from schwab_connection import SchwabError, SchwabTransport


class BackgroundCatalogTests(TestCase):
    def test_slow_chain_http_does_not_serialize_quote_http_but_keeps_spacing(self):
        from io import BytesIO
        clock=[0.];starts=[];entered=Event();release=Event()
        def sleep(seconds):clock[0]+=seconds
        def respond(request,timeout):
            starts.append((request.full_url,clock[0]))
            if 'chains' in request.full_url:
                entered.set()
                if not release.wait(3):raise RuntimeError('test deadline')
            return BytesIO(b'{}')
        opener=Mock();opener.open.side_effect=respond
        transport=SchwabTransport(opener=opener,clock=lambda:clock[0],sleeper=sleep)
        with ThreadPoolExecutor(max_workers=2) as pool:
            chain=pool.submit(transport.request,'GET','/marketdata/v1/chains')
            try:
                self.assertTrue(entered.wait(1))
                quote=pool.submit(transport.request,'GET','/marketdata/v1/quotes')
                self.assertEqual(quote.result(timeout=1),{})
                self.assertFalse(chain.done())
                self.assertGreaterEqual(starts[1][1]-starts[0][1],1)
            finally:release.set()
            self.assertEqual(chain.result(timeout=2),{})

    def setUp(self):
        self.fixture=fixtures.OpeningPreparationTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h=self.fixture.h

    def test_during_session_prepares_both_sides_with_spacing_no_order(self):
        h=self.h;h.f.now=self.fixture.opening+timedelta(hours=2)
        prep=h.runner.opening_preparation
        prep.step(h.store.active(),ready=True,continuous=True)
        prep.step(h.store.active(),ready=True,continuous=True)
        self.assertEqual(h.f.client.full_chain.call_count,1)
        h.f.now+=timedelta(seconds=5)
        prep.step(h.store.active(),ready=True,continuous=True)
        self.assertEqual(h.f.client.full_chain.call_count,2)
        self.assertEqual(h.plan()['state'],'ARMED')
        self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),[])

    def test_network_does_not_hold_trading_lock_or_overwrite_newer_data(self):
        h=self.h;entered=Event();release=Event()
        payload=deepcopy(h.f.payload)
        def blocked(*args):
            entered.set()
            if not release.wait(3):raise RuntimeError('test deadline')
            return payload
        h.f.client.full_chain.side_effect=blocked
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(h.f.market.prepare_calendar,'AMZN','CALL',h.f.now)
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(h.f.market.lock.acquire(timeout=.2))
                try:
                    from manual_trade_service import decode_manual_chain
                    newer=decode_manual_chain(payload,'AMZN','CALL',h.f.now+timedelta(seconds=1))
                    h.f.market.cache[('AMZN','CALL')]=newer
                finally:h.f.market.lock.release()
            finally:release.set()
            self.assertIs(future.result(timeout=2),newer)
        self.assertIs(h.f.market.cache[('AMZN','CALL')],newer)

    def test_retry_after_and_unmodified_quote_timestamps(self):
        h=self.h;h.f.market.prepare_calendar('AMZN','CALL',h.f.now)
        market=h.f.market.cache[('AMZN','CALL')]
        stamp=market.chain.contracts[0].snapshot.quote_timestamp
        h.f.now+=timedelta(minutes=4)
        h.f.client.full_chain.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        with self.assertRaises(ManualDataError):h.f.market.prepare_calendar('AMZN','CALL',h.f.now)
        count=h.f.client.full_chain.call_count
        h.f.now+=timedelta(seconds=20)
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_COOLDOWN'):
            h.f.market.prepare_calendar('AMZN','PUT',h.f.now)
        self.assertEqual(h.f.client.full_chain.call_count,count)
        self.assertEqual(h.f.market.cache[('AMZN','CALL')].chain.contracts[0].snapshot.quote_timestamp,stamp)

    def test_closed_session_pending_or_unready_does_not_prepare(self):
        h=self.h;prep=h.runner.opening_preparation
        h.f.now=self.fixture.opening+timedelta(hours=1)
        prep.step(h.store.active(),ready=False,continuous=True)
        with patch.object(h.f.service,'pending_orders',return_value=[{}]):
            prep.step(h.store.active(),ready=True,continuous=True)
        h.f.now=__import__('datetime').datetime.fromisoformat(h.plan()['closes_at'])
        prep.step(h.store.active(),ready=True,continuous=True)
        h.f.client.full_chain.assert_not_called()

    def test_production_queue_does_not_do_synchronous_warmup(self):
        h=self.h;h.runner.background_preparation=True
        with patch.object(h.runner.opening_preparation,'step') as prep:
            h.runner.step()
        prep.assert_not_called()
