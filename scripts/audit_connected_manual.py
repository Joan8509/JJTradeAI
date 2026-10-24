"""Owner metadata-only operational audit. No messages, account/order API or fills."""
from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit,urlunsplit
from urllib.request import Request,urlopen

_AUDIT_STAGE='INITIAL'
def audit_stage(name):
    global _AUDIT_STAGE
    _AUDIT_STAGE=name

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def audit():
    from schwab_connection import EncryptedSchwabStore
    from telegram_alerts import call,_tls_context
    from manual_trade_links import app_url
    from vps_private_runtime import load_config
    result=dict(checked_utc=datetime.now(timezone.utc).isoformat(),messages_sent=0,orders_sent=0)
    audit_stage('LOCAL_PROFILE')
    profile=EncryptedSchwabStore().load()
    if (profile.get('real_orders_enabled') is not False or profile.get('api_product')!='MARKET_DATA_ONLY'
            or profile.get('manual_practice_enabled') is not True):raise ValueError
    result.update(real_orders_enabled=False,manual_practice_enabled=True)
    audit_stage('PRIVATE_RUNTIME_CONFIG')
    settings=load_config();token=settings['TELEGRAM_BOT_TOKEN'];owner=settings['TELEGRAM_CHAT_ID']
    audit_stage('TELEGRAM_GET_ME')
    bot=call(token,'getMe')
    audit_stage('TELEGRAM_GET_CHAT')
    chat=call(token,'getChat',chat_id=owner)
    result['telegram_authenticated']=(bot.get('is_bot') is True and str(bot.get('id'))==token.split(':')[0]
        and str(chat.get('id'))==str(owner))
    audit_stage('MONITOR_RECEIPTS')
    status=json.loads((ROOT/'exports/private_runtime/telegram_manual.status.json').read_text())
    probe=json.loads((ROOT/'exports/private_runtime/schwab_data_probe.status.json').read_text())
    result.update(companion_state=status.get('state'),monitor_ready=status.get('monitor_ready'),
        active_stop_loss_pct=status.get('stop_loss_pct'),
        companion_pid=status.get('pid'),heartbeat_age_seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(status['heartbeat'])).total_seconds(),
        probe_state=probe.get('state'),probe_same_pid=probe.get('pid')==status.get('pid'),
        startup_schwab_quotes=probe.get('startup_quote_count'))
    parts=urlsplit(app_url());origin=urlunsplit((parts.scheme,parts.netloc,'','',''));ctx=_tls_context()
    for path,name in [('/_stcore/health','interface_https'),('/telegram/','miniapp_https'),('/telegram/health','miniapp_health_https')]:
        audit_stage(name.upper())
        with urlopen(origin+path,timeout=10,context=ctx) as response:result[name]=response.status
    # GET/previews cannot buy, and unsigned POST must fail before a review/claim.
    for request,name,expected in [(origin+'/telegram/api/execute','get_execute_status',404),
        (Request(origin+'/telegram/api/execute',method='POST',
            data=b'{"init_data":"","intent":"invalid"}',headers={'Content-Type':'application/json','Origin':origin}),
             'unsigned_post_status',403)]:
        audit_stage(name.upper())
        try:
            with urlopen(request,timeout=10,context=ctx) as response:code=response.status
        except HTTPError as error:code=error.code
        result[name]=code
        if code!=expected:raise ValueError('HTTP_GUARD_FAILURE')
    audit_stage('LEDGER_COUNTS')
    ledger=ROOT/'exports/trade_review/manual_simulation/observed_manual_v1/ledger.db'
    with closing(sqlite3.connect(ledger.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        result['local_orders']=db.execute('SELECT COUNT(*) FROM simulated_orders').fetchone()[0]
        result['local_fills']=db.execute('SELECT COUNT(*) FROM simulated_fills').fetchone()[0]
    audit_stage('WRITE_AUDIT_RECEIPT')
    evidence=ROOT/'exports/trade_review/connected_manual_deployment/audit.json'
    evidence.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    try:
        result=audit();print(json.dumps(result))
        if not result['telegram_authenticated']:raise SystemExit(2)
    except Exception as error:
        result={'status':'AUDIT_BLOCKED','stage':_AUDIT_STAGE,'error_type':type(error).__name__,'details_hidden':True,'messages_sent':0,'orders_sent':0}
        if isinstance(error,HTTPError):result['http_status']=error.code
        print(json.dumps(result));raise SystemExit(2)
