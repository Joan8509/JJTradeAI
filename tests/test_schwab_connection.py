from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import traceback
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit, urlencode

from schwab_connection import (OAuthConfig, SchwabOAuth, SchwabTransport, SchwabError,
    SchwabReadOnlyClient, DisabledLiveExecution, EncryptedSchwabStore)

NOW = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.value = {}

    def load(self):
        return json.loads(json.dumps(self.value))

    def save(self, value):
        self.value = json.loads(json.dumps(value))

    @contextmanager
    def locked(self):
        yield


class SchwabConnectionTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.transport = Mock()
        self.transport.request.return_value = dict(token_type='Bearer', expires_in=1800,
            access_token='SYNTHETIC_ACCESS', refresh_token='SYNTHETIC_REFRESH')
        self.config = OAuthConfig('SYNTHETIC_APP', 'SYNTHETIC_SECRET', 'https://jj.example/schwab/callback')
        self.oauth = SchwabOAuth(self.config, self.store, transport=self.transport)

    def authorize(self):
        url, state = self.oauth.begin(NOW)
        callback = self.config.callback_url+'?'+urlencode({'code': 'code+value@', 'state': state})
        self.oauth.complete(callback, state, NOW)
        return callback, state

    def test_exact_https_callback_and_credentials_hidden_in_repr(self):
        self.assertNotIn('SYNTHETIC_SECRET', repr(self.config))
        self.assertNotIn('SYNTHETIC_APP', repr(self.config))
        for value in ('http://jj.example/cb', 'https://user:pass@jj.example/cb',
                      'https://jj.example/cb?token=x', 'https://jj.example/cb#code'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OAuthConfig('x', 'y', value)

    def test_single_use_state_browser_binding_and_code_decoded_exactly_once(self):
        callback, state = self.authorize()
        request = self.transport.request.call_args
        self.assertEqual(request.kwargs['form']['code'], 'code+value@')
        self.assertNotIn('authorization', self.store.value)
        self.assertEqual(self.oauth.access(NOW), 'SYNTHETIC_ACCESS')
        with self.assertRaisesRegex(SchwabError, 'USED'):
            self.oauth.complete(callback, state, NOW)
        self.transport.request.assert_called_once()

    def test_wrong_cookie_foreign_callback_duplicate_parameters_and_expired_state_block(self):
        _, state = self.oauth.begin(NOW)
        good = self.config.callback_url+'?'+urlencode({'code': 'x', 'state': state})
        cases = [(good, 'wrong', NOW), (good.replace('jj.example', 'evil.example'), state, NOW),
                 (good+'&code=second', state, NOW), (good, state, NOW+timedelta(minutes=5))]
        for callback, cookie, now in cases:
            with self.subTest(callback=callback), self.assertRaises(SchwabError):
                self.oauth.complete(callback, cookie, now)
        self.transport.request.assert_not_called()

    def test_timeout_consumes_code_and_no_automatic_replay(self):
        _, state = self.oauth.begin(NOW)
        self.transport.request.side_effect = SchwabError('TRANSPORT_FAILURE')
        callback = self.config.callback_url+'?'+urlencode({'code': 'x', 'state': state})
        with self.assertRaises(SchwabError):
            self.oauth.complete(callback, state, NOW)
        with self.assertRaisesRegex(SchwabError, 'USED'):
            self.oauth.complete(callback, state, NOW)
        self.transport.request.assert_called_once()

    def test_refresh_persists_rotation_and_does_not_reset_initial_authorization_time(self):
        self.authorize()
        self.transport.request.return_value = dict(token_type='Bearer', expires_in=1800,
            access_token='ROTATED_ACCESS', refresh_token='ROTATED_REFRESH')
        self.assertEqual(self.oauth.access(NOW+timedelta(minutes=30)), 'ROTATED_ACCESS')
        self.assertEqual(self.store.value['tokens']['refresh_token'], 'ROTATED_REFRESH')
        self.assertEqual(self.store.value['tokens']['authorization_started_at'], NOW.isoformat())
        self.assertEqual(self.transport.request.call_args.kwargs['form']['refresh_token'], 'SYNTHETIC_REFRESH')

    def test_invalid_refresh_propagates_without_restarting_login(self):
        self.authorize()
        self.transport.request.side_effect = SchwabError('REAUTHORIZATION_REQUIRED', http_status=401)
        with self.assertRaisesRegex(SchwabError, 'REAUTHORIZATION'):
            self.oauth.access(NOW+timedelta(hours=1))
        self.assertEqual(self.transport.request.call_count, 2)

    def test_order_mutations_and_host_traversal_rejected_before_any_network(self):
        opener = Mock()
        transport = SchwabTransport(opener=opener)
        for method, path in [('POST','/trader/v1/accounts/abc/orders'), ('DELETE','/trader/v1/accounts/abc/orders/1'),
                             ('PUT','/trader/v1/accounts/abc/orders/1'), ('GET','//evil.example/path'),
                             ('GET','/trader/v1/accounts/../orders'), ('POST','/v1/oauth/token?other=x')]:
            with self.subTest(path=path), self.assertRaises(SchwabError):
                transport.request(method, path)
        opener.open.assert_not_called()
        with self.assertRaisesRegex(SchwabError, 'REAL_ORDERS_DISABLED'):
            DisabledLiveExecution().dispatch({'orders_enabled': True})

    def test_429_backoff_and_exception_chain_do_not_expose_secret_url(self):
        clock = [0.]
        def sleep(seconds):
            clock[0] += seconds
        opener = Mock()
        opener.open.side_effect = HTTPError('https://private/SYNTHETIC_SECRET',429,
            'SYNTHETIC_SECRET',{'Retry-After':'15'},BytesIO(b'SYNTHETIC_SECRET'))
        transport = SchwabTransport(opener=opener, clock=lambda:clock[0], sleeper=sleep)
        for _ in range(2):
            try:
                transport.request('GET','/marketdata/v1/quotes')
            except SchwabError as error:
                self.assertEqual(error.retry_after_seconds, 15)
                self.assertNotIn('SYNTHETIC_SECRET', ''.join(traceback.format_exception(error)))
        self.assertGreaterEqual(clock[0],15)

    def test_read_only_client_uses_explicit_account_and_get_only(self):
        self.authorize()
        self.transport.request.reset_mock()
        client = SchwabReadOnlyClient(self.oauth)
        client.positions('SYNTHETIC_HASH',NOW)
        client.orders('SYNTHETIC_HASH',NOW-timedelta(days=1),NOW,NOW)
        client.chain('AAPL','CALL',NOW.date(),(NOW+timedelta(days=7)).date(),NOW)
        self.assertTrue(all(call.args[0]=='GET' for call in self.transport.request.call_args_list))
        with self.assertRaises(ValueError):
            client.positions('../account',NOW)

    def test_schwab_vault_cannot_overwrite_existing_alpaca_or_plaintext_files(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]/'exports/private_runtime'
        for name in ('runtime.dpapi','config.json','tokens.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                EncryptedSchwabStore(root/name)

    def test_full_chain_get_does_not_hide_later_listed_expirations(self):
        self.authorize();self.transport.request.reset_mock()
        SchwabReadOnlyClient(self.oauth).full_chain('AMZN','CALL',NOW)
        request=self.transport.request.call_args
        self.assertEqual(request.args,('GET','/marketdata/v1/chains'))
        self.assertEqual(request.kwargs['params']['range'],'ALL')
        self.assertNotIn('fromDate',request.kwargs['params'])
        self.assertNotIn('toDate',request.kwargs['params'])

    def test_explicit_refresh_preserves_authorization_age_and_private_profile_fields(self):
        self.authorize();self.store.value['real_orders_enabled']=False
        self.store.value['private_policy']={'preserve':True}
        started=self.store.value['tokens']['authorization_started_at']
        self.transport.request.reset_mock()
        self.transport.request.return_value=dict(token_type='Bearer',expires_in=1800,
            access_token='SYNTHETIC_NEW_ACCESS',refresh_token='SYNTHETIC_NEW_REFRESH')
        self.assertEqual(self.oauth.refresh(NOW+timedelta(seconds=1)),'SYNTHETIC_NEW_ACCESS')
        self.assertEqual(self.store.value['tokens']['authorization_started_at'],started)
        self.assertEqual(self.store.value['tokens']['refresh_token'],'SYNTHETIC_NEW_REFRESH')
        self.assertEqual(self.store.value['private_policy'],{'preserve':True})
        self.assertFalse(self.store.value['real_orders_enabled'])
        self.assertEqual(self.transport.request.call_args.args,('POST','/v1/oauth/token'))


if __name__ == '__main__':
    unittest.main()
