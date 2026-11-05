"""Slow balance HTTP must not stop the host's readiness publication."""
from threading import Event
from unittest import TestCase
from unittest.mock import Mock,patch
import time
from real_execution_host import RealExecutionHost
from tests.test_real_order_ledger import Vault


class HostRefreshTests(TestCase):
    def test_only_real_market_client_gets_bounded_vault_without_http_or_simulation_change(self):
        from real_execution_host import owner_real_market_data
        market=Mock();vault=Mock()
        with patch('manual_trade_service.owner_market_data',return_value=market),patch(
                'real_execution_host.EncryptedSchwabStore',return_value=vault):
            self.assertIs(owner_real_market_data(),market)
        self.assertIs(market.client.oauth.store,vault)
        market.client.quotes.assert_not_called();market.client.oauth.access.assert_not_called()

    def test_real_owner_identity_is_checked_without_spawning_whoami(self):
        from real_live_storage import RealEncryptedStore
        from schwab_connection import SchwabError
        with patch('real_live_storage._process_sid',return_value='S-1-5-21-123-500'),patch('subprocess.check_output') as spawn:
            self.assertEqual(RealEncryptedStore._owner(),'S-1-5-21-123-500')
            spawn.assert_not_called()
        for sid in ('S-1-5-21-123-1001',None,'not-a-sid-500'):
            with patch('real_live_storage._process_sid',return_value=sid),self.assertRaises(SchwabError):
                RealEncryptedStore._owner()

    def fixture(self):
        host=RealExecutionHost();host.binding='a'*64;host.worker=Mock();host.protocol=True
        host.capital=Mock();host.capital.account_ready.return_value=True
        host.market=Mock()
        host._status=Mock()
        store=Vault();store.save(dict(purpose='REAL_CONTROL_V1',account=dict(binding=host.binding),
            execution_authorized=True,deployment_hold=False))
        return host,store

    def test_slow_refresh_cannot_hold_status_or_start_duplicate_refreshes(self):
        host,store=self.fixture();started=Event();release=Event()
        def slow():started.set();release.wait(2)
        host.capital.refresh.side_effect=slow
        try:
            with patch('real_execution_host.RealControlStore',return_value=store):
                begin=time.monotonic();host.tick()
                self.assertLess(time.monotonic()-begin,.5)
                self.assertTrue(started.wait(.5));host._status.assert_called_once_with([])
                # Even if the scheduled interval elapsed, the in-flight GET is single.
                host.last_refresh=0;host.tick()
                self.assertEqual(host.capital.refresh.call_count,1)
                self.assertEqual(host._status.call_count,2)
        finally:
            release.set();host._refresh_thread.join(1)

    def test_background_refresh_never_turns_missing_account_evidence_into_ready(self):
        host,store=self.fixture();host.capital.account_ready.return_value=False
        host.capital.blocker='LIVE_ACCOUNT_REFRESH_UNAVAILABLE'
        with patch('real_execution_host.RealControlStore',return_value=store):host.tick()
        host._refresh_thread.join(1)
        host._status.assert_called_once_with(['LIVE_ACCOUNT_REFRESH_UNAVAILABLE'])

    def test_market_oauth_maintenance_does_not_block_host_or_duplicate_slow_refresh(self):
        host,store=self.fixture();started=Event();release=Event()
        def slow(now):started.set();release.wait(2)
        host.market.client.oauth.access.side_effect=slow
        try:
            with patch('real_execution_host.RealControlStore',return_value=store):
                begin=time.monotonic();host.tick()
                self.assertLess(time.monotonic()-begin,.5)
                self.assertTrue(started.wait(.5));self.assertFalse(host._market_authorization_current())
                host._last_market_auth=0;host.tick()
                host.market.client.oauth.access.assert_called_once()
                self.assertEqual(host._status.call_count,2)
        finally:
            release.set();host._market_auth_thread.join(1);host._refresh_thread.join(1)
        self.assertTrue(host._market_authorization_current())
        host.market.client.quotes.assert_not_called();host.market.client.full_chain.assert_not_called()

    def test_slow_protocol_recovery_publishes_status_and_never_duplicates_diagnostics(self):
        host,store=self.fixture();host.protocol=False;started=Event();release=Event()
        def slow():started.set();release.wait(2);host.protocol=True
        host._verify_protocol=Mock(side_effect=slow)
        try:
            with patch('real_execution_host.RealControlStore',return_value=store):
                begin=time.monotonic();host.tick()
                self.assertLess(time.monotonic()-begin,.5);self.assertTrue(started.wait(.5))
                self.assertIn('LIVE_PREVIEW_PROTOCOL_NOT_VERIFIED',host._status.call_args.args[0])
                host.last_protocol=0;host.tick()
                self.assertEqual(host._verify_protocol.call_count,1)
                self.assertEqual(host._status.call_count,2)
        finally:
            release.set();host._protocol_thread.join(1);host._refresh_thread.join(1)
            host._market_auth_thread.join(1)
        self.assertTrue(host.protocol);self.assertIsNone(host.protocol_error)

    def test_missing_stale_or_rejected_option_authorization_is_not_ready(self):
        from schwab_connection import SchwabError
        from datetime import datetime,timezone
        host=RealExecutionHost()
        self.assertFalse(host._market_authorization_current())
        host.market=Mock();host._refresh_market_authorization()
        self.assertTrue(host._market_authorization_current())
        host._market_auth['checked']=time.monotonic()-45
        self.assertFalse(host._market_authorization_current())
        host.market.client.oauth.access.side_effect=SchwabError('REAUTHORIZATION_REQUIRED')
        host._refresh_market_authorization()
        self.assertFalse(host._market_authorization_current())
        self.assertEqual(host._market_authorization_blocker(),'LIVE_OPTION_DATA_REAUTHORIZE')
        host.binding='a'*64;host.capital=Mock();host.protocol=True;host.deployment_hold=False
        host.capital.account_ready.return_value=True
        host.worker=Mock();host.worker.preparation=None
        host.worker.status.return_value=dict(exits_current=True,entries_current=True)
        host.clock=lambda:datetime.now(timezone.utc)
        store=Vault()
        with patch('real_execution_host.RealHostStatusStore',return_value=store):host._status([])
        status=store.load()
        self.assertFalse(status['ready_to_arm']);self.assertFalse(status['option_market_authorization_current'])
        self.assertIn('LIVE_OPTION_DATA_REAUTHORIZE',status['blockers'])
        host.market.client.oauth.access.side_effect=None;host._refresh_market_authorization()
        with patch('real_execution_host.RealHostStatusStore',return_value=store):host._status([])
        self.assertTrue(store.load()['ready_to_arm'])

    def test_recovered_protocol_updates_entry_and_profit_preview_clients(self):
        from tests.test_schwab_option_order_request import contract,NOW
        from types import SimpleNamespace
        host=RealExecutionHost(clock=lambda:NOW);host.binding='a'*64
        host.context=SimpleNamespace(account_number='12345678')
        host.market=Mock();host.market.get_catalog_chain.return_value=SimpleNamespace(
            chain=SimpleNamespace(contracts=[contract()],underlying_price=contract().snapshot.strike))
        host.capital=Mock();host.worker=Mock()
        store=Vault();store.save(dict(purpose='REAL_CONTROL_V1',account=dict(binding=host.binding)))
        from schwab_connection import SchwabError
        preview=Mock();preview.preview.side_effect=[SchwabError('HTTP_ERROR',http_status=400),
            dict(source='SCHWAB_PREVIEW_ENDPOINT',state='PREVIEW_NO_REJECTION_REPORTED')]
        with patch('real_execution_host.RealControlStore',return_value=store),patch(
                'real_execution_host.SchwabPreviewClient',return_value=preview):host._verify_protocol()
        self.assertTrue(host.protocol)
        self.assertEqual(host.capital.preview.wire_format,'ORDER_REQUEST_V1')
        self.assertEqual(host.worker.targets.preview.wire_format,'ORDER_REQUEST_V1')
