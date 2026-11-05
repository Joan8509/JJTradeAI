"""Pre-opening preparation and critical-path requests, without production I/O."""
from copy import deepcopy
from datetime import timedelta
from threading import Event
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch

from real_entry_preparation import RealEntryPreparation
from real_execution_runtime import RealExecutionWorker
from manual_trade_service import ManualMarketData,manual_candidates
from tests.test_manual_trade_service import NOW,payload_fixture,state_fixture


class RealEntryPreparationTests(TestCase):
    def setUp(self):
        self.now=NOW-timedelta(seconds=60)
        self.plan=dict(paused=False,session_open=NOW.isoformat(),entry_owner=None,entry_consumed=False,
            rows=[dict(symbol='AMZN',state='ARMED'),dict(symbol='AAPL',state='ARMED')])
        self.queue=Mock();self.queue.read.side_effect=lambda binding:deepcopy(self.plan)
        self.market=Mock()
        self.preparation=RealEntryPreparation(self.queue,'a'*64,self.market,clock=lambda:self.now)

    def test_only_armed_selected_companies_and_one_side_per_turn(self):
        self.market.prepare_calendar.assert_not_called()
        self.preparation.step();self.preparation.step();self.preparation.step()
        self.assertEqual([c.args[:2] for c in self.market.prepare_calendar.call_args_list],
            [('AMZN','CALL'),('AMZN','PUT'),('AAPL','CALL')])
        self.market.get_catalog_chain.assert_not_called()
        self.assertEqual(self.preparation.status()['prepared'],3)

    def test_no_background_requests_outside_window_or_with_reserved_radar(self):
        for changes in (dict(paused=True),dict(entry_owner='OWNER'),dict(entry_consumed=True),dict(rows=[])):
            old=deepcopy(self.plan);self.plan.update(changes);self.preparation.step();self.plan=old
        for stamp in (NOW-timedelta(minutes=6),NOW-timedelta(seconds=20),NOW,NOW+timedelta(minutes=1)):
            self.now=stamp;self.preparation.step()
        self.market.prepare_calendar.assert_not_called()

    def test_provider_failure_is_private_and_cannot_trigger_an_order(self):
        self.market.prepare_calendar.side_effect=RuntimeError('SYNTHETIC_PRIVATE_BODY')
        self.preparation.step()
        self.assertEqual(self.preparation.status()['state'],'PREPARATION_UNAVAILABLE')
        self.assertNotIn('SYNTHETIC_PRIVATE_BODY',str(self.preparation.status()))
        self.assertEqual([c[0] for c in self.market.method_calls],['prepare_calendar'])

    def test_warm_catalog_avoids_complete_chain_request_at_signal_but_requires_fresh_quotes(self):
        client=Mock();client.full_chain.return_value=payload_fixture()
        client.chain.return_value=payload_fixture()
        market=ManualMarketData(client,direct_quotes=True)
        self.preparation.market=market
        # Quotes in this historical fixture deliberately remain historical.
        self.now=NOW;self.plan['session_open']=(NOW+timedelta(seconds=60)).isoformat()
        self.preparation.step();client.full_chain.assert_called_once()
        signal_time=NOW+timedelta(seconds=60)
        market.get_catalog_chain('AMZN','CALL',signal_time)
        # Signal path now requests only the selected expiry, not the full calendar.
        client.full_chain.assert_called_once();client.chain.assert_called_once()
        cached=market.get_catalog_chain('AMZN','CALL',signal_time)
        _,_,candidates=manual_candidates(state_fixture(signal_time),cached,'AMZN','CALL',signal_time)
        self.assertEqual(candidates,())  # Fetching now does not refresh a quote timestamp.
        client.accounts.assert_not_called();client.orders.assert_not_called()

    def test_slow_preparation_cannot_block_entry_or_exit_loop(self):
        started=Event();release=Event();entered=Event();exited=Event()
        preparation=Mock()
        preparation.step.side_effect=lambda:(started.set(),release.wait(3))
        queue=Mock();queue.step.side_effect=lambda *args,**kw:entered.set()
        execution=Mock(binding='a'*64)
        execution.poll.side_effect=lambda:(exited.set(),[])[-1]
        worker=RealExecutionWorker(queue,execution,Mock(),preparation=preparation)
        try:
            worker.start()
            self.assertTrue(started.wait(1));self.assertTrue(entered.wait(1));self.assertTrue(exited.wait(1))
        finally:release.set();worker.shutdown()

    def test_tls_initialization_happens_once_without_oauth_or_http(self):
        from schwab_preview_client import SchwabPreviewClient
        context=Mock()
        with patch('schwab_preview_client.build_opener') as build:
            client=SchwabPreviewClient(context)
            build.assert_not_called()
            client.prepare_transport();client.prepare_transport()
            build.assert_called_once();context.oauth.access.assert_not_called()
            build.return_value.open.assert_not_called()
