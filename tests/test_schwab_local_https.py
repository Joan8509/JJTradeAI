from contextlib import contextmanager, redirect_stderr
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from scripts.schwab_oauth_receiver import handler_for, LOCAL_CALLBACK, BACKEND_PORT


@contextmanager
def backend():
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


class LocalReceiverTests(unittest.TestCase):
    def test_preflight_never_loads_vault_or_authorizes_and_does_not_log_queries(self):
        log = StringIO()
        with patch('scripts.schwab_oauth_receiver.EncryptedSchwabStore') as vault, redirect_stderr(log), backend() as port:
            for path, expected in [('/schwab/health', 200), ('/schwab/start', 503),
                    ('/schwab/callback?code=SYNTHETIC_PRIVATE_CODE&state=TEST', 503)]:
                connection = HTTPConnection('127.0.0.1', port, timeout=3)
                try:
                    connection.request('GET', path, headers={'Host': '127.0.0.1:8182'})
                    response = connection.getresponse()
                    body = response.read().decode()
                    self.assertEqual(response.status, expected)
                    self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                    self.assertNotIn('SYNTHETIC_PRIVATE_CODE', body)
                    if path == '/schwab/health':
                        self.assertIn('authorization_enabled=false', body)
                        self.assertIn('real_orders_enabled=false', body)
                finally:
                    connection.close()
            vault.assert_not_called()
        self.assertEqual(log.getvalue(), '')

    def test_foreign_host_is_rejected(self):
        with backend() as port:
            connection = HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                connection.request('GET', '/schwab/health', headers={'Host': 'evil.example'})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                connection.close()

    def test_health_only_cli_cannot_load_credentials(self):
        from scripts import schwab_oauth_receiver as receiver
        with patch('sys.argv', ['receiver', '--health-only']), \
                patch.object(receiver, 'EncryptedSchwabStore') as vault, \
                patch.object(receiver, 'QuietServer') as server:
            receiver.main()
            vault.assert_not_called()
            self.assertEqual(server.call_args.args[0], ('127.0.0.1', BACKEND_PORT))

    def test_real_backend_requires_exact_registered_callback_and_market_data_profile(self):
        from scripts import schwab_oauth_receiver as receiver
        base = {'oauth_config': {'client_id': 'SYNTHETIC', 'client_secret': 'SYNTHETIC',
                               'callback_url': LOCAL_CALLBACK},
                'real_orders_enabled': False, 'api_product': 'MARKET_DATA_ONLY'}
        for delta in [{'real_orders_enabled': True}, {'api_product': 'UNVERIFIED'},
                      {'oauth_config': dict(base['oauth_config'], callback_url=LOCAL_CALLBACK+'/')}]:
            with self.subTest(delta=delta), patch('sys.argv', ['receiver']), \
                    patch.object(receiver, 'EncryptedSchwabStore') as store, \
                    patch.object(receiver, 'QuietServer') as server:
                store.return_value.load.return_value = dict(base, **delta)
                with self.assertRaises(ValueError):
                    receiver.main()
                server.assert_not_called()


class NativeRequestPolicyTests(unittest.TestCase):
    def test_real_csharp_proxy_accepts_only_bounded_exact_host_bodyless_get_routes(self):
        source = str(Path(__file__).resolve().parents[1]/'scripts/schwab_loopback_tls.cs').replace("'", "''")
        good = 'GET /schwab/callback?code=SYNTHETIC%2B&state=TEST HTTP/1.1\r\nHost: 127.0.0.1:8182\r\nCookie: jj_schwab_state=TEST\r\n\r\n'
        bad = [
            good.replace('GET ', 'POST ', 1),
            good.replace('127.0.0.1:8182', 'localhost:8182'),
            good.replace('Host:', 'Host :'),
            good.replace('Host: 127.0.0.1:8182\r\n', ''),
            good.replace('Cookie:', 'Host: 127.0.0.1:8182\r\nCookie:'),
            good.replace('Cookie:', 'Transfer-Encoding: chunked\r\nCookie:'),
            good.replace('Cookie:', 'Content-Length: 0\r\nCookie:'),
            good.replace('Cookie:', 'Expect: 100-continue\r\nCookie:'),
            good.replace('Cookie:', 'Cookie: duplicate\r\nCookie:'),
            good.replace('/schwab/callback', '/other'),
            good.replace('/schwab/callback', 'https://evil.example/schwab/callback'),
            good.replace('code=SYNTHETIC%2B', 'code=x#fragment'),
            good.replace('TEST\r\n\r\n', 'x'*17000+'\r\n\r\n'),
            good.replace('jj_schwab_state=TEST', 'bad\nHeader: test'),
            good[:-4],
        ]
        command = "Add-Type -Path '"+source+"'; $cases=[Console]::In.ReadToEnd() | ConvertFrom-Json; " \
            "$results=@(foreach($case in $cases){try{$value=[JJSchwabLoopbackTls]::NormalizeRequest($case);" \
            "[pscustomobject]@{accepted=$true;value=$value}}catch{[pscustomobject]@{accepted=$false}}});" \
            "ConvertTo-Json -InputObject $results -Compress"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            input=json.dumps([good]+bad), capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, 'Native proxy compilation or policy test failed')
        decisions = json.loads(result.stdout)
        self.assertTrue(decisions[0]['accepted'])
        self.assertIn('Cookie: jj_schwab_state=TEST\r\n', decisions[0]['value'])
        self.assertNotIn('SYNTHETIC+', decisions[0]['value'])  # Preserve encoded code; decode once in OAuth.
        self.assertEqual([row['accepted'] for row in decisions[1:]], [False]*len(bad))


if __name__ == '__main__':
    unittest.main()
