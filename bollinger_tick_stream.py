"""One Alpaca connection; fast trade geometry independent of bar analysis.

No broker orders. Prices follow Alpaca close-eligible sale conditions. The
minute history stays canonical; an intraminute observation never overwrites it.
"""
from collections import OrderedDict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import hashlib
import math
import os
from pathlib import Path
from queue import Empty, Full, Queue
import sqlite3
from threading import Event, Thread, Lock
import time
from zoneinfo import ZoneInfo

import pandas as pd

from alpaca_market_data import AlpacaStockBarStream
from bollinger_phone_worker import bands_at_open, detect_values, STRATEGY_VERSION
from bollinger_expansion import MINIMUM_BAND_EXPANSION_PCT, expansion_evidence
from market_calendar import MarketSessionRepository
from market_store import MarketBarStore
from bollinger_reference_scope import (REGULAR, active_reference_scope, required_periods)

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
MAX_TRADE_AGE = timedelta(seconds=3)
MAX_PENDING_AUDIT = 8192
ROUTINE_FLUSH_SECONDS = .5


def sqlite_busy(error):
    code = getattr(error, 'sqlite_errorcode', None)
    return isinstance(code, int) and code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def record_ingest_revision(database):
    """Fixed local receipt proving which implementation a worker loaded."""
    path = Path(database).resolve().parent/'trade_review/ingest_runtime/loaded.json'
    temporary = path.with_suffix('.'+str(os.getpid())+'.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({'utc': datetime.now(UTC).isoformat(),
            'pid': os.getpid(), 'revision': 'sqlite_wal_publisher_v5',
            'timing_revision': 'ingest_stage_timing_v1',
            'bar_storage_revision': 'ordered_async_bar_storage_v1',
            'reference_scope_fence_revision': 'scoped_pending_references_v1',
            'strategy_version': STRATEGY_VERSION,
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'minimum_band_expansion_pct': MINIMUM_BAND_EXPANSION_PCT,
            'expansion_source_sha256': hashlib.sha256(Path(__file__).with_name('bollinger_expansion.py').read_bytes()).hexdigest(),
            'detector_source_sha256': hashlib.sha256(Path(__file__).with_name('bollinger_phone_worker.py').read_bytes()).hexdigest(),
            'sqlite_version': sqlite3.sqlite_version}), encoding='utf-8')
        temporary.replace(path)
    except OSError:
        pass  # Receipt contention must not stop market reception.


def ingest_timing_snapshot(worker):
    """Safe stage counters, no payloads, account data or exception bodies."""
    stage, entered = worker.active_stage
    return dict(utc=datetime.now(UTC).isoformat(), pid=os.getpid(),
        revision='ingest_stage_timing_v1', stage=stage,
        stage_seconds=max(0., time.monotonic()-entered),
        queue_depth=worker.queue.qsize(), analysis_depth=worker.analysis.qsize(),
        state=worker.state, failed=worker.failed.is_set(),
        max_seconds=dict(worker.max_stage_seconds),
        last_trade_queue_seconds=worker.last_trade_queue_seconds,
        bar_storage_revision='ordered_async_bar_storage_v1',
        persistence_depth=worker.persistence.qsize(),
        persistence_stage=worker.persistence_stage[0],
        persistence_stage_seconds=max(0.,time.monotonic()-worker.persistence_stage[1]))


def record_ingest_failure(database, stage, error):
    """Allowlisted failure metadata; never raw exceptions, trades or credentials."""
    result = {'utc': datetime.now(UTC).isoformat(), 'pid': os.getpid(),
              'stage': stage, 'error_type': type(error).__name__}
    code = getattr(error, 'sqlite_errorcode', None)
    if isinstance(code, int):
        result['sqlite_errorcode'] = code
    path = Path(database).resolve().parent/'fast_ingest_failure.json'
    temporary = path.with_suffix('.'+str(os.getpid())+'.tmp')
    try:
        temporary.write_text(json.dumps(result), encoding='utf-8')
        temporary.replace(path)
    except OSError:
        pass

