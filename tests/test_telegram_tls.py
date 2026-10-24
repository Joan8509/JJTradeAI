import io
import ssl
import unittest
from unittest.mock import patch
from urllib.error import URLError

from telegram_alerts import _tls_context, call, TelegramError


class TelegramTlsTests(unittest.TestCase):
    def tearDown(self):
        _tls_context.cache_clear()

    def test_system_and_mozilla_roots_preserve_strict_verification(self):
        _tls_context.cache_clear()
        context = _tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
        self.assertIs(context, _tls_context())

    def test_call_uses_verified_context(self):
        with patch('telegram_alerts.urlopen') as api:
            api.return_value.__enter__.return_value = io.BytesIO(b'{"ok":true,"result":{"is_bot":true}}')
            self.assertTrue(call('123:example', 'getMe')['is_bot'])
        context = api.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_certificate_failure_does_not_retry_unverified_or_expose_key(self):
        with patch('telegram_alerts.urlopen', side_effect=URLError(ssl.SSLCertVerificationError('123:example'))) as api:
            with self.assertRaises(TelegramError) as raised:
                call('123:example', 'getMe')
        api.assert_called_once()
        self.assertNotIn('123:example', str(raised.exception))
