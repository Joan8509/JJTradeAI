"""One-session read-only Schwab evidence inside the supervised Administrator radar.

No strategy, order, notification or Alpaca connection. Disabled without private
dated gate; it never enables trading or rewrites any market-data tolerance.
"""
from datetime import datetime,date,timedelta,timezone
import json
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
GATE=ROOT/'exports/private_runtime/schwab_data_probe.json'
STATUS=ROOT/'exports/private_runtime/schwab_data_probe.status.json'
NY=ZoneInfo('America/New_York')


def validate_gate(gate,now):
    target=date.fromisoformat(gate['session_date'])
    today=now.astimezone(NY).date()
    if (gate.get('format')!=1 or gate.get('enabled') is not True or gate.get('orders_enabled') is not False
            or not today<=target<=today+timedelta(days=1)):
        raise ValueError('READ_ONLY_DATED_GATE_REQUIRED')
    return target


def calendar_window(target):
    # One indexed row, query-only, two-second budget; no repository constructor.
    from contextlib import closing
    import sqlite3
    started=time.monotonic()
    with closing(sqlite3.connect((ROOT/'exports/market_data.db').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda:time.monotonic()-started>2,1000)
        row=db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',(target.isoformat(),)).fetchone()
    if not row:raise ValueError('OFFICIAL_SESSION_REQUIRED')
    opened,closed=map(datetime.fromisoformat,row)
    if opened.tzinfo is None or closed.tzinfo is None or not opened<closed:
        raise ValueError('OFFICIAL_SESSION_REQUIRED')
    return opened,closed


def owner_client():
    from schwab_connection import EncryptedSchwabStore,OAuthConfig,SchwabOAuth,SchwabReadOnlyClient
    store=EncryptedSchwabStore();profile=store.load()
    if profile.get('api_product')!='MARKET_DATA_ONLY' or profile.get('real_orders_enabled') is not False:
        raise ValueError('READ_ONLY_PROFILE_REQUIRED')
    return SchwabReadOnlyClient(SchwabOAuth(OAuthConfig(**profile['oauth_config']),store)),store


class DataProbe:
    def __init__(self,target,*,client_factory=owner_client,window=calendar_window,
                 clock=lambda:datetime.now(timezone.utc),status=STATUS,evidence=None):
        self.target=target;self.client_factory=client_factory;self.clock=clock
        self.opened,self.closed=window(target);self.stop=threading.Event()
        self.status=Path(status);self.evidence=Path(evidence) if evidence else ROOT/'exports/trade_review'/('schwab_rth_'+target.isoformat())
        self.thread=None

    def write_status(self,state,**fields):
        import os
        value=dict(state=state,checked_utc=self.clock().isoformat(),pid=os.getpid(),
                   session_date=self.target.isoformat(),real_orders_enabled=False,orders_sent=0,messages_sent=0,**fields)
        self.status.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.status.with_suffix('.tmp');tmp.write_text(json.dumps(value),encoding='utf-8');tmp.replace(self.status)

    def run(self):
        try:
            from telegram_manual_controls import poller_lock
            with poller_lock(self.status.with_suffix('.lock')):self._run()
        except Exception as error:
            code=getattr(error,'code',None)
            self.write_status(code if code in ('AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED','TRANSPORT_FAILURE') else 'PROBE_BLOCKED')

    def _run(self):
        from scripts.audit_schwab_market_readiness import chain_summary,quote_summary
        from watchlist_config import load_watchlist
        from vps_private_runtime import current_sid,session_id
        if not current_sid().endswith('-500') or session_id()!=0:
            raise ValueError('SUPERVISED_ADMINISTRATOR_REQUIRED')
        self.client,self.store=self.client_factory()
        profile=self.store.load();expiry=(profile.get('tokens') or {}).get('expires_at')
        symbols=list(load_watchlist(ROOT/'config/watchlist.json')['symbols'])
        # A real startup GET proves API/config access under the task's identity.
        payload=self.client.quotes(['AAPL','SPY','QQQ'],self.clock())
        self.evidence.mkdir(parents=True,exist_ok=True)
        startup=dict(checked_utc=self.clock().isoformat(),identity='ADMINISTRATOR_SESSION_0',
            quotes=[quote_summary(payload,s,self.clock()) for s in ('AAPL','SPY','QQQ')],
            orders_sent=0,messages_sent=0,real_orders_enabled=False)
        (self.evidence/'startup.json').write_text(json.dumps(startup,indent=2),encoding='utf-8')
        self.write_status('AUTHENTICATED_WAITING_RTH',starts_utc=(self.opened+timedelta(seconds=30)).isoformat(),
                          startup_quote_count=sum(q['status']=='QUOTE_RECEIVED' for q in startup['quotes']))
        start=self.opened+timedelta(seconds=30);end=min(self.closed,start+timedelta(seconds=150))
        while self.clock()<start:
            if self.stop.wait(min(30,(start-self.clock()).total_seconds())):return
        if self.clock()>=end:self.write_status('WINDOW_EXPIRED_NO_REPLAY');return
        observations=[]
        while not self.stop.is_set() and self.clock()<end:
            begun=self.clock()
            quotes=self.client.quotes(symbols,self.clock());checked=self.clock()
            observation=dict(checked_utc=checked.isoformat(),quotes=[quote_summary(quotes,s,checked) for s in symbols],chains=[])
            for symbol in ('AAPL','SPY','QQQ'):
                for side in ('CALL','PUT'):
                    if self.stop.is_set():return
                    raw=self.client.full_chain(symbol,side,self.clock())
                    observation['chains'].append(chain_summary(raw,symbol,side,self.clock(),
                        increments=profile.get('verified_contract_price_increments')))
            observation['completed_utc']=self.clock().isoformat();observations.append(observation)
            with (self.evidence/'observations.jsonl').open('a',encoding='utf-8') as output:output.write(json.dumps(observation)+'\n')
            self.write_status('OBSERVING_RTH',samples=len(observations))
            if self.stop.wait(max(1,15-(self.clock()-begun).total_seconds())):return
        after=self.store.load()
        summary=dict(samples=len(observations),completed_utc=self.clock().isoformat(),
            observed_span_seconds=(datetime.fromisoformat(observations[-1]['completed_utc'])-datetime.fromisoformat(observations[0]['checked_utc'])).total_seconds() if observations else 0,
            any_fresh_options=any(c['nearest_fresh_30s'] for o in observations for c in o['chains']),
            all_samples_have_fresh_representative_options=bool(observations) and all(c['nearest_fresh_30s']>0 for o in observations for c in o['chains']),
            token_expiry_advanced=bool(expiry and (after.get('tokens') or {}).get('expires_at','')>expiry),
            requires_review_before_activation=True,real_orders_enabled=False,orders_sent=0,messages_sent=0)
        (self.evidence/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        self.write_status('COMPLETED_REVIEW_REQUIRED',samples=len(observations))

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start();return self

    def close(self):self.stop.set()


def start_optional():
    try:
        if not GATE.exists():return None
        gate=json.loads(GATE.read_text(encoding='utf-8'))
        if gate.get('enabled') is not True:return None
        target=validate_gate(gate,datetime.now(timezone.utc))
        return DataProbe(target).start()
    except Exception:return None # Evidence-only errors must never stop the radar.
