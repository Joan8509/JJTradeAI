from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import json
from schwab_auth_watchdog import check_authorization, notice_for
from schwab_connection import SchwabError

NOW = datetime(2026, 10, 26, 13, 20, tzinfo=timezone.utc)


class WatchdogTests(TestCase):
    def setUp(self):
        self.profile = dict(real_orders_enabled=False, api_product='MARKET_DATA_ONLY',
            tokens=dict(authorization_started_at=(NOW-timedelta(days=1)).isoformat(),
                        expires_at=(NOW+timedelta(minutes=20)).isoformat()))
        self.store = Mock(); self.store.load.return_value = self.profile
        self.oauth = Mock(); self.factory = Mock(return_value=self.oauth)
        self.client = Mock(); self.client.quotes.return_value = {'AAPL': {'quote': {}}, 'SPY': {'quote': {}}}
        self.client_factory = Mock(return_value=self.client)

    def check(self, **kw):
        return check_authorization(self.store, self.factory, self.client_factory, NOW, **kw)

    def test_before_open_checks_provider_without_waiting_for_a_signal(self):
        result = self.check()
        self.assertEqual(result['state'], 'READY')
        self.client.quotes.assert_called_once_with(['AAPL', 'SPY'], NOW)
        self.oauth.refresh.assert_not_called()
        self.assertIsNone(notice_for(result, NOW))

    def test_refreshes_five_minutes_ahead_and_checks_persisted_access(self):
        self.profile['tokens']['expires_at'] = (NOW+timedelta(minutes=4)).isoformat()
        result = self.check()
        self.oauth.refresh.assert_called_once_with(NOW)
        self.assertTrue(result['refreshed'])
        self.client.quotes.assert_called_once()

    def test_revocation_is_exposed_without_retry_login_or_orders(self):
        self.client.quotes.side_effect = SchwabError('REAUTHORIZATION_REQUIRED')
        result = self.check()
        self.assertEqual(result['state'], 'REAUTHORIZATION_REQUIRED')
        self.assertIn('Acción necesaria', notice_for(result, NOW)[1])
        self.oauth.begin.assert_not_called()

    def test_precautionary_age_never_claims_provider_expiry(self):
        start = (NOW-timedelta(days=5)).isoformat()
        self.profile['tokens']['authorization_started_at'] = start
        result = self.check()
        self.assertEqual(result['state'], 'READY')
        self.assertTrue(result['renewal_reminder'])
        self.assertEqual(self.profile['tokens']['authorization_started_at'], start)
        self.assertIn('no indica una fecha', notice_for(result, NOW)[1])

    def test_429_respects_retry_after_across_runs(self):
        self.client.quotes.side_effect = SchwabError('RATE_LIMITED', retry_after_seconds=900)
        result = self.check()
        self.client.reset_mock()
        next_result = self.check(previous=result)
        self.assertEqual(next_result['state'], 'BACKOFF')
        self.client.quotes.assert_not_called()
        self.oauth.refresh.assert_not_called()

    def test_unexpected_exception_is_sanitized(self):
        self.factory.side_effect = ValueError('SYNTHETIC_PRIVATE_TOKEN')
        result = self.check()
        self.assertEqual(result['state'], 'CHECK_FAILED')
        self.assertNotIn('SYNTHETIC_PRIVATE_TOKEN', str(result))

    def test_non_readonly_profile_cannot_reach_network(self):
        self.profile['real_orders_enabled'] = True
        self.assertEqual(self.check()['state'], 'CHECK_FAILED')
        self.factory.assert_not_called()

    def test_missing_tokens_requires_intervention(self):
        self.profile['tokens'] = {}
        result = self.check()
        self.assertEqual(result['state'], 'AUTHORIZATION_REQUIRED')
        self.client_factory.assert_not_called()

    def test_daily_notice_id_is_stable_and_separate_from_strategy(self):
        self.client.quotes.side_effect = SchwabError('REAUTHORIZATION_REQUIRED')
        first = notice_for(self.check(), NOW)
        second = notice_for(self.check(), NOW+timedelta(minutes=5))
        self.assertEqual(first, second)
        self.assertTrue(first[0].startswith('authorization:'))

    def test_refresh_failure_does_not_claim_ready_or_query_with_old_access(self):
        self.profile['tokens']['expires_at'] = (NOW-timedelta(minutes=1)).isoformat()
        self.oauth.refresh.side_effect = SchwabError('REAUTHORIZATION_REQUIRED')
        result = self.check()
        self.assertEqual(result['state'], 'REAUTHORIZATION_REQUIRED')
        self.client_factory.assert_not_called()

    def test_uncertain_maintenance_send_is_claimed_once_across_process_runs(self):
        from scripts import watch_schwab_authorization as runner
        with TemporaryDirectory() as folder:
            root = Path(folder); (root/'exports/private_runtime').mkdir(parents=True)
            state = dict(state='REAUTHORIZATION_REQUIRED', real_orders_enabled=False)
            with patch.object(runner, 'ROOT', root), \
                 patch('schwab_connection.EncryptedSchwabStore'), \
                 patch('schwab_auth_watchdog.check_authorization', side_effect=lambda *a, **k: dict(state)), \
                 patch('vps_private_runtime.session_id', return_value=0), \
                 patch('vps_private_runtime.load_config', return_value={'TELEGRAM_BOT_TOKEN':'SYNTHETIC', 'TELEGRAM_CHAT_ID':'SYNTHETIC'}), \
                 patch('telegram_alerts.call', side_effect=TimeoutError('SYNTHETIC_PRIVATE')) as send, \
                 redirect_stdout(StringIO()):
                self.assertEqual(runner.main(), 2)
                self.assertEqual(runner.main(), 2)
            send.assert_called_once()
            saved = (root/'exports/private_runtime/schwab_auth_watchdog.json').read_text()
            self.assertNotIn('SYNTHETIC', saved)
            self.assertEqual(next(iter(json.loads(saved)['notices'].values()))['state'], 'UNCONFIRMED')
