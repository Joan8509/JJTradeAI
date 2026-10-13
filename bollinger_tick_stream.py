"""One Alpaca connection; fast trade geometry independent of bar analysis.

No broker orders. Prices follow Alpaca close-eligible sale conditions. The
minute history stays canonical; an intraminute observation never overwrites it.
"""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import math
from queue import Empty, Full, Queue
import sqlite3
from threading import Event, Thread
import time
from zoneinfo import ZoneInfo

import pandas as pd

from alpaca_market_data import AlpacaStockBarStream
from bollinger_phone_worker import bands_at_open, detect_values, STRATEGY_VERSION
from live_market import aggregate_minute_bars
from market_calendar import MarketSessionRepository
from market_store import MarketBarStore

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
MAX_TRADE_AGE = timedelta(seconds=3)
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

    def connect(self):
        # Explicit close, including Windows test cleanup.
        from contextlib import contextmanager
        @contextmanager
        def opened():
            db = sqlite3.connect(self.database, timeout=5)
            try:
                with db:
                    yield db
            finally:
                db.close()
        return opened()

    def flush(self, snapshots, audit, *, state, feed, symbols, now):
        with self.connect() as db:
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
    def __init__(self, database, feed, *, now=None):
        self.database, self.feed = database, feed
        self.now = now or (lambda: datetime.now(UTC))
        self.store = MarketBarStore(database)
        self.calendar = MarketSessionRepository(database)
        self.connected_at = None
        self.states = {}
        self.quarantines = {}
        self.seen = OrderedDict()
        self.missed_openings = set()
        self.session_key = self.session = None

    def status(self, state, now):
        self.connected_at = now if state == 'CONECTADO' else None
        self.states.clear()

    def _history(self, symbol, candle, now):
        bars = self.store.load_frame(symbol=symbol, provider='ALPACA', feed=self.feed,
                                    start=candle-timedelta(days=7), end=candle-timedelta(minutes=1))
        if bars.empty:
            return None
        closed = aggregate_minute_bars(bars, '15m')
        closed = closed[closed.date < pd.Timestamp(candle)].tail(20)
        if len(closed) != 20:
            return None
        # Require the last official closing minute. A delayed prior candle
        # must not be used as a completed Bollinger reference.
        previous_start = closed.iloc[-1].date.to_pydatetime()
        previous_session = self.calendar.session(previous_start.astimezone(NY).date())
        if previous_session is None:
            return None
        expected = min(previous_start+timedelta(minutes=15), previous_session.closes_at)-timedelta(minutes=1)
        if pd.Timestamp(expected) not in set(pd.to_datetime(bars.date, utc=True)):
            return None
        if candle > self.session.opens_at and previous_start != candle-timedelta(minutes=15):
            return None
        # At the session open require the previous *official* session, not an
        # arbitrary older day with available data.
        if candle == self.session.opens_at:
            with sqlite3.connect(self.database) as db:
                row = db.execute('SELECT MAX(session_date) FROM market_sessions WHERE session_date < ?',
                                 (candle.astimezone(NY).date().isoformat(),)).fetchone()
            db.close()
            if not row or row[0] != previous_start.astimezone(NY).date().isoformat():
                return None
        return closed.close.astype(float).tolist()

    def observe(self, message, received):
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
            if state['history'] is None and now >= state['retry_at']:
                state['history'] = self._history(symbol, candle, now)
                state['retry_at'] = now+timedelta(seconds=1)
            if state['opening'] is None and now >= state['open_retry_at']:
                # Mid-candle startup/reconnection: recover the real opening
                # from the completed FIRST minute, never the first price seen.
                first = self.store.load_frame(symbol=symbol, provider='ALPACA', feed=self.feed,
                                             start=candle, end=candle)
                if now >= candle+timedelta(minutes=1) and not first.empty:
                    state['opening'] = float(first.iloc[0].open)
                state['open_retry_at'] = now+timedelta(seconds=1)
            signal = None
            price = float(message['p'])
            reason = 'READY_NO_EXIT'
            if state['quarantined']:
                reason = 'CORRECTION_QUARANTINE'
            elif state['opening'] is None or state['history'] is None:
                reason = 'WAITING_FOR_OPEN_OR_HISTORY'
            else:
                prior = state['history']
                prev_upper, prev_lower = bands_at_open(prior[:-1], prior[-1])
                upper, lower = bands_at_open(prior[1:], price)
                opening_upper, opening_lower = bands_at_open(prior[1:], state['opening'])
                side = detect_values(prior[-1], prev_upper, prev_lower, sum(prior)/20,
                    price, upper, lower, (sum(prior[1:])+price)/20,
                    opening=state['opening'], opening_upper=opening_upper, opening_lower=opening_lower)
                if side:
                    exposure = (price-upper if side == 'SUPERIOR' else lower-price)/(upper-lower)*100
                    signal = {'side': side, 'price': price, 'candle': candle.isoformat(),
                              'exposure_pct_bandwidth': exposure, 'small_exposure': exposure < 1}
                    reason = 'EXIT'
            return {'symbol': symbol, 'provider': 'ALPACA', 'feed': self.feed,
                    'source_kind': 'TRADE', 'source_timestamp': stamp.isoformat(),
                    'received_at': received.isoformat(), 'checked_at': now.isoformat(),
                    'opening': state['opening'], 'version': STRATEGY_VERSION,
                    'trade_id': message['i'], 'trade_timestamp_raw': message['t'],
                    'signal': signal, 'reason': reason}, reason
        except (KeyError, ValueError, TypeError, OverflowError):
            return None, 'INVALID_TRADE'


