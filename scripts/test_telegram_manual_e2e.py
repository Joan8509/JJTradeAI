"""Headless browser through real loopback HTTP and temporary simulation databases.

No real credentials, Telegram SDK/API, account API, Schwab transport or active DB.
Only the isolated fixture overrides its advertised origin to its ephemeral HTTP
loopback port. Production HTTPS/origin/signature checks are not changed.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from telegram_manual_http import LoopbackServer,handler_for
from tests.test_manual_alert_entry import AlertEntryTests

EDGE=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')


def scenario(target):
    fixture=AlertEntryTests();fixture.setUp()
    f=fixture.f;service=fixture.h.service
    if target=='REJECT':
        def rejected_quote(*args):
            payload=deepcopy(f.payload)
            payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['bid']=1.50
            return payload
        f.client.chain.side_effect=rejected_quote
    server=LoopbackServer(('127.0.0.1',0),None)
    service.origin='http://127.0.0.1:'+str(server.server_port)
    service.base_url=service.origin+'/telegram/'
    base=handler_for(service);routes=Counter()
    class Handler(base):
        def do_GET(self):
            path=self._path()
            if path=='/':
                html=(ROOT/'web/telegram_manual/index.html').read_text(encoding='utf-8')
                html=html.replace('https://telegram.org/js/telegram-web-app.js','fixture-sdk.js')
                html=html.replace('</head>','<script src="fixture-driver.js" defer></script></head>')
                html=html.replace('</body>','<pre id="e2e-results"></pre></body>')
                self._response(200,html.encode(),'text/html; charset=utf-8');return
            if path=='/fixture-sdk.js':
                script='window.Telegram={WebApp:{initData:'+json.dumps(fixture.h.raw())+',ready(){},expand(){}}};'
                script+='Date.now=()=>'+str(int(f.now.timestamp()*1000))+';window.fixtureTarget='+json.dumps('MANUAL' if target=='REJECT' else target)+';window.fixtureReject='+str(target=='REJECT').lower()+';'
                self._response(200,script.encode(),'text/javascript; charset=utf-8');return
            if path=='/fixture-driver.js':
                self._response(200,(ROOT/'tests/telegram_manual_e2e_driver.js').read_bytes(),'text/javascript; charset=utf-8');return
            super().do_GET()
        def do_POST(self):
            path=self._path();routes[path]+=1
            if path=='/fixture-step':
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                step=body['step']
                bid,ask=(1.95,2.) if step==1 else (2.10,2.15) if step==2 or target=='MANUAL' else (2.75,2.80)
                f.quote(bid=bid,ask=ask,seconds=step)
                f.client.chain.side_effect=lambda *a:deepcopy(f.payload)
                f.service.observe()
                self._response(200,{'ok':True});return
            super().do_POST()
    server.RequestHandlerClass=Handler
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='jjtrade_e2e_browser_') as temp:
            folder=Path(temp)
            url=service.base_url+'#entry=AMZN&side=CALL&candle='+quote(fixture.candle,safe='')
            run=subprocess.run([str(EDGE),'--headless=new','--disable-gpu','--no-first-run',
                '--disable-background-networking','--disable-extensions','--no-default-browser-check',
                '--user-data-dir='+str(folder/'profile'),'--dump-dom','--virtual-time-budget=20000',url],
                capture_output=True,timeout=70)
            dom=run.stdout.decode('utf-8',errors='replace')
        match=re.search(r'<pre id="e2e-results">(.*?)</pre>',dom,re.S)
        passed='data-e2e-result="PASS"' in dom
        orders=f.engine.ledger.orders()
        passed=passed and len(orders)==(0 if target=='REJECT' else 2) and all(o['status']=='FILLED' for o in orders) and not f.service.positions()
        passed=passed and routes['/api/entry-buy']==1 and routes['/api/execute']==0
        result=dict(target=target,passed=passed,returncode=run.returncode,
            checks=match.group(1) if match else 'BROWSER_RESULT_MISSING',routes=dict(routes),
            isolated_orders=len(orders),isolated_closed=not f.service.positions(),
            active_database_used=False,real_orders_enabled=False,messages_sent=0)
        if not passed:(ROOT/'exports/trade_review/telegram_manual_e2e'/('failed_'+target+'.html')).write_text(dom,encoding='utf-8')
        return result
    finally:
        server.shutdown();server.server_close();thread.join(3);fixture.doCleanups()


def main():
    out=ROOT/'exports/trade_review/telegram_manual_e2e';out.mkdir(parents=True,exist_ok=True)
    requested=sys.argv[1:] or ['MANUAL','35','REJECT']
    if any(t not in ('MANUAL','35','REJECT') for t in requested):raise ValueError('SYNTHETIC_TARGET_INVALID')
    results=[]
    for target in requested:
        result=scenario(target);results.append(result);print(json.dumps(result),flush=True)
    result=dict(checked_utc=datetime.now(timezone.utc).isoformat(),synthetic_only=True,real_http=True,results=results)
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if all(r['passed'] for r in results) else 2


if __name__=='__main__':raise SystemExit(main())
