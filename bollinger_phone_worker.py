"""Radar temprano de salida Bollinger; no autoriza ni ejecuta operaciones."""
import json
import math
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread
from zoneinfo import ZoneInfo

import pandas as pd
from bollinger_expansion import (MINIMUM_BAND_EXPANSION_PCT,
                                 measure_band_expansion, expansion_evidence)

from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore
from market_calendar import MarketSessionRepository
from telegram_alerts import CONFIG_PATH, TelegramError, connection, send_message
from bollinger_ma_context import live_context
from watchlist_config import load_watchlist

POLICY_PATH = CONFIG_PATH.parent / "bollinger_policy.json"
STATUS_PATH = CONFIG_PATH.parent / "radar_status.json"
STRATEGY_VERSION = "v5_apertura_dentro_bandas_actuales"
# Stable event identity across the authorized opening interpretation update.
# Payload version changes; existing events and notification claims never replay.
EVENT_KEY_VERSION = "v4_apertura_dentro_sin_veto_previo"


def canonical_candle(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('La vela requiere zona horaria.')
    return stamp.astimezone(timezone.utc).isoformat()


def candle_keys(prefix, candle, side):
    """Preserve deduplication against keys written before UTC normalization."""
    stamp = datetime.fromisoformat(canonical_candle(candle))
    values = [stamp.isoformat(), stamp.astimezone(ZoneInfo('America/New_York')).isoformat()]
    return tuple(dict.fromkeys(f'{prefix}|{value}|{side}' for value in values))


def claim_notice(db, keys, attempted_at):
    # Serialize the lookup and insert so old aliases cannot race a new claim.
    db.execute('BEGIN IMMEDIATE')
    placeholders = ','.join('?' for _ in keys)
    if db.execute(f'SELECT 1 FROM bollinger_phone_notifications WHERE event_key IN ({placeholders})', keys).fetchone():
        return False
    return bool(db.execute('INSERT OR IGNORE INTO bollinger_phone_notifications(event_key,state,attempted_at) VALUES(?,?,?)',
                           (keys[0], 'ENVIANDO', attempted_at)).rowcount)


def delivery_status(database):
    """Keep the last delivery result visible even on cycles without signals."""
    with _database(database) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='bollinger_phone_notifications'").fetchone():
            return {}
        row = db.execute('SELECT state,attempted_at FROM bollinger_phone_notifications ORDER BY attempted_at DESC LIMIT 1').fetchone()
    return {'last_delivery_state': row[0], 'last_delivery_at': row[1]} if row else {}


@contextmanager
def _database(path):
    db = sqlite3.connect(path, timeout=15)
    try:
        with db:
            yield db
    finally:
        db.close()


def set_enabled(enabled):
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = POLICY_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps({"enabled": bool(enabled), "updated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    temporary.replace(POLICY_PATH)


def enabled():
    if not POLICY_PATH.exists():
        return os.environ.get("TELEGRAM_ALERTS_ENABLED", "false").lower() == "true"
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8")).get("enabled") is True
    except (OSError, ValueError):
        return False


def detect_exit(prepared):
    """Compara vela parcial con la anterior; mide expansión, sin umbrales calibrados."""
    if len(prepared) < 2:
        return None
    previous, latest = prepared.iloc[-2], prepared.iloc[-1]
    columns = ("close", "bollinger_upper", "bollinger_lower", "bollinger_mid")
    if not all(math.isfinite(float(row[column])) for row in (previous, latest) for column in columns):
        return None
    if latest.get('open') is None or not math.isfinite(float(latest.get('open'))):
        return None
    side = detect_values(previous.close, previous.bollinger_upper, previous.bollinger_lower, previous.bollinger_mid,
                         latest.close, latest.bollinger_upper, latest.bollinger_lower, latest.bollinger_mid,
                         opening=latest.get("open"))
    if side is None:
        return None
    distance=float(latest.close-latest.bollinger_upper) if side=='SUPERIOR' else float(latest.bollinger_lower-latest.close)
    exposure=distance/float(latest.bollinger_upper-latest.bollinger_lower)*100
    return {"side": side, "price": float(latest.close), "candle": pd.Timestamp(latest["date"]).isoformat(),
            "band_expansion": expansion_evidence(float(latest.bollinger_upper), float(latest.bollinger_lower),
                float(previous.bollinger_upper), float(previous.bollinger_lower)),
            "exposure_pct_bandwidth":exposure,"small_exposure":exposure<1}


def bands_at_open(prior_closes, opening):
    values = [float(v) for v in prior_closes] + [float(opening)]
    mean = sum(values)/len(values)
    deviation = math.sqrt(sum((v-mean)**2 for v in values)/len(values))
    return mean+2*deviation, mean-2*deviation


def detect_values(previous_close, previous_upper, previous_lower, previous_mid, close, upper, lower, mid, *, opening=None, opening_upper=None, opening_lower=None):
    """Shared live/replay rule. Legacy opening-band kwargs are audit-only.

    User clarification26/10: compare this candle's genuine opening with the
    bands available NOW, not bands frozen at its first trade. No future close.
    """
    if not all(math.isfinite(float(value)) for value in (previous_close, previous_upper, previous_lower, previous_mid, close, upper, lower, mid)):
        return None
    if opening is None or not math.isfinite(float(opening)):
        return None
    if not lower <= opening <= upper:
        return None
    # Opening stays fixed/official; only the live bands evolve. An opening
    # still outside those current bands cannot authorize an exit.
    # Condición obligatoria de volatilidad: ambos disipadores deben abrirse
    # frente a la vela anterior. Una salida del precio o más ancho por una
    # sola banda no basta y ningún apoyo histórico puede saltarse esta regla.
    if not (upper > previous_upper and lower < previous_lower):
        return None
    # User-authorized minimum, inclusive, for EACH band relative to the old width.
    try:
        expansion = measure_band_expansion(upper, lower, previous_upper, previous_lower)
    except (TypeError, ValueError, OverflowError):
        return None
    if not expansion.meets(MINIMUM_BAND_EXPANSION_PCT):
        return None
    if close > upper and close > opening and mid > previous_mid:
        return "SUPERIOR"
    if close < lower and close < opening and mid < previous_mid:
        return "INFERIOR"
    return None


def message_for(symbol, signal, source_time):
    from price_ranges import load_option_price_ranges
    from stock_instruments import STOCK_INSTRUMENTS
    reference = load_option_price_ranges().get(symbol)
    name = reference['name'] if reference else STOCK_INSTRUMENTS.get(symbol, {}).get('name')
    company = f"{symbol} · {name}" if name else symbol
    local = pd.Timestamp(signal.get('candle', source_time)).to_pydatetime().astimezone(ZoneInfo("America/New_York"))
    price_range = f"${reference['optimal_low']:g} – ${reference['optimal_high']:g}" if reference else "Sin rango definido"
    return (f"{company}\n"
            f"Salida: {signal['side'].lower()}\n"
            f"Vela: 15 min · {local:%I:%M %p} ET\n"
            f"Rango de precios: {price_range}")


@lru_cache(maxsize=256)
def _signal_support(database, symbol, provider, feed, stamp, side, price):
    """Reuse descriptive support while the exact observed bar stays unchanged."""
    signal={'side':side,'price':price}
    try:
        return live_context(database,symbol,provider,feed,datetime.fromisoformat(stamp),signal)
    except (ValueError,KeyError,OSError,sqlite3.Error):
        return {'state':'SIN_DATOS','ma_type':'SMA','provisional':False}


class SignalSupportWorker:
    """Descriptive research after detection; never in the notification path."""
    def __init__(self):
        self.queue = Queue(maxsize=64)
        self.finished = Event()
        self.seen = set()
        self.thread = Thread(target=self._run, name='bollinger-support', daemon=True)
        self.thread.start()

    def submit(self, database, event_key, event):
        if event_key in self.seen:
            return
        try:
            self.queue.put_nowait((str(database), event_key, dict(event)))
            self.seen.add(event_key)
            if len(self.seen) > 2048:
                self.seen = {event_key}
        except Full:
            pass  # Research overload must not delay price detection.

    def _run(self):
        while not self.finished.is_set():
            try:
                database, key, event = self.queue.get(timeout=.1)
            except Empty:
                continue
            try:
                source = datetime.fromisoformat(event['source_timestamp'])
                available = source if event.get('source_kind') == 'TRADE' else source+timedelta(minutes=1)
                from bollinger_pattern_memory import historical_support
                event['ma_context'] = live_context(database, event['symbol'], event['provider'],
                    event['feed'], source, event, available_at=available)
                event['historical_support'] = historical_support(event['symbol'], event['provider'],
                    event['feed'], source, event, available_at=available)
                from bollinger_volatility_context import live_volatility_context
                event['higher_volatility'] = live_volatility_context(database,event['symbol'],event['provider'],
                    event['feed'],source,event,available_at=available)
                with _database(database) as db:
                    db.execute('UPDATE bollinger_live_events SET payload_json=? WHERE event_key=?',
                               (json.dumps(event), key))
                    row = db.execute('SELECT payload_json FROM bollinger_radar_state WHERE symbol=? '
                                     'AND source_timestamp=?', (event['symbol'],event['source_timestamp'])).fetchone()
                    if row:
                        payload = json.loads(row[0])
                        if payload.get('signal'):
                            payload['signal']['ma_context'] = event['ma_context']
                            payload['signal']['historical_support'] = event['historical_support']
                            payload['signal']['higher_volatility'] = event['higher_volatility']
                            db.execute('UPDATE bollinger_radar_state SET payload_json=? WHERE symbol=? '
                                       'AND source_timestamp=?', (json.dumps(payload),event['symbol'],event['source_timestamp']))
            except Exception:
                # Optional support is never approval. A failed job can retry.
                self.seen.discard(key)
            finally:
                self.queue.task_done()

    def close(self):
        self.finished.set()
        self.thread.join(timeout=5)


def _save_radar_states(database, rows):
    """One short transaction for a cycle, never across research or network I/O."""
    if rows:
        with _database(database) as db:
            db.executemany("INSERT INTO bollinger_radar_state VALUES(?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET source_timestamp=excluded.source_timestamp,"
                "payload_json=excluded.payload_json WHERE "
                "bollinger_radar_state.source_timestamp<>excluded.source_timestamp OR "
                "CASE WHEN json_valid(bollinger_radar_state.payload_json) THEN "
                "json_remove(bollinger_radar_state.payload_json,'$.checked_at')<>"
                "json_remove(excluded.payload_json,'$.checked_at') ELSE 1 END", rows)
        rows.clear()


def tick(database=DEFAULT_MARKET_DATABASE, *, as_of=None, sender=send_message, support_worker=None):
    from bollinger_reference_scope import REGULAR, active_reference_scope
    reference_scope = active_reference_scope()
    now = as_of or datetime.now(timezone.utc)
    wall_time=(lambda:now) if as_of is not None else (lambda:datetime.now(timezone.utc))
    tick_started=time.perf_counter()
    notifications_enabled = enabled() and connection() is not None
    session = MarketSessionRepository(database).session(now.astimezone(ZoneInfo("America/New_York")).date())
    if session is None or not session.opens_at <= now < session.closes_at:
        return {"state": "FUERA_DE_SESION", "observed": 0}
    with _database(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS bollinger_phone_notifications (event_key TEXT PRIMARY KEY, state TEXT NOT NULL, attempted_at TEXT NOT NULL, message_id INTEGER, error TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS bollinger_radar_state (symbol TEXT PRIMARY KEY, source_timestamp TEXT NOT NULL, payload_json TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS bollinger_notice_timing (event_key TEXT PRIMARY KEY, source_ready_at TEXT, source_received_at TEXT, detected_at TEXT, send_started_at TEXT, send_finished_at TEXT, telegram_message_at TEXT, support_ms REAL, tick_to_send_ms REAL, send_ms REAL, state TEXT)")
        if not any(row[1]=='source_kind' for row in db.execute('PRAGMA table_info(bollinger_notice_timing)')):
            db.execute("ALTER TABLE bollinger_notice_timing ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'BAR'")
        has_received=any(row[1]=='received_at' for row in db.execute('PRAGMA table_info(minute_bars)'))
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tick_symbols=set()
        tick_payloads={}
        if 'bollinger_tick_runtime' in tables:
            runtime=db.execute('SELECT state,heartbeat,symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()
            if runtime and runtime[0]=='CONECTADO':
                # Ownership does not disappear when a heartbeat is stale or
                # advances while this cycle is reading SQLite. Never turn a
                # connected trade stream into an old minute-bar signal.
                tick_symbols=set(json.loads(runtime[2]))
                for symbol,payload in db.execute('SELECT symbol,payload_json FROM bollinger_tick_latest'):
                    tick_payloads[symbol]=json.loads(payload)
        previews = db.execute("SELECT symbol FROM live_bollinger_preview WHERE updated_at >= ?", ((now - timedelta(minutes=3)).isoformat(),)).fetchall() if 'live_bollinger_preview' in tables else []
        previews=sorted(set(previews).union((symbol,) for symbol in tick_symbols))
    # Check the heartbeat against the clock AFTER the snapshot was read. The
    # collector can publish a newer heartbeat than the cycle's starting time.
    now = wall_time()
    stream_ready = bool(tick_symbols and timedelta(0) <=
                        now-datetime.fromisoformat(runtime[1]) <= timedelta(seconds=3))
    store = MarketBarStore(database)
    observed = sent = 0
    errors = []
    radar_states = []
    configured=set(load_watchlist()['symbols'])
    for (symbol,) in previews:
        if symbol not in configured:
            continue
        source_kind='BAR'
        opening=None
        if symbol in tick_symbols:
            if not stream_ready:
                continue
            source_kind='TRADE'
            payload=tick_payloads.get(symbol)
            if not payload:
                continue
            if payload.get('reference_scope', REGULAR) != reference_scope:
                continue  # Mixed collector/radar scope cannot authorize a notice.
            source_time=datetime.fromisoformat(payload['source_timestamp'])
            # An active stream owns the symbol even between trades. Never
            # resurrect an older minute-close exit after a tick has retracted.
            if not timedelta(0)<=now-source_time<=timedelta(seconds=3):
                continue
            provider,feed=payload['provider'],payload['feed']
            received=payload['received_at']
            opening=payload.get('opening')
            signal=payload.get('signal')
            observed+=1
        else:
            provider=feed=None
        if source_kind=='BAR':
            result = _minute_signal(database, store, symbol, now, has_received)
            if result is None:
                continue
            provider,feed,source_time,received,signal,opening=result
            observed+=1
        if signal is not None:
            signal = dict(signal)
            signal['candle'] = canonical_candle(signal['candle'])
        detected_time=wall_time()
        support_started=time.perf_counter()
        if signal is not None and support_worker is None:
            available=source_time if source_kind=='TRADE' else source_time+timedelta(minutes=1)
            signal=dict(signal)
            signal['ma_context'] = (live_context(database,symbol,provider,feed,source_time,signal,available_at=available)
                if source_kind=='TRADE' else _signal_support(str(database),symbol,provider,feed,
                source_time.isoformat(),signal['side'],signal['price']))
            from bollinger_pattern_memory import historical_support
            signal['historical_support'] = historical_support(symbol, provider, feed, source_time, signal, available_at=available)
        support_ms=(time.perf_counter()-support_started)*1000
        state_payload = {"symbol": symbol, "provider": provider, "feed": feed,
                         "reference_scope": reference_scope,
                         "version": STRATEGY_VERSION, "source_kind":source_kind,
                         "source_timestamp": source_time.isoformat(), "checked_at": now.isoformat(),
                         "data_reason": payload.get('reason') if source_kind == 'TRADE' else 'READY_MINUTE_REFERENCE',
                         "status": "SALIDA_DETECTADA" if signal else "SIN_SALIDA_NUEVA", "signal": signal}
        radar_states.append((symbol, source_time.isoformat(), json.dumps(state_payload)))
        if signal is None:
            continue
        # Publish preceding observations before optional support reads them.
        # The transaction ends before research, a claim or Telegram calls.
        _save_radar_states(database, radar_states)
        with _database(database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS bollinger_live_events (event_key TEXT PRIMARY KEY, detected_at TEXT NOT NULL, payload_json TEXT NOT NULL)")
            event = {**signal, "symbol": symbol, "provider": provider, "feed": feed,
                     "reference_scope": reference_scope,
                     "source_timestamp": source_time.isoformat(), "source_kind":source_kind,
                     "detected_at": detected_time.isoformat(), "version": STRATEGY_VERSION, "opening": opening}
            keys = candle_keys(f"{EVENT_KEY_VERSION}|{provider}|{feed}|{symbol}", signal['candle'], signal['side'])
            keys = tuple(dict.fromkeys(keys+candle_keys(f"{STRATEGY_VERSION}|{provider}|{feed}|{symbol}", signal['candle'], signal['side'])))
            existing = db.execute(f"SELECT event_key FROM bollinger_live_events WHERE event_key IN ({','.join('?' for _ in keys)}) ORDER BY detected_at LIMIT 1", keys).fetchone()
            event_key = existing[0] if existing else keys[0]
            if existing is None:
                db.execute("INSERT OR IGNORE INTO bollinger_live_events VALUES(?,?,?)", (event_key, detected_time.isoformat(), json.dumps(event)))
        # Submit only the original observed event, with its original price and
        # availability. The support thread cannot rewrite a later tick's signal.
        if support_worker is not None:
            with _database(database) as db:
                original=json.loads(db.execute('SELECT payload_json FROM bollinger_live_events WHERE event_key=?',(event_key,)).fetchone()[0])
            support_worker.submit(database,event_key,original)
        if not notifications_enabled:
            continue
        chat_id = connection()["chat_id"]
        notice_keys = candle_keys(f"v1|{chat_id}|{provider}|{feed}|{symbol}", signal['candle'], signal['side'])
        key = notice_keys[0]
        send_started=wall_time()
        send_clock=time.perf_counter()
        fresh=(timedelta(0)<=send_started-source_time<=timedelta(seconds=3) if source_kind=='TRADE'
               else timedelta(minutes=1)<=send_started-source_time<=timedelta(minutes=3))
        if not fresh:
            continue
        if source_kind=='TRADE':
            # Recheck current geometry immediately before claiming the send.
            with _database(database) as db:
                latest=db.execute('SELECT payload_json FROM bollinger_tick_latest WHERE symbol=?',(symbol,)).fetchone()
                runtime=db.execute('SELECT state,heartbeat FROM bollinger_tick_runtime WHERE id=1').fetchone()
            current=json.loads(latest[0]) if latest else {}
            current_signal=current.get('signal')
            if (not runtime or runtime[0]!='CONECTADO' or not timedelta(0)<=send_started-datetime.fromisoformat(runtime[1])<=timedelta(seconds=3)
                or current.get('reference_scope',REGULAR)!=reference_scope or active_reference_scope()!=reference_scope
                or not current_signal or current_signal['side']!=signal['side'] or canonical_candle(current_signal['candle'])!=signal['candle']
                or not timedelta(0)<=send_started-datetime.fromisoformat(current['source_timestamp'])<=timedelta(seconds=3)):
                continue
        with _database(database) as db:
            claimed = claim_notice(db, notice_keys, send_started.isoformat())
        if not claimed:
            continue
        telegram_time=None
        try:
            result = sender(message_for(symbol, signal, source_time))
            state, message_id, error = "ENVIADO", result.get("message_id"), None
            if isinstance(result.get('date'),(int,float)):
                telegram_time=datetime.fromtimestamp(result['date'],timezone.utc).isoformat()
            sent += 1
        except TelegramError as failure:
            state, message_id, error = "ENVIO_NO_CONFIRMADO", None, str(failure)
            errors.append(error)
        send_finished=wall_time()
        with _database(database) as db:
            db.execute("UPDATE bollinger_phone_notifications SET state=?,message_id=?,error=? WHERE event_key=?", (state, message_id, error, key))
            db.execute("INSERT OR IGNORE INTO bollinger_notice_timing "
                "(event_key,source_ready_at,source_received_at,detected_at,send_started_at,send_finished_at,telegram_message_at,support_ms,tick_to_send_ms,send_ms,state,source_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (key,(source_time if source_kind=='TRADE' else source_time+timedelta(minutes=1)).isoformat(),received,detected_time.isoformat(),
                 send_started.isoformat(),send_finished.isoformat(),telegram_time,support_ms,
                 (send_clock-tick_started)*1000,(time.perf_counter()-send_clock)*1000,state,source_kind))
    _save_radar_states(database, radar_states)
    return {"state": ("VIGILANDO" if notifications_enabled else "VIGILANDO_SIN_AVISOS") if observed else "SIN_DATOS_RECIENTES", "observed": observed, "sent": sent, "errors": errors,
            "price_mode":"TRADES" if tick_symbols else "MINUTE_BARS"}


def _minute_reference_ready(database, bars, aggregated, *, reference_scope=None):
    """Apply the fast path's official-period guard to the minute fallback.

    Aggregation drops empty periods, so twenty older rows alone cannot prove
    the required references exist. The first official minute also supplies
    this candle's opening; a later minute cannot substitute that opening.
    """
    if aggregated.empty:
        return False
    candle = pd.Timestamp(aggregated.iloc[-1]['date']).to_pydatetime()
    local_day = candle.astimezone(ZoneInfo('America/New_York')).date()
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            sessions = db.execute(
                'SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? '
                'AND session_date<=? ORDER BY session_date',
                ((local_day-timedelta(days=7)).isoformat(), local_day.isoformat()),
            ).fetchall()
    except sqlite3.Error:
        return False
    from bollinger_reference_scope import active_reference_scope,required_periods,regular_session
    scope = reference_scope or active_reference_scope()
    periods = required_periods(sessions,candle,scope=scope)
    closed = aggregated[aggregated.date < pd.Timestamp(candle)].tail(20)
    if regular_session(sessions,candle) is None or not periods or list(closed.date) != [p[0] for p in periods]:
        return False
    minutes = set(pd.to_datetime(bars.date, utc=True))
    return pd.Timestamp(periods[-1][1]-timedelta(minutes=1)) in minutes and pd.Timestamp(candle) in minutes


def _aggregate_reference_minutes(bars, scope):
    from bollinger_reference_scope import EXTENDED
    if scope == EXTENDED:
        # Only the requested 04:00-20:00 window; never include overnight bars.
        local = pd.to_datetime(bars.date,utc=True).dt.tz_convert('America/New_York')
        bars = bars.loc[(local.dt.hour >= 4) & (local.dt.hour < 20)]
    return aggregate_minute_bars(bars,'15m',regular_hours_only=(scope != EXTENDED))


def _recent_minute_source(database, symbol, now):
    """Seek each source prefix, then its latest eligible minute using the PK.

    GROUP BY with only symbol/time filters scans the whole composite index.
    Prefix seeks retain the same source selection without a new schema/index.
    """
    start, end = (now-timedelta(minutes=3)).isoformat(), (now-timedelta(minutes=1)).isoformat()
    selected = None
    started = time.monotonic()
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.set_progress_handler(lambda: time.monotonic()-started > 2, 1000)
            db.execute('BEGIN')  # One consistent snapshot across the source-prefix seeks.
            pair = db.execute('SELECT provider,feed FROM minute_bars ORDER BY provider,feed LIMIT 1').fetchone()
            while pair:
                stamp = db.execute('SELECT timestamp FROM minute_bars WHERE provider=? AND feed=? AND symbol=? '
                                   'AND timestamp>=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1',
                                   (*pair, symbol, start, end)).fetchone()
                if stamp and (selected is None or stamp[0] > selected[2]):
                    selected = (*pair, stamp[0])
                pair = db.execute('SELECT provider,feed FROM minute_bars WHERE (provider,feed)>(?,?) '
                                  'ORDER BY provider,feed LIMIT 1', pair).fetchone()
    except sqlite3.OperationalError:
        return None  # Unavailable/partial evidence cannot authorize a signal.
    return selected


def _minute_signal(database, store, symbol, now, has_received):
    """Legacy minute fallback, separate from exact trade timestamps."""
    source = _recent_minute_source(database, symbol, now)
    if source is None:
        return None
    provider,feed,stamp=source
    received=None
    if has_received:
        with _database(database) as db:
            row=db.execute('SELECT received_at FROM minute_bars WHERE symbol=? AND provider=? AND feed=? AND timestamp=?',
                (symbol,provider,feed,stamp)).fetchone()
            received=row[0] if row else None
    source_time=datetime.fromisoformat(stamp)
    bars=store.load_frame(symbol=symbol,provider=provider,feed=feed,start=now-timedelta(days=7),end=source_time)
    if bars.empty:
        return None
    from bollinger_reference_scope import active_reference_scope
    scope=active_reference_scope()
    aggregated=_aggregate_reference_minutes(bars,scope)
    if not _minute_reference_ready(database, bars, aggregated, reference_scope=scope):
        return None
    signal=detect_exit(prepare_market_frame(aggregated))
    return provider,feed,source_time,received,signal,float(aggregated.iloc[-1]['open'])


def write_status(status, path=STATUS_PATH):
    """A brief Windows reader/antivirus lock must not kill Telegram monitoring."""
    temporary=path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(status),encoding='utf-8')
        for attempt in range(4):
            try:
                temporary.replace(path)
                return True
            except PermissionError:
                if attempt<3:
                    time.sleep(.025)
    except OSError:
        return False
    return False  # Keep monitoring; try publishing status next cycle.


def main():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = (CONFIG_PATH.parent / "radar.lock").open("a+b")
    lock.seek(0)
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    support_worker=SignalSupportWorker()
    health_at = 0
    feed_health = {}
    readiness_at = 0
    readiness = 'SIN_COMPROBAR'
    while True:
        try:
            status = tick(support_worker=support_worker)
        except Exception:
            status = {"state": "ERROR", "error": "No se pudo completar la revisión. Revisa los datos y la conexión."}
        status.update({"heartbeat": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()})
        if time.monotonic()-health_at >= 5:
            from radar_health import fast_feed_health
            try:
                feed_health = fast_feed_health(DEFAULT_MARKET_DATABASE)
            except (OSError, sqlite3.Error, ValueError):
                feed_health = {'state': 'DIAGNOSTICO_NO_DISPONIBLE'}
            health_at = time.monotonic()
        status['fast_feed_health'] = feed_health
        if time.monotonic()-readiness_at >= 30:
            from telegram_alerts import local_readiness
            readiness = local_readiness()
            readiness_at = time.monotonic()
        status['telegram_readiness'] = readiness
        try:
            status.update(delivery_status(DEFAULT_MARKET_DATABASE))
        except (OSError, sqlite3.Error):
            status['delivery_status_unavailable'] = True
        write_status(status)
        time.sleep(.25 if status.get('price_mode')=='TRADES' else 1)


if __name__ == "__main__":
    from sqlite_runtime_guard import require_safe_wal_runtime
    require_safe_wal_runtime(DEFAULT_MARKET_DATABASE)
    main()
