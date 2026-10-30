"""Separate account OAuth state/cookie and native policy; local synthetic tokens."""
from contextlib import closing,redirect_stderr
from datetime import datetime,timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from threading import Thread
from unittest import TestCase
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit,urlencode
from scripts.schwab_accounts_oauth_receiver import build_oauth,COOKIE_NAME,ACCOUNT_CALLBACK,main
from scripts.schwab_oauth_receiver import handler_for
from schwab_connection import SchwabOAuth,OAuthConfig
from tests.test_schwab_connection import MemoryStore


class RealAccountOAuthTests(TestCase):
    def test_native_proxy_is_isolated_copy_with_same_request_policy(self):
        root=Path(__file__).resolve().parents[1]/'scripts'
        original=(root/'schwab_loopback_tls.cs').read_text(encoding='utf-8')
        actual=(root/'schwab_accounts_loopback_tls.cs').read_text(encoding='utf-8')
        self.assertEqual(actual,original.replace('JJSchwabLoopbackTls','JJSchwabAccountsLoopbackTls').replace('8182','8186').replace('8183','8187'))

    def test_health_only_uses_separate_port_and_never_reads_any_vault(self):
        with patch('sys.argv',['accounts','--health-only']),patch('scripts.schwab_accounts_oauth_receiver.AccountReadOnlyStore') as store,\
             patch('scripts.schwab_accounts_oauth_receiver.QuietServer') as server:
            main();store.assert_not_called()
            self.assertEqual(server.call_args.args[0],('127.0.0.1',8187))

    def test_wrong_product_or_callback_is_rejected(self):
        from real_account_readonly import PRODUCT
        profile=dict(real_orders_enabled=False,api_product=PRODUCT,
            oauth_config=dict(client_id='SYNTHETIC',client_secret='SYNTHETIC',callback_url=ACCOUNT_CALLBACK))
        for delta in ({'api_product':'MARKET_DATA_ONLY'},{'real_orders_enabled':True},
            {'oauth_config':dict(profile['oauth_config'],callback_url='https://127.0.0.1:8182/schwab/callback')}):
            with self.subTest(delta=delta),self.assertRaises(ValueError):build_oauth(Mock(load=lambda:dict(profile,**delta)))

    def test_account_cookie_is_distinct_and_old_cookie_cannot_authorize(self):
        store=MemoryStore();market_store=MemoryStore();market_store.value={'keep':'DATA_APP_UNCHANGED'}
        transport=Mock();transport.request.return_value=dict(token_type='Bearer',expires_in=1800,
            access_token='SYNTHETIC_ACCOUNT_ACCESS',refresh_token='SYNTHETIC_ACCOUNT_REFRESH')
        oauth=SchwabOAuth(OAuthConfig('SYNTHETIC_KEY','SYNTHETIC_SECRET',ACCOUNT_CALLBACK),store,transport=transport)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(oauth,cookie_name=COOKIE_NAME))
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        def request(path,cookie=None):
            with closing(HTTPConnection('127.0.0.1',server.server_port,timeout=3)) as connection:
                headers={'Host':'127.0.0.1:8186'}
                if cookie:headers['Cookie']=cookie
                connection.request('GET',path,headers=headers);response=connection.getresponse()
                return response.status,dict(response.getheaders()),response.read().decode()
        log=StringIO()
        try:
            with redirect_stderr(log):
                status,headers,_=request('/schwab/start');self.assertEqual(status,302)
                self.assertTrue(headers['Set-Cookie'].startswith(COOKIE_NAME+'='))
                state=parse_qs(urlsplit(headers['Location']).query)['state'][0]
                callback='/schwab/callback?'+urlencode(dict(code='SYNTHETIC_CODE',state=state))
                self.assertEqual(request(callback,'jj_schwab_state='+state)[0],409)
                transport.request.assert_not_called()
                status,headers,body=request(callback,COOKIE_NAME+'='+state)
                self.assertEqual(status,200);self.assertNotIn('SYNTHETIC_ACCOUNT_ACCESS',body)
                self.assertEqual(headers['Cache-Control'],'no-store')
                self.assertEqual(request(callback,COOKIE_NAME+'='+state)[0],409)
                self.assertEqual(market_store.value,{'keep':'DATA_APP_UNCHANGED'})
                self.assertEqual(transport.request.call_count,1)
        finally:server.shutdown();server.server_close();thread.join(3)
        self.assertEqual(log.getvalue(),'')