# Alpaca's Stock Minute Bars article: exclusions from open/close price.
EXCLUDED_CONDITIONS = frozenset('479CGHIMNPQRTUVZ')
REGULAR_MODIFIERS = frozenset(('@', ' ', 'F', 'E', 'X', 'Y', 'L', 'O', '5', '6'))


def eligible_trade(message):
    """Reject unknown conditions as well as known non-price-forming sales."""
    try:
        price, size = float(message['p']), float(message['s'])
        conditions = message['c']
        tape = message['z']
        if not isinstance(conditions, list) or tape not in ('A', 'B', 'C'):
            return False
        excluded = EXCLUDED_CONDITIONS | ({'B'} if tape in ('A', 'B') else {'W'})
        return (math.isfinite(price) and price > 0 and math.isfinite(size) and size > 0
                and all(c not in excluded and c in REGULAR_MODIFIERS for c in conditions))
    except (KeyError, TypeError, ValueError):
        return False


class TickRepository:
    def __init__(self, database):
        from sqlite_runtime_guard import require_safe_wal_runtime
        require_safe_wal_runtime(database)
        self.database = str(database)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bollinger_tick_latest (
                    symbol TEXT PRIMARY KEY, source_timestamp TEXT NOT NULL,
                    received_at TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bollinger_tick_runtime (
                    id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL,
                    heartbeat TEXT NOT NULL, feed TEXT NOT NULL, symbols_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bollinger_tick_audit (
                    id INTEGER PRIMARY KEY, received_at TEXT NOT NULL,
                    symbol TEXT, source_timestamp TEXT, reason TEXT NOT NULL,
                    message_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_bollinger_tick_audit_time
                    ON bollinger_tick_audit(received_at);
            ''')
            # Rolling, private raw evidence; cap time retention on each restart.
            db.execute('DELETE FROM bollinger_tick_audit WHERE received_at < ?',
                       ((datetime.now(UTC)-timedelta(days=7)).isoformat(),))

    def connect(self, *, timeout=5):
        # Explicit close, including Windows test cleanup.
        from contextlib import contextmanager
        @contextmanager
        def opened():
            db = sqlite3.connect(self.database, timeout=timeout)
            try:
                with db:
                    yield db
            finally:
                db.close()
        return opened()

    def flush(self, snapshots, audit, *, state, feed, symbols, now, connection=None):
        transaction = self.connect(timeout=.025) if connection is None else connection
        with transaction as db:
            db.execute('INSERT INTO bollinger_tick_runtime VALUES(1,?,?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET state=excluded.state,heartbeat=excluded.heartbeat,'
                       'feed=excluded.feed,symbols_json=excluded.symbols_json',
                       (state, now.isoformat(), feed, json.dumps(list(symbols))))
            db.executemany('INSERT INTO bollinger_tick_latest VALUES(?,?,?,?) '
                          'ON CONFLICT(symbol) DO UPDATE SET source_timestamp=excluded.source_timestamp,'
                          'received_at=excluded.received_at,payload_json=excluded.payload_json',
                          [(symbol, p['source_timestamp'], p['received_at'], json.dumps(p))
                           for symbol, p in snapshots.items()])
            db.executemany('INSERT INTO bollinger_tick_audit '
                          '(received_at,symbol,source_timestamp,reason,message_json) VALUES(?,?,?,?,?)', audit)


class TickGeometry:
    """O(20) geometry per eligible trade; history loads only on candle changes."""
    def __init__(self, database, feed, *, now=None, reference_scope=None):
        self.database, self.feed = database, feed
        self.reference_scope = reference_scope or active_reference_scope()
        self.now = now or (lambda: datetime.now(UTC))
        self.store = MarketBarStore(database)
        self.calendar = MarketSessionRepository(database)
        self.connected_at = None
        self.states = {}
        self.quarantines = {}
        self.seen = OrderedDict()
        self.missed_openings = set()
        self.session_key = self.session = None
        self.reference_windows = {}

    def bar_affects_reference(self,bar,candle):
        if bar.timestamp==candle:return True
        if bar.timestamp>candle:return False
        windows=self.reference_windows.get(candle)
        if windows is not None:
            return any(start<=bar.timestamp<end for start,end in windows)
        # At the regular opening, the last premarket minute is not one of
        # the required prior regular periods. Do not fence it as if it were.
        session=self.session
        if (self.reference_scope==REGULAR and session is not None and
            bar.timestamp.astimezone(NY).date()==session.opens_at.astimezone(NY).date()):
            return session.opens_at<=bar.timestamp<min(candle,session.closes_at)
        return True  # Unknown scope/calendar cannot authorize old references.

    def status(self, state, now):
        self.connected_at = now if state == 'CONECTADO' else None
        self.states.clear()

    def _history(self, symbol, candle, now):
        # Only the last close of each required official period contributes to
        # Bollinger. Avoid normalizing/resampling seven days of minute rows on
        # the shared trade thread whenever a symbol starts a new candle.
        uri = Path(self.database).resolve().as_uri()+'?mode=ro'
        started = time.monotonic()
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: time.monotonic()-started > 2, 1000)
            sessions = db.execute(
                'SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? '
                'AND session_date<=? ORDER BY session_date',
                ((candle.astimezone(NY).date()-timedelta(days=7)).isoformat(),
                 candle.astimezone(NY).date().isoformat()),
            ).fetchall()
            required = required_periods(sessions, candle, scope=self.reference_scope)
            if not required:
                return None
            self.reference_windows[candle]=tuple(required)
            if len(self.reference_windows)>64:
                self.reference_windows.pop(next(iter(self.reference_windows)))
            previous_start = required[-1][0]
            if candle > self.session.opens_at and previous_start != candle-timedelta(minutes=15):
                return None
            if self.reference_scope == REGULAR and candle == self.session.opens_at:
                row = db.execute('SELECT MAX(session_date) FROM market_sessions WHERE session_date < ?',
                                 (candle.astimezone(NY).date().isoformat(),)).fetchone()
                if not row or row[0] != previous_start.astimezone(NY).date().isoformat():
                    return None
            closes = []
            for period, end in required:
                # Indexed seeks release only twenty prices, never substitute
                # an older period when this one has no official minute bars.
                row = db.execute('SELECT timestamp,close FROM minute_bars '
                    'WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? AND timestamp<=? '
                    'ORDER BY timestamp DESC LIMIT 1',
                    ('ALPACA', self.feed, symbol, period.isoformat(),
                     (end-timedelta(minutes=1)).isoformat())).fetchone()
                if row is None:
                    return None
                if period == previous_start and pd.Timestamp(row[0]) != pd.Timestamp(end-timedelta(minutes=1)):
                    return None
                closes.append(float(row[1]))
        return closes

    def observe(self, message, received, *, references_pending=False):
        symbol = str(message.get('S', '')).upper()
        now = self.now()
        if message.get('T') in ('c', 'x'):
            # Corrections are evidence, never a new trade. Quarantine the
            # affected current candle rather than inventing a corrected path.
            if symbol in self.states:
                self.states[symbol]['quarantined'] = True
            self.quarantines[symbol] = now
            return None, 'CORRECTION_QUARANTINE'
        try:
            stamp = datetime.fromisoformat(message['t'].replace('Z', '+00:00')).astimezone(UTC)
            if not eligible_trade(message):
                return None, 'EXCLUDED_CONDITION'
            if now-stamp > MAX_TRADE_AGE:
                local=stamp.astimezone(NY)
                uncertain=local.replace(minute=(local.minute//15)*15,second=0,microsecond=0).astimezone(UTC)
                self.missed_openings.add((symbol,uncertain))
                if len(self.missed_openings)>2048:
                    self.missed_openings={(symbol,uncertain)}
            if self.connected_at is None or not timedelta(0) <= now-stamp <= MAX_TRADE_AGE:
                return None, 'DISCONNECTED_OR_STALE'
            if not timedelta(0) <= received-stamp <= MAX_TRADE_AGE:
                return None, 'STALE_AT_RECEIPT'
            if stamp.astimezone(NY).date() != self.session_key:
                self.session_key = stamp.astimezone(NY).date()
                self.session = self.calendar.session(self.session_key)
            if self.session is None or not self.session.opens_at <= stamp < self.session.closes_at:
                return None, 'OUTSIDE_SESSION'
            identity = (symbol, message.get('x'), str(message['i']), stamp.date())
            if identity in self.seen:
                return None, 'DUPLICATE'
            self.seen[identity] = True
            if len(self.seen) > 10000:
                self.seen.popitem(last=False)
            candle = self.session.opens_at + timedelta(minutes=15*int((stamp-self.session.opens_at).total_seconds()//900))
            state = self.states.get(symbol)
            if state and candle < state['candle']:
                return None, 'OUT_OF_ORDER'
            if not state or state['candle'] != candle:
                state = self.states[symbol] = {'candle': candle, 'opening': None,
                    'last': None, 'history': None, 'retry_at': now, 'open_retry_at':now,
                    'quarantined': self.quarantines.get(symbol, candle-timedelta(seconds=1)) >= candle}
                # Only a stream already connected before the candle began
                # can use its first eligible trade as the opening.
                if self.connected_at <= candle and stamp >= self.connected_at and (symbol,candle) not in self.missed_openings:
                    state['opening'] = float(message['p'])
                    state['opening_stamp'] = stamp
            if state.get('opening_stamp') is not None and stamp < state['opening_stamp']:
                state['opening']=None
                state['opening_stamp']=None
                self.missed_openings.add((symbol,candle))
                return {'symbol':symbol,'provider':'ALPACA','feed':self.feed,'source_kind':'TRADE',
                        'source_timestamp':received.isoformat(),'received_at':received.isoformat(),
                        'signal':None,'reason':'OPENING_OUT_OF_ORDER'}, 'OPENING_OUT_OF_ORDER'
            if state['last'] is not None and stamp < state['last']:
                return None, 'OUT_OF_ORDER'
            state['last'] = stamp
            if not references_pending and state['history'] is None and now >= state['retry_at']:
                state['history'] = self._history(symbol, candle, now)
                state['retry_at'] = now+timedelta(seconds=1)
            if not references_pending and state['opening'] is None and now >= state['open_retry_at']:
                # Mid-candle startup/reconnection: recover the real opening
                # from the completed FIRST minute, never the first price seen.
                first = self.store.load_frame(symbol=symbol, provider='ALPACA', feed=self.feed,
                                             start=candle, end=candle)
                if now >= candle+timedelta(minutes=1) and not first.empty:
                    state['opening'] = float(first.iloc[0].open)
                state['open_retry_at'] = now+timedelta(seconds=1)
            signal = None
            geometry = None
            price = float(message['p'])
            reason = 'READY_NO_EXIT'
            if state['quarantined']:
                reason = 'CORRECTION_QUARANTINE'
            elif references_pending:
                reason = 'WAITING_FOR_REFERENCE_STORAGE'
            elif state['opening'] is None or state['history'] is None:
                reason = 'WAITING_FOR_OPEN_OR_HISTORY'
            else:
                prior = state['history']
                prev_upper, prev_lower = bands_at_open(prior[:-1], prior[-1])
                upper, lower = bands_at_open(prior[1:], price)
                initial_upper, initial_lower = bands_at_open(prior[1:], state['opening'])
                side = detect_values(prior[-1], prev_upper, prev_lower, sum(prior)/20,
                    price, upper, lower, (sum(prior[1:])+price)/20,
                    opening=state['opening'])
                geometry = {'upper': upper, 'lower': lower,
                    'previous_upper': prev_upper, 'previous_lower': prev_lower,
                    'mid': (sum(prior[1:])+price)/20, 'previous_mid': sum(prior)/20,
                    'opening_upper': upper, 'opening_lower': lower,
                    'initial_opening_upper': initial_upper, 'initial_opening_lower': initial_lower,
                    'opening_reference': 'CURRENT_BANDS',
                    'opening': state['opening'], 'price': price, 'side': side}
                if side:
                    exposure = (price-upper if side == 'SUPERIOR' else lower-price)/(upper-lower)*100
                    signal = {'side': side, 'price': price, 'candle': candle.isoformat(),
                              'band_expansion': expansion_evidence(upper, lower, prev_upper, prev_lower),
                              'exposure_pct_bandwidth': exposure, 'small_exposure': exposure < 1}
                    reason = 'EXIT'
            # History/SQLite work can consume time after the first age check.
            # Never publish an EXIT that became stale during that work.
            checked = self.now()
            if not timedelta(0) <= checked-stamp <= MAX_TRADE_AGE:
                return None, 'DISCONNECTED_OR_STALE'
            return {'symbol': symbol, 'provider': 'ALPACA', 'feed': self.feed,
                    'source_kind': 'TRADE', 'source_timestamp': stamp.isoformat(),
                    'received_at': received.isoformat(), 'checked_at': checked.isoformat(),
                    'opening': state['opening'], 'version': STRATEGY_VERSION,
                    'reference_scope': self.reference_scope,
                    'trade_id': message['i'], 'trade_timestamp_raw': message['t'],
                    'signal': signal, 'reason': reason, 'geometry': geometry}, reason
        except (KeyError, ValueError, TypeError, OverflowError):
            return None, 'INVALID_TRADE'


class TickPublisher:
    """Single bounded writer. Disk commit latency cannot hold trade evaluation.

    Each retry preserves every audit and the newest projection per symbol.
    Heartbeat timestamps come from the evaluator, never from writer progress.
    """
    def __init__(self, repository, feed, symbols, failed):
        self.repository,self.feed,self.symbols,self.failed=repository,feed,symbols,failed
        self.lock=Lock();self.wake=Event();self.stopping=Event()
        self.snapshots={};self.audit=[];self.inflight=0
        self.state='DESCONECTADO';self.now=datetime.now(UTC)
        self.fatal_batch=None
        self.thread=Thread(target=self._run,name='tick-publisher',daemon=True)
        self.thread.start()

    def pending(self):
        with self.lock:return len(self.audit)+self.inflight

    def submit(self,snapshots,audit,*,state,now,final=False):
        with self.lock:
            if not final and len(audit)+len(self.audit)+self.inflight>MAX_PENDING_AUDIT:
                raise BufferError('Pending trade audit limit exceeded')
            self.snapshots.update(snapshots);self.audit.extend(audit)
            self.state,self.now=state,now
        self.wake.set()

    def _run(self):
        connection=None
        try:
            connection=sqlite3.connect(self.repository.database,timeout=.025)
            connection.execute('PRAGMA synchronous=FULL')
            self._publish_loop(connection)
        except Exception as error:
            record_ingest_failure(self.repository.database,'TICK_PUBLICATION_FAILED',error)
            self.failed.set()
        finally:
            if connection is not None:connection.close()

    def _publish_loop(self, connection):
        last_prune=time.monotonic()
        batch=None
        while True:
            self.wake.wait(.05)
            if batch is None:
                with self.lock:
                    if not self.wake.is_set():
                        if self.stopping.is_set():return
                        continue
                    self.wake.clear()
                    batch=(self.snapshots,self.audit,self.state,self.now)
                    self.snapshots,self.audit={},[]
                    self.inflight=len(batch[1])
            snapshots,audit,state,now=batch
            try:
                self.repository.flush(snapshots,audit,state=state,feed=self.feed,symbols=self.symbols,now=now,connection=connection)
            except sqlite3.OperationalError as error:
                if sqlite_busy(error):
                    # Merge pending retractions before retrying a rolled-back
                    # batch. An old EXIT must not replace a newer neutral state.
                    with self.lock:
                        snapshots.update(self.snapshots);audit.extend(self.audit)
                        self.snapshots,self.audit={},[]
                        batch=(snapshots,audit,self.state,self.now)
                        self.inflight=len(audit)
                        self.wake.clear()
                    time.sleep(.05)
                    continue
                record_ingest_failure(self.repository.database,'TICK_PUBLICATION_FAILED',error)
                self.failed.set()
                self.fatal_batch=batch
                return
            except Exception as error:
                record_ingest_failure(self.repository.database,'TICK_PUBLICATION_FAILED',error)
                self.failed.set()
                self.fatal_batch=batch
                return
            with self.lock:self.inflight=0
            batch=None
            # Retention is disk maintenance, never work on the trade evaluator.
            if time.monotonic()-last_prune>=60:
                try:
                    with connection as db:
                        db.execute('DELETE FROM bollinger_tick_audit WHERE id IN '
                            '(SELECT id FROM bollinger_tick_audit WHERE id <= '
                            '(SELECT MAX(id)-200000 FROM bollinger_tick_audit) ORDER BY id LIMIT 2000)')
                except sqlite3.OperationalError as error:
                    if not sqlite_busy(error):
                        record_ingest_failure(self.repository.database,'TICK_RETENTION_FAILED',error)
                        self.failed.set()
                last_prune=time.monotonic()

    def close(self):
        self.stopping.set();self.wake.set();self.thread.join(timeout=5)
        if self.thread.is_alive():
            self.failed.set()
            record_ingest_failure(self.repository.database,'TICK_PUBLICATION_SHUTDOWN_TIMEOUT',TimeoutError())


class RealtimeBollingerWorker:
    """Bounded fast ingest plus an independent ordered analysis queue."""
    def __init__(self, database, feed, symbols):
        self.repository = TickRepository(database)
        self.geometry = TickGeometry(database, feed)
        self.feed, self.symbols = feed, tuple(symbols)
        self.queue, self.analysis = Queue(maxsize=4096), Queue(maxsize=2048)
        self.persistence=Queue(maxsize=2048)
        self.pending_bars={};self.bar_sequence=0
        self.persistence_stage=('IDLE',time.monotonic())
        self.finished, self.failed = Event(), Event()
        self.publisher=TickPublisher(self.repository,feed,self.symbols,self.failed)
        self.state = 'DESCONECTADO'
        self.last_error = None
        self.active_stage = ('IDLE', time.monotonic())
        self.max_stage_seconds = {}
        self.last_trade_queue_seconds = None
        self.threads = [Thread(target=self._run, name='bollinger-trades', daemon=True),
                        Thread(target=self._analyze, name='bar-analysis', daemon=True),
                        Thread(target=self._timings, name='ingest-timings', daemon=True),
                        Thread(target=self._persist, name='official-bar-storage', daemon=True)]
        record_ingest_revision(database)
        for thread in self.threads:
            thread.start()

    def offer(self, kind, payload, callback=None):
        if self.failed.is_set():
            raise RuntimeError('El receptor rapido requiere reiniciar tras un error de ingestión.')
        try:
            self.queue.put_nowait((kind, payload, datetime.now(UTC), callback))
        except Full:
            self.failed.set()
            raise RuntimeError('Cola de precios saturada; se detuvo la detección rápida.')

    def status(self, state):
        self.offer('status', state)

    def trade(self, message):
        self.offer('trade', dict(message))

    def bar(self, bar, callback):
        self.offer('bar', bar, callback)

    def _references_pending(self,message):
        pending=self.pending_bars.get(str(message.get('S','')).upper(),{})
        if not pending:return False
        try:
            stamp=datetime.fromisoformat(message['t'].replace('Z','+00:00')).astimezone(UTC)
            candle=stamp.replace(minute=stamp.minute//15*15,second=0,microsecond=0)
            return any(self.geometry.bar_affects_reference(bar,candle) for bar in pending.values())
        except (ValueError,KeyError,TypeError):return False

    def _persist(self):
        # One ordered writer, using the same canonical store. The fast thread
        # keeps consuming trades while storage/SQLite is busy. Affected
        # references stay unavailable until a commit acknowledgment is handled.
        while not self.finished.is_set():
            try:bars=self.persistence.get(timeout=.1)
            except Empty:continue
            try:
                if self.failed.is_set():continue
                self.persistence_stage=('BAR_PERSIST',time.monotonic())
                self.geometry.store.upsert_bars([b for _,b,_,_ in bars],provider='ALPACA',feed=self.feed)
                if not self.finished.is_set():self.offer('bars_committed',bars)
            except Exception as error:
                self.last_error='BAR_STORAGE_FAILED';self.failed.set()
                record_ingest_failure(self.repository.database,self.last_error,error)
            finally:
                self.persistence_stage=('IDLE',time.monotonic())
                self.persistence.task_done()

    def _timings(self):
        # Optional filesystem work has its own thread. It never holds a trade
        # lock, touches SQLite, retries orders or creates a market connection.
        path = Path(self.repository.database).resolve().parent/'trade_review/ingest_runtime/timing.json'
        temporary = path.with_suffix('.'+str(os.getpid())+'.tmp')
        while not self.finished.is_set():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(json.dumps(ingest_timing_snapshot(self)), encoding='utf-8')
                temporary.replace(path)
            except (OSError, RuntimeError):
                pass
            self.finished.wait(5)

    def _analyze(self):
        while not self.finished.is_set():
            try:
                callback, bar = self.analysis.get(timeout=.1)
            except Empty:
                continue
            try:
                callback(bar)
            except Exception as error:
                # Existing handle_bar records its own incidents. An unexpected
                # callback failure must still make this worker unhealthy.
                self.last_error = 'BAR_ANALYSIS_FAILED'
                record_ingest_failure(self.repository.database, self.last_error, error)
                self.failed.set()
            finally:
                self.analysis.task_done()

    def _run(self):
        snapshots, audit = {}, []
        patterns = {}
        urgent = False
        last_flush = time.monotonic()
        deferred = None
        while not self.finished.is_set():
            try:
                if deferred is None:
                    kind, payload, received, callback = self.queue.get(timeout=.05)
                else:
                    kind, payload, received, callback = deferred
                    deferred = None
            except Empty:
                kind = None
            completed = 1 if kind is not None else 0
            event_started = time.monotonic()
            self.active_stage = (kind.upper() if kind else 'IDLE', event_started)
            try:
                if self.failed.is_set():
                    self.state = 'ERROR'
                    self.geometry.status('ERROR', datetime.now(UTC))
                    snapshots.clear()
                    patterns.clear()
                    urgent = True
                elif kind == 'status':
                    self.state = payload
                    self.geometry.status(payload, received)
                    snapshots.clear()
                    patterns.clear()
                    urgent = True
                elif kind == 'bar':
                    bars = [(payload, received, callback)]
                    # Coalesce only adjacent bars already queued. Never cross a
                    # trade/status/correction or add a collection delay.
                    while len(bars) < 64:
                        try:
                            item = self.queue.get_nowait()
                        except Empty:
                            break
                        if item[0] != 'bar':
                            deferred = item
                            break
                        bars.append((item[1], item[2], item[3]))
                        completed += 1
                    pending=[]
                    for bar,bar_received,bar_callback in bars:
                        self.bar_sequence+=1;token=self.bar_sequence
                        self.pending_bars.setdefault(bar.symbol,{})[token]=bar
                        pending.append((token,bar,bar_received,bar_callback))
                        state=self.geometry.states.get(bar.symbol)
                        if state and self.geometry.bar_affects_reference(bar,state['candle']):
                            snapshots[bar.symbol]={'symbol':bar.symbol,'provider':'ALPACA','feed':self.feed,
                                'source_kind':'TRADE','source_timestamp':bar_received.isoformat(),
                                'received_at':bar_received.isoformat(),'signal':None,
                                'reason':'WAITING_FOR_REFERENCE_STORAGE'}
                            patterns.pop(bar.symbol,None);urgent=True
                    self.persistence.put_nowait(pending)
                elif kind == 'bars_committed':
                    self.active_stage = ('BAR_REFERENCE_UPDATE', time.monotonic())
                    for token,bar,bar_received,bar_callback in payload:
                        pending=self.pending_bars.get(bar.symbol,{})
                        pending.pop(token,None)
                        if not pending:self.pending_bars.pop(bar.symbol,None)
                        state=self.geometry.states.get(bar.symbol)
                        if state and self.geometry.bar_affects_reference(bar,state['candle']):
                            if bar.timestamp < state['candle']:
                                state['history']=None
                                state['retry_at']=datetime.now(UTC)
                            elif bar.timestamp == state['candle']:
                                state['opening']=bar.open
                                state['opening_stamp']=None
                            snapshots[bar.symbol]={'symbol':bar.symbol,'provider':'ALPACA','feed':self.feed,
                                'source_kind':'TRADE','source_timestamp':bar_received.isoformat(),
                                'received_at':bar_received.isoformat(),'signal':None,'reason':'REFERENCE_UPDATED'}
                            if patterns.pop(bar.symbol, None) is not None:
                                urgent = True
                        self.analysis.put_nowait((bar_callback, bar))
                elif kind == 'trade':
                    processing_started = datetime.now(UTC)
                    self.last_trade_queue_seconds = (processing_started-received).total_seconds()
                    self.active_stage = ('TRADE_GEOMETRY', time.monotonic())
                    snapshot, reason = self.geometry.observe(payload, received,
                        references_pending=self._references_pending(payload))
                    symbol = str(payload.get('S', '')).upper()
                    if snapshot:
                        snapshots[symbol] = snapshot
                        signal = snapshot.get('signal')
                        identity = (signal.get('side'), signal.get('candle')) if signal else None
                        if identity != patterns.get(symbol):
                            urgent = True
                        patterns[symbol] = identity
                    elif payload.get('T') in ('c', 'x'):
                        snapshots[symbol] = {'symbol': symbol, 'provider': 'ALPACA', 'feed': self.feed,
                            'source_kind': 'TRADE', 'source_timestamp': received.isoformat(),
                            'received_at': received.isoformat(), 'signal': None, 'reason': reason}
                        patterns.pop(symbol, None)
                        urgent = True
                    evidence = dict(payload)
                    evidence['_jjtrade'] = {'processing_started_at': processing_started.isoformat(),
                        'processed_at': datetime.now(UTC).isoformat(),
                        'connected': self.geometry.connected_at is not None,
                        'geometry': snapshot.get('geometry') if snapshot else None}
                    audit.append((received.isoformat(), symbol, payload.get('t'), reason, json.dumps(evidence)))
                if len(audit)+self.publisher.pending() > MAX_PENDING_AUDIT:
                    raise BufferError('Pending trade audit limit exceeded')
                flush_at = time.monotonic()
                if urgent or flush_at-last_flush >= ROUTINE_FLUSH_SECONDS or len(audit) >= 200:
                    self.publisher.submit(snapshots,audit,state=self.state,now=datetime.now(UTC))
                    snapshots,audit={},[]
                    urgent=False
                    last_flush=time.monotonic()
            except Exception as error:
                self.last_error = 'FAST_INGEST_FAILED'
                if not self.failed.is_set():
                    record_ingest_failure(self.repository.database, self.last_error, error)
                self.failed.set()
            finally:
                if kind:
                    self.max_stage_seconds[kind] = max(self.max_stage_seconds.get(kind, 0.),
                                                       time.monotonic()-event_started)
                self.active_stage = ('IDLE', time.monotonic())
                for _ in range(completed):
                    self.queue.task_done()
        self.publisher.submit({},audit,state='DETENIDO',now=datetime.now(UTC),final=True)

    def close(self):
        self.finished.set()
        for thread in self.threads:
            thread.join(timeout=5)
        self.publisher.close()


class RealtimeBollingerStream:
    """Supervisor-compatible single stream with trade and bar subscriptions."""
    def __init__(self, config, worker):
        self.worker = worker
        self.stream = AlpacaStockBarStream(config, on_trade_message=worker.trade)

    def run(self, symbols, on_bar, *, on_error=None, on_status=None):
        from bollinger_reference_recovery import ReferenceRecovery
        recovery=ReferenceRecovery(self.stream.config,self.worker.geometry.store,symbols)
        def status(state):
            self.worker.status(state)
            if on_status:
                on_status(state)

        def error(failure):
            if not self.worker.failed.is_set():
                status('DESCONECTADO')
            if on_error:
                on_error(failure)
        try:
            recovery.start()
            self.stream.run(symbols, lambda bar: self.worker.bar(bar, on_bar),
                            on_error=error, on_status=status)
        finally:
            recovery.close()
            if not self.worker.failed.is_set():
                status('DESCONECTADO')

    def stop(self):
        self.stream.stop()
