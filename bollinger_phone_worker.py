"""Radar temprano de salida Bollinger; no autoriza ni ejecuta operaciones."""
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread
from zoneinfo import ZoneInfo

import pandas as pd

from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore
from market_calendar import MarketSessionRepository
from telegram_alerts import CONFIG_PATH, TelegramError, connection, send_message
from bollinger_ma_context import live_context
from watchlist_config import load_watchlist

POLICY_PATH = CONFIG_PATH.parent / "bollinger_policy.json"
STATUS_PATH = CONFIG_PATH.parent / "radar_status.json"
STRATEGY_VERSION = "v3_bandas_en_apertura"


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
    opening_upper = opening_lower = None
    if latest.get('open') is None or not math.isfinite(float(latest.get('open'))):
        return None
    if len(prepared) >= 20:
        opening_upper, opening_lower = bands_at_open(prepared.iloc[-20:-1]['close'].tolist(), latest.get('open'))
    side = detect_values(previous.close, previous.bollinger_upper, previous.bollinger_lower, previous.bollinger_mid,
                         latest.close, latest.bollinger_upper, latest.bollinger_lower, latest.bollinger_mid,
                         opening=latest.get("open"), opening_upper=opening_upper, opening_lower=opening_lower)
    if side is None:
        return None
    distance=float(latest.close-latest.bollinger_upper) if side=='SUPERIOR' else float(latest.bollinger_lower-latest.close)
    exposure=distance/float(latest.bollinger_upper-latest.bollinger_lower)*100
    return {"side": side, "price": float(latest.close), "candle": pd.Timestamp(latest["date"]).isoformat(),
            "exposure_pct_bandwidth":exposure,"small_exposure":exposure<1}


def bands_at_open(prior_closes, opening):
    values = [float(v) for v in prior_closes] + [float(opening)]
    mean = sum(values)/len(values)
    deviation = math.sqrt(sum((v-mean)**2 for v in values)/len(values))
    return mean+2*deviation, mean-2*deviation


def detect_values(previous_close, previous_upper, previous_lower, previous_mid, close, upper, lower, mid, *, opening=None, opening_upper=None, opening_lower=None):
    """Regla única compartida por el radar y la reconstrucción histórica."""
    if not all(math.isfinite(float(value)) for value in (previous_close, previous_upper, previous_lower, previous_mid, close, upper, lower, mid)):
        return None
    if not previous_lower <= previous_close <= previous_upper:
        return None
    if opening is None or not math.isfinite(float(opening)):
        return None
    # Recalcula las bandas con los 19 cierres conocidos y la apertura, no con el
    # cierre posterior. Un salto ya fuera de estas bandas sigue excluido.
    open_upper = previous_upper if opening_upper is None else opening_upper
    open_lower = previous_lower if opening_lower is None else opening_lower
    if not all(math.isfinite(float(v)) for v in (open_upper, open_lower)) or not open_lower <= opening <= open_upper:
        return None
    # Condición obligatoria de volatilidad: ambos disipadores deben abrirse
    # frente a la vela anterior. Una salida del precio o más ancho por una
    # sola banda no basta y ningún apoyo histórico puede saltarse esta regla.
    if not (upper > previous_upper and lower < previous_lower):
        return None
    if close > upper and close > opening and mid > previous_mid:
        return "SUPERIOR"
    if close < lower and close < opening and mid < previous_mid:
        return "INFERIOR"
    return None


def message_for(symbol, signal, source_time):
    from price_ranges import load_option_price_ranges
    reference = load_option_price_ranges().get(symbol)
    company = f"{symbol} · {reference['name']}" if reference else symbol
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


