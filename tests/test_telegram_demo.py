"""Static preview cannot place even a simulated order or expose private files."""
import http.client
import json
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer
from scripts.serve_telegram_demo import DemoHandler


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),DemoHandler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,method,path):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request(method,path);r=connection.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:connection.close()

    def test_demo_assets_health_csp_and_no_actions_or_private_paths(self):
        for path in ('/','/telegram-demo/','/demo.js','/style.css','/demo.css'):
            status,headers,body=self.request('GET',path)
            self.assertEqual(status,200);self.assertTrue(body)
            self.assertIn("connect-src 'none'",headers['Content-Security-Policy'])
        health=json.loads(self.request('GET','/health')[2])
        self.assertFalse(health['real_orders_enabled']);self.assertFalse(health['simulation_orders_enabled'])
        for method in ('POST','PUT','PATCH','DELETE'):
            self.assertEqual(self.request(method,'/api/execute')[0],405)
        for path in ('/api/execute','/api/state','/../telegram_alerts.py','/exports/private_runtime/schwab.dpapi'):
            self.assertEqual(self.request('GET',path)[0],404)

    def test_explicit_fictional_data_disabled_buy_sell_and_no_trading_import(self):
        root=Path(__file__).resolve().parents[1]
        page=(root/'web/telegram_demo/index.html').read_text(encoding='utf-8')
        self.assertIn('Todos los precios, contratos y resultados son ficticios',page)
        self.assertIn('disabled type="button">Ejecutar compra',page)
        self.assertIn('disabled type="button">Cerrar posición',page)
        server=(root/'scripts/serve_telegram_demo.py').read_text()
        self.assertNotIn('import telegram_manual',server);self.assertNotIn('import schwab',server)
        js=(root/'web/telegram_demo/demo.js').read_text()
        self.assertNotIn('fetch(',js);self.assertNotIn('XMLHttpRequest',js)
