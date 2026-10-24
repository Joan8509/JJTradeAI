"""Official-clock warmup; only isolated queue/ledger and synthetic provider."""
from copy import deepcopy
from datetime import datetime,timedelta
import unittest
from unittest.mock import patch
from tests import test_automatic_entry_queue as fixture
from tests.test_manual_trade_service import state_fixture
from schwab_connection import SchwabError


class OpeningPreparationTests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.opening=datetime.fromisoformat(self.h.f.state['session'][0])
        self.h.f.now=self.opening-timedelta(minutes=3)
        put=deepcopy(self.h.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0])
        put.update(symbol='AMZN  261023P00105000',putCall='PUT',strikePrice=105.)
        self.h.f.payload['putExpDateMap']={'2026-10-23:7':{'105.0':[put]}}
        self.h.arm()

    def test_warms_both_sides_once_with_spacing_and_never_claims_or_buys(self):
        h=self.h;h.runner.step();h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,1)
        h.f.now+=timedelta(seconds=5);h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,2)
        self.assertEqual([call.args[1] for call in h.f.client.full_chain.call_args_list],['CALL','PUT'])
        h.f.now+=timedelta(seconds=5);h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,2)
        self.assertEqual(h.plan()['state'],'ARMED')
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),[])
        self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(len(h.store.read("SELECT id FROM queue_decisions WHERE stage='PREOPEN_CATALOG_READY'")),2)

    def test_never_warms_at_cutoff_open_morning_afternoon_or_too_early(self):
        h=self.h
        for offset in (-301,-241,-120,-1,0,30,3600,18000):
            h.f.now=self.opening+timedelta(seconds=offset)
            with patch.object(h.runner,'_signal',side_effect=__import__('manual_trade_service').ManualDataError('NO_CURRENT_SIGNAL')):
                h.runner.step()
        h.f.client.full_chain.assert_not_called()

    def test_requires_armed_plan_and_ready_monitor_and_direct_quotes(self):
        h=self.h;h.ready=False;h.runner.step();h.ready=True
        h.f.market.direct_quotes=False;h.runner.step();h.f.market.direct_quotes=True
        h.store.pause();h.runner.step()
        h.f.client.full_chain.assert_not_called()

    def test_exposure_or_pending_order_suppresses_nonessential_queries(self):
        h=self.h
        with patch.object(h.f.service,'pending_orders',return_value=[{}]):h.runner.step()
        with patch.object(h.f.service,'positions',return_value=[{}]):h.runner.step()
        h.f.client.full_chain.assert_not_called()

    def test_clock_rechecked_after_exposure_read(self):
        h=self.h
        def slow():h.f.now=self.opening-timedelta(seconds=119);return []
        with patch.object(h.f.service,'positions',side_effect=slow):h.runner.step()
        h.f.client.full_chain.assert_not_called()

    def test_provider_backoff_and_sanitized_error_preserve_authorization(self):
        h=self.h
        h.f.client.full_chain.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        h.runner.step();h.f.now+=timedelta(seconds=6);h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,1)
        self.assertEqual(h.plan()['state'],'ARMED')
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),[])
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_warmed_calendar_still_needs_live_regular_quotes_and_signal(self):
        h=self.h;h.runner.step()
        cached=dict(h.f.market.cache)
        h.f.now=self.opening
        h.f.state=state_fixture(self.opening)
        q=h.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q['quoteTimeInLong']=int(self.opening.timestamp()*1000)
        h.f.payload['underlying']['quoteTime']=int(self.opening.timestamp()*1000)
        h.f.market.cache.update(cached)
        h.f.client.chain.side_effect=lambda *args:deepcopy(h.f.payload)
        h.runner.step()
        self.assertEqual(h.f.client.full_chain.call_count,1)  # None added on EXIT.
        h.f.client.chain.assert_called_once()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertEqual(h.f.engine.ledger.orders()[0]['filled_quantity'],0)

    def test_session_shift_uses_plan_open_instead_of_hardcoded_wall_time(self):
        h=self.h
        # Move the official fixture schedule one hour, keeping the same lead.
        shifted=self.opening+timedelta(hours=1)
        with h.store.transaction() as db:
            db.execute('UPDATE queue_plans SET opens_at=?',(shifted.isoformat(),))
        h.runner.step();h.f.client.full_chain.assert_not_called()
        h.f.now=shifted-timedelta(minutes=3);h.runner.step()
        h.f.client.full_chain.assert_called_once()


if __name__=='__main__':unittest.main()
