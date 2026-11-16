"""Bounded asynchronous evidence from existing quotes; no broker interface or authority."""
from collections import OrderedDict
from datetime import datetime,timezone
from pathlib import Path
from queue import Queue,Empty
from threading import Event,Thread,Lock
import json,sqlite3,math

REVISION=1
def finite(value):
    if isinstance(value,bool):return None
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):return None

DEFAULT_PATH=Path(__file__).resolve().parent/'exports/trade_review/option_evidence/quotes.sqlite3'

class OptionEvidenceRecorder:
    def __init__(self,path=DEFAULT_PATH,*,capacity=128,clock=lambda:datetime.now(timezone.utc)):
        self.path=Path(path);self.clock=clock;self.queue=Queue(maxsize=capacity)
        self.stop_event=Event();self.thread=None;self._lock=Lock()
        self._state=dict(revision=REVISION,state='NOT_STARTED',counter_scope='CURRENT_PROCESS',accepted=0,written=0,dropped=0,duplicates=0)

    def status(self):
        with self._lock:return dict(self._state,queued=self.queue.qsize())

    def _count(self,key,n=1):
        with self._lock:self._state[key]+=n

    def start(self):
        if self.thread is not None:return
        self.thread=Thread(target=self._run,name='JJTrade-option-evidence',daemon=True);self.thread.start()

    def publish(self,contracts,*,phase,symbol,signal_key=None,spot=None):
        """Memory queue only. Failures never affect trading or launch an HTTP request."""
        try:
            if self.status()['state']=='UNAVAILABLE':raise ValueError('UNAVAILABLE')
            if phase not in ('ENTRY_CANDIDATE','POSITION_QUOTE'):raise ValueError('PHASE')
            packet=(self.clock().isoformat(),phase,symbol,signal_key,spot,tuple(c.snapshot for c in contracts))
            self.queue.put_nowait(packet);self._count('accepted');return True
        except Exception:
            self._count('dropped');return False

    def _run(self):
        seen=OrderedDict();reported_drops=0;db=None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            db=sqlite3.connect(self.path,timeout=.05)
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY,observed_at TEXT NOT NULL,phase TEXT NOT NULL,symbol TEXT NOT NULL,contract TEXT NOT NULL,quote_at TEXT,payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS contract_quote_time ON quotes(contract,quote_at)')
            db.execute('CREATE TABLE IF NOT EXISTS gaps(at TEXT,packets INTEGER,reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS observer_status(id INTEGER PRIMARY KEY,heartbeat TEXT,payload TEXT)');db.commit()
            with self._lock:self._state['state']='CURRENT'
            while not self.stop_event.is_set() or not self.queue.empty():
                try:packet=self.queue.get(timeout=.2)
                except Empty:continue
                packets=[packet]
                while len(packets)<16:
                    try:packets.append(self.queue.get_nowait())
                    except Empty:break
                records=[]
                for observed,phase,symbol,key,spot,snapshots in packets:
                    for q in snapshots:
                        payload=dict(signal_key=key,underlying_price=finite(spot),option_type=q.option_type,strike=q.strike,
                            expiration=q.expiration.isoformat(),bid=q.bid,ask=q.ask,bid_size=q.bid_size,ask_size=q.ask_size,
                            delta=finite(q.delta),gamma=finite(q.gamma),theta=finite(q.theta),vega=finite(q.vega),implied_volatility=finite(q.implied_volatility),
                            feed=q.feed,multiplier=100,source='EXISTING_SCHWAB_READ_NO_ADDITIONAL_REQUEST')
                        quote_at=q.quote_timestamp.isoformat() if q.quote_timestamp else None
                        fingerprint=json.dumps([quote_at,payload],sort_keys=True,allow_nan=False)
                        identity=(phase,q.symbol,key)
                        if seen.get(identity)==fingerprint:
                            self._count('duplicates');continue
                        seen[identity]=fingerprint;seen.move_to_end(identity)
                        if len(seen)>1024:seen.popitem(last=False)
                        records.append((observed,phase,symbol,q.symbol,quote_at,json.dumps(payload,allow_nan=False)))
                try:
                    db.executemany('INSERT INTO quotes(observed_at,phase,symbol,contract,quote_at,payload) VALUES(?,?,?,?,?,?)',records)
                    state=self.status();drops=state['dropped'];state['written']+=len(records)
                    if drops>reported_drops:db.execute('INSERT INTO gaps VALUES(?,?,?)',(self.clock().isoformat(),drops-reported_drops,'DROPPED_OBSERVATION_PACKETS'))
                    db.execute('INSERT OR REPLACE INTO observer_status VALUES(1,?,?)',(self.clock().isoformat(),json.dumps(state)))
                    db.commit();reported_drops=drops;self._count('written',len(records))
                except sqlite3.Error:
                    db.rollback();self._count('dropped',len(packets));seen.clear()
                for _ in packets:self.queue.task_done()
            db.close()
            with self._lock:self._state['state']='STOPPED'
        except Exception:
            with self._lock:self._state['state']='UNAVAILABLE'
        finally:
            if db is not None:db.close()

    def stop(self,timeout=2):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout)