def tick(database=DEFAULT_MARKET_DATABASE, *, as_of=None, sender=send_message, support_worker=None):
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
            if runtime and runtime[0]=='CONECTADO' and timedelta(0)<=now-datetime.fromisoformat(runtime[1])<=timedelta(seconds=3):
                tick_symbols=set(json.loads(runtime[2]))
                for symbol,payload in db.execute('SELECT symbol,payload_json FROM bollinger_tick_latest'):
                    tick_payloads[symbol]=json.loads(payload)
        previews = db.execute("SELECT symbol FROM live_bollinger_preview WHERE updated_at >= ?", ((now - timedelta(minutes=3)).isoformat(),)).fetchall() if 'live_bollinger_preview' in tables else []
        previews=sorted(set(previews).union((symbol,) for symbol in tick_symbols))
    store = MarketBarStore(database)
    observed = sent = 0
    errors = []
    configured=set(load_watchlist()['symbols'])
    for (symbol,) in previews:
        if symbol not in configured:
            continue
        source_kind='BAR'
        opening=None
        if symbol in tick_symbols:
            source_kind='TRADE'
            payload=tick_payloads.get(symbol)
            if not payload:
                continue
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
                         "version": STRATEGY_VERSION, "source_kind":source_kind,
                         "source_timestamp": source_time.isoformat(), "checked_at": now.isoformat(),
                         "status": "SALIDA_DETECTADA" if signal else "SIN_SALIDA_NUEVA", "signal": signal}
        with _database(database) as db:
            db.execute("INSERT INTO bollinger_radar_state VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET source_timestamp=excluded.source_timestamp,payload_json=excluded.payload_json",
                       (symbol, source_time.isoformat(), json.dumps(state_payload)))
        if signal is None:
            continue
        with _database(database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS bollinger_live_events (event_key TEXT PRIMARY KEY, detected_at TEXT NOT NULL, payload_json TEXT NOT NULL)")
            event = {**signal, "symbol": symbol, "provider": provider, "feed": feed,
                     "source_timestamp": source_time.isoformat(), "source_kind":source_kind,
                     "detected_at": detected_time.isoformat(), "version": STRATEGY_VERSION, "opening": opening}
            event_key = f"{STRATEGY_VERSION}|{provider}|{feed}|{symbol}|{signal['candle']}|{signal['side']}"
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
        key = f"v1|{chat_id}|{provider}|{feed}|{symbol}|{signal['candle']}|{signal['side']}"
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
                or not current_signal or current_signal['side']!=signal['side'] or current_signal['candle']!=signal['candle']
                or not timedelta(0)<=send_started-datetime.fromisoformat(current['source_timestamp'])<=timedelta(seconds=3)):
                continue
        with _database(database) as db:
            claimed = db.execute("INSERT OR IGNORE INTO bollinger_phone_notifications(event_key,state,attempted_at) VALUES(?,?,?)", (key, "ENVIANDO", send_started.isoformat())).rowcount
        if not claimed:
            continue
        telegram_time=None
        try:
            from manual_trade_links import signal_link
            url=signal_link(symbol,signal,source_time)
            markup={'inline_keyboard':[[{'text':'Abrir señal y operar','url':url}]]} if url else None
            result = sender(message_for(symbol, signal, source_time),reply_markup=markup) if markup else sender(message_for(symbol, signal, source_time))
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
    return {"state": ("VIGILANDO" if notifications_enabled else "VIGILANDO_SIN_AVISOS") if observed else "SIN_DATOS_RECIENTES", "observed": observed, "sent": sent, "errors": errors,
            "price_mode":"TRADES" if tick_symbols else "MINUTE_BARS"}


def _minute_signal(database, store, symbol, now, has_received):
    """Legacy minute fallback, separate from exact trade timestamps."""
    with _database(database) as db:
        source = db.execute("SELECT provider,feed,MAX(timestamp) FROM minute_bars WHERE symbol=? AND timestamp>=? AND timestamp<=? GROUP BY provider,feed ORDER BY MAX(timestamp) DESC LIMIT 1",
            (symbol, (now-timedelta(minutes=3)).isoformat(), (now-timedelta(minutes=1)).isoformat())).fetchone()
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
    aggregated=aggregate_minute_bars(bars,'15m')
    signal=detect_exit(prepare_market_frame(aggregated))
    return provider,feed,source_time,received,signal,float(aggregated.iloc[-1]['open'])


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
    while True:
        try:
            status = tick(support_worker=support_worker)
        except Exception:
            status = {"state": "ERROR", "error": "No se pudo completar la revisión. Revisa los datos y la conexión."}
        status.update({"heartbeat": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()})
        temporary = STATUS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(status), encoding="utf-8")
        temporary.replace(STATUS_PATH)
        time.sleep(.25 if status.get('price_mode')=='TRADES' else 1)


if __name__ == "__main__":
    main()
