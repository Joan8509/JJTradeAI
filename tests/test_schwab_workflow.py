from contextlib import closing
from datetime import datetime,timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock
from urllib.parse import urlsplit,parse_qs,urlencode

from scripts.schwab_oauth_receiver import handler_for
from scripts.check_schwab_readonly import inspect_account
from schwab_connection import SchwabOAuth,OAuthConfig
from schwab_rehearsal import run_synthetic_rehearsal
from schwab_simulation import policy_from_dict,ExecutionBlocked
from tests.test_schwab_connection import MemoryStore


class SchwabWorkflowTests(unittest.TestCase):
    def test_public_template_is_incomplete_and_real_mode_is_rejected(self):
        root=Path(__file__).resolve().parents[1]
        payload=json.loads((root/'config/schwab_automation.example.json').read_text())
        with self.assertRaisesRegex(ExecutionBlocked,'POLICY_INCOMPLETE'):
            policy_from_dict(payload).require_complete()
        for changes in ({'mode':'LIVE'},{'real_orders_enabled':True}):
            with self.assertRaisesRegex(ExecutionBlocked,'REAL_ORDERS_DISABLED'):
                policy_from_dict(payload|changes)
        with self.assertRaisesRegex(ExecutionBlocked,'FIXED_CONTRACT_QUANTITY_UNSUPPORTED'):
            policy_from_dict(payload|{'contracts':3})
        with self.assertRaisesRegex(ExecutionBlocked,'AUTOMATIC_BUDGET_SIZING_NOT_ACTIVE'):
            policy_from_dict(payload|{'entry_budget_usd':'601.95'})

    def test_readonly_check_does_not_select_the_only_account_implicitly(self):
        client=Mock();client.accounts.return_value=[{'hashValue':'SYNTHETIC_HASH','accountNumber':'99990000'}]
        result=inspect_account(client,{},datetime.now(timezone.utc))
        self.assertEqual(result['status'],'ACCOUNT_SELECTION_REQUIRED')
        client.positions.assert_not_called();client.orders.assert_not_called()
        self.assertNotIn('99990000',json.dumps(result));self.assertNotIn('SYNTHETIC_HASH',json.dumps(result))

    def test_readonly_check_rejects_account_identity_mismatch_without_orders_lookup(self):
        client=Mock();client.accounts.return_value=[{'hashValue':'SYNTHETIC_HASH','accountNumber':'99990000'}]
        client.positions.return_value={'securitiesAccount':{'accountNumber':'99991111'}}
        result=inspect_account(client,{'selected_account_hash':'SYNTHETIC_HASH'},datetime.now(timezone.utc))
        self.assertEqual(result['status'],'ACCOUNT_IDENTITY_MISMATCH');client.orders.assert_not_called()

    def test_actual_http_callback_binds_cookie_and_does_not_return_tokens(self):
        transport=Mock();transport.request.return_value=dict(token_type='Bearer',expires_in=1800,
            access_token='SYNTHETIC_ACCESS',refresh_token='SYNTHETIC_REFRESH')
        oauth=SchwabOAuth(OAuthConfig('TEST_APP','TEST_SECRET','https://jj.example/schwab/callback'),
                         MemoryStore(),transport=transport)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(oauth))
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        try:
            def request(path,cookie=None,host='jj.example'):
                with closing(HTTPConnection('127.0.0.1',server.server_port,timeout=3)) as connection:
                    headers={'Host':host}
                    if cookie:headers['Cookie']=cookie
                    connection.request('GET',path,headers=headers)
                    response=connection.getresponse()
                    return response.status,dict(response.getheaders()),response.read().decode('utf-8')
            status,_,_=request('/schwab/start',host='evil.example')
            self.assertEqual(status,403);transport.request.assert_not_called()
            status,headers,_=request('/schwab/start')
            self.assertEqual(status,302)
            self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('Secure',headers['Set-Cookie'])
            state=parse_qs(urlsplit(headers['Location']).query)['state'][0]
            callback='/schwab/callback?'+urlencode({'code':'SYNTHETIC_CODE','state':state})
            self.assertEqual(request(callback)[0],409);transport.request.assert_not_called()
            status,headers,body=request(callback,'jj_schwab_state='+state)
            self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertNotIn('SYNTHETIC_ACCESS',body);self.assertNotIn('SYNTHETIC_REFRESH',body)
            self.assertEqual(request(callback,'jj_schwab_state='+state)[0],409)
            transport.request.assert_called_once()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)

    def test_production_detector_to_simulated_broker_rehearsal_and_existing_path_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'scenario'
            report=run_synthetic_rehearsal(root)
            self.assertEqual(report['status'],'OK');self.assertTrue(all(report['checks'].values()))
            self.assertFalse(report['test_policy_is_user_approved'])
            self.assertFalse(report['schwab_connection_verified'])
            self.assertFalse(report['real_orders_enabled'])
            self.assertEqual(report['simulated_bought_contracts'],report['simulated_sold_contracts'])
            with self.assertRaises(FileExistsError):run_synthetic_rehearsal(root)


if __name__=='__main__':unittest.main()
