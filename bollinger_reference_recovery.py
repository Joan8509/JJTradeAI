"""Repair only missing official Bollinger references; never evaluate signals."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
import json,sqlite3,time
from pathlib import Path
from threading import Event,Thread
from urllib.request import urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo
from alpaca_market_data import AlpacaMarketDataProvider
from bollinger_reference_scope import active_reference_scope,required_periods

UTC=timezone.utc;NY=ZoneInfo('America/New_York')

def missing_reference_windows(database,symbol,feed,now,*,reference_scope=None):
    scope=reference_scope or active_reference_scope()
    """Twenty official periods, plus the exact final preceding minute."""
    began=time.monotonic()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=.25)) as db:
        db.set_progress_handler(lambda:time.monotonic()-began>.25,1000)
        rows=db.execute(
            'SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? AND session_date<=? ORDER BY session_date',
            ((now.astimezone(NY).date()-timedelta(days=7)).isoformat(),now.astimezone(NY).date().isoformat())).fetchall()
        if not rows:raise ValueError('REFERENCE_CALENDAR_UNAVAILABLE')
        opened,closed=(datetime.fromisoformat(v).astimezone(UTC) for v in rows[-1])
        anchor=opened if now<opened else min(closed,opened+timedelta(minutes=15*int((now-opened).total_seconds()//900)))
        required=required_periods(rows,anchor,scope=scope)
        if not required:raise ValueError('REFERENCE_PERIODS_UNAVAILABLE')
        missing=[]
        for a,b in required:
            row=db.execute('SELECT timestamp FROM minute_bars WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1',
                ('ALPACA',feed,symbol,a.isoformat(),(b-timedelta(minutes=1)).isoformat())).fetchone()
            if row is None:missing.append((a,b))
            elif (a,b)==required[-1] and datetime.fromisoformat(row[0])!=b-timedelta(minutes=1):
                missing.append((b-timedelta(minutes=1),b))
        return missing

class ReferenceRecovery:
    """One REST request/sec, bounded sweeps >=300sec, retry-after honored.

    Runs separately from trades and bar analysis. Uses the collector's existing
    provider/feed and store; no additional WebSocket, claims or notifications.
    """
    def __init__(self,config,store,symbols,*,provider=None):
        self.config,self.store,self.symbols=config,store,tuple(symbols)
        self.stop=Event();self.last_request=0;self.cursor=0;self.retry_after=300
        self.provider=provider or AlpacaMarketDataProvider(config,transport=self.transport)
        self.thread=None

    def transport(self,request):
        if self.stop.wait(max(0,1-(time.monotonic()-self.last_request))):raise InterruptedError()
        self.last_request=time.monotonic()
        with urlopen(request,timeout=15) as response:return json.load(response)

    def sweep(self,now=None):
        now=now or datetime.now(UTC);results={};requests=0;self.retry_after=300
        for offset in range(len(self.symbols)):
            index=(self.cursor+offset)%len(self.symbols);symbol=self.symbols[index]
            if self.stop.is_set():break
            try:
                windows=missing_reference_windows(self.store.database_path,symbol,self.config.feed,now)
                if not windows:
                    results[symbol]=dict(status='NO_REQUIRED_GAPS');continue
                if requests>=4:
                    self.cursor=index;break
                requests+=1
                frame=self.provider.fetch_minute_bars(symbol,start=min(a for a,b in windows),end=max(b for a,b in windows)-timedelta(minutes=1))
                mask=frame.date.map(lambda t:any(a<=t<b for a,b in windows))
                frame=frame.loc[mask]
                if self.stop.is_set():break
                inserted=self.store.upsert_frame(frame,symbol=symbol,provider='ALPACA',feed=self.config.feed,only_missing=True) if not frame.empty else 0
                remaining=missing_reference_windows(self.store.database_path,symbol,self.config.feed,now)
                results[symbol]=dict(status='REPAIRED' if not remaining else 'PROVIDER_GAPS_REMAIN',inserted=inserted,remaining_periods=len(remaining))
            except HTTPError as error:
                retry=error.headers.get('Retry-After','')
                try:self.retry_after=max(300,int(retry))
                except (TypeError,ValueError):
                    try:self.retry_after=max(300,(parsedate_to_datetime(retry)-datetime.now(UTC)).total_seconds())
                    except (TypeError,ValueError,OverflowError):pass
                results[symbol]=dict(status='HTTP_ERROR',http_status=error.code)
                self.cursor=index
                if error.code==429:break
            except Exception as error:
                results[symbol]=dict(status='UNAVAILABLE',error_type=type(error).__name__)
        return dict(checked_utc=now.isoformat(),feed=self.config.feed,requests=requests,symbols=results,signals_evaluated=0,messages_sent=0)

    def run(self):
        path=Path(self.store.database_path).resolve().parent/'trade_review/ingest_runtime/reference_recovery.json'
        while not self.stop.is_set():
            result=self.sweep()
            try:
                path.parent.mkdir(parents=True,exist_ok=True)
                temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result),encoding='utf-8');temporary.replace(path)
            except OSError:pass
            self.stop.wait(self.retry_after)

    def start(self):
        self.thread=Thread(target=self.run,name='reference-recovery',daemon=True);self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=5)