class RealtimeBollingerWorker:
    """Bounded fast ingest plus an independent ordered analysis queue."""
    def __init__(self, database, feed, symbols):
        self.repository = TickRepository(database)
        self.geometry = TickGeometry(database, feed)
        self.feed, self.symbols = feed, tuple(symbols)
        self.queue, self.analysis = Queue(maxsize=4096), Queue(maxsize=2048)
        self.finished, self.failed = Event(), Event()
        self.state = 'DESCONECTADO'
        self.last_error = None
        self.threads = [Thread(target=self._run, name='bollinger-trades', daemon=True),
                        Thread(target=self._analyze, name='bar-analysis', daemon=True)]
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

    def _analyze(self):
        while not self.finished.is_set():
            try:
                callback, bar = self.analysis.get(timeout=.1)
            except Empty:
                continue
            try:
                callback(bar)
            except Exception:
                # Existing handle_bar records its own incidents. An unexpected
                # callback failure must still make this worker unhealthy.
                self.last_error = 'BAR_ANALYSIS_FAILED'
                self.failed.set()
            finally:
                self.analysis.task_done()

    def _run(self):
        snapshots, audit = {}, []
        last_flush = time.monotonic()
        last_prune = last_flush
        while not self.finished.is_set():
            try:
                kind, payload, received, callback = self.queue.get(timeout=.05)
            except Empty:
                kind = None
            try:
                if self.failed.is_set():
                    self.state = 'ERROR'
                    self.geometry.status('ERROR', datetime.now(UTC))
                    snapshots.clear()
                elif kind == 'status':
                    self.state = payload
                    self.geometry.status(payload, received)
                    snapshots.clear()
                elif kind == 'bar':
                    self.geometry.store.upsert_bar(payload, provider='ALPACA', feed=self.feed)
                    state=self.geometry.states.get(payload.symbol)
                    if state:
                        if payload.timestamp < state['candle']:
                            state['history']=None
                            state['retry_at']=datetime.now(UTC)
                        elif payload.timestamp == state['candle']:
                            state['opening']=payload.open
                            state['opening_stamp']=None
                        # A changed official reference cannot leave an earlier
                        # tick candidate queued for sending. Reevaluate on price.
                        snapshots[payload.symbol]={'symbol':payload.symbol,'provider':'ALPACA','feed':self.feed,
                            'source_kind':'TRADE','source_timestamp':received.isoformat(),
                            'received_at':received.isoformat(),'signal':None,'reason':'REFERENCE_UPDATED'}
                    # No analysis or historical network calls on the receive thread.
                    self.analysis.put_nowait((callback, payload))
                elif kind == 'trade':
                    snapshot, reason = self.geometry.observe(payload, received)
                    symbol = str(payload.get('S', '')).upper()
                    if snapshot:
                        snapshots[symbol] = snapshot
                    elif payload.get('T') in ('c', 'x'):
                        snapshots[symbol] = {'symbol': symbol, 'provider': 'ALPACA', 'feed': self.feed,
                            'source_kind': 'TRADE', 'source_timestamp': received.isoformat(),
                            'received_at': received.isoformat(), 'signal': None, 'reason': reason}
                    audit.append((received.isoformat(), symbol, payload.get('t'), reason, json.dumps(payload)))
                if time.monotonic()-last_flush >= .1 or len(audit) >= 200:
                    self.repository.flush(snapshots, audit, state=self.state, feed=self.feed,
                                          symbols=self.symbols, now=datetime.now(UTC))
                    snapshots.clear()
                    audit.clear()
                    last_flush = time.monotonic()
                    if last_flush-last_prune>=60:
                        with self.repository.connect() as db:
                            db.execute('DELETE FROM bollinger_tick_audit WHERE id <= '
                                       '(SELECT MAX(id)-200000 FROM bollinger_tick_audit)')
                        last_prune=last_flush
            except Exception:
                self.last_error = 'FAST_INGEST_FAILED'
                self.failed.set()
            finally:
                if kind is not None:
                    self.queue.task_done()
        self.repository.flush({}, audit, state='DETENIDO', feed=self.feed,
                              symbols=self.symbols, now=datetime.now(UTC))

    def close(self):
        self.finished.set()
        for thread in self.threads:
            thread.join(timeout=5)


class RealtimeBollingerStream:
    """Supervisor-compatible single stream with trade and bar subscriptions."""
    def __init__(self, config, worker):
        self.worker = worker
        self.stream = AlpacaStockBarStream(config, on_trade_message=worker.trade)

    def run(self, symbols, on_bar, *, on_error=None, on_status=None):
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
            self.stream.run(symbols, lambda bar: self.worker.bar(bar, on_bar),
                            on_error=error, on_status=status)
        finally:
            if not self.worker.failed.is_set():
                status('DESCONECTADO')

    def stop(self):
        self.stream.stop()
