"""Radar temprano de salida Bollinger; no autoriza ni ejecuta operaciones."""
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore
from market_calendar import MarketSessionRepository
from telegram_alerts import CONFIG_PATH, TelegramError, connection, send_message

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
    return {"side": side, "price": float(latest.close), "candle": pd.Timestamp(latest["date"]).isoformat()}


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
    if not (upper > previous_upper and lower < previous_lower):
        return None
    if close > upper and close > opening and mid > previous_mid:
        return "SUPERIOR"
    if close < lower and close < opening and mid < previous_mid:
        return "INFERIOR"
    return None


def message_for(symbol, signal, source_time):
    direction = "alcista" if signal["side"] == "SUPERIOR" else "bajista"
    local = source_time.astimezone(ZoneInfo("America/New_York"))
    return (f"🔔 {symbol} · Bollinger 15 minutos\n"
            f"Salida {direction} por el disipador {signal['side'].lower()}.\n"
            f"Ambas bandas se abren y el punto medio acompaña.\n"
            f"Precio observado: {signal['price']:.2f} · Barra: {local:%I:%M %p} ET\n"
            "AVISO TEMPRANO: vela en formación o recién cerrada; puede revertirse.\n"
            "Revisa tu gráfico. No es una aprobación de entrada.")


def tick(database=DEFAULT_MARKET_DATABASE, *, as_of=None, sender=send_message):
    now = as_of or datetime.now(timezone.utc)
    notifications_enabled = enabled() and connection() is not None
    session = MarketSessionRepository(database).session(now.astimezone(ZoneInfo("America/New_York")).date())
    if session is None or not session.opens_at <= now < session.closes_at:
        return {"state": "FUERA_DE_SESION", "observed": 0}
    with _database(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS bollinger_phone_notifications (event_key TEXT PRIMARY KEY, state TEXT NOT NULL, attempted_at TEXT NOT NULL, message_id INTEGER, error TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS bollinger_radar_state (symbol TEXT PRIMARY KEY, source_timestamp TEXT NOT NULL, payload_json TEXT NOT NULL)")
        # Solamente símbolos que el buscador está vigilando y actualizando.
        previews = db.execute("SELECT symbol FROM live_bollinger_preview WHERE updated_at >= ?", ((now - timedelta(minutes=3)).isoformat(),)).fetchall()
    store = MarketBarStore(database)
    observed = sent = 0
    errors = []
    for (symbol,) in previews:
        with _database(database) as db:
            source = db.execute("SELECT provider,feed,MAX(timestamp) FROM minute_bars WHERE symbol=? AND timestamp>=? AND timestamp<=? GROUP BY provider,feed ORDER BY MAX(timestamp) DESC LIMIT 1",
                                (symbol, (now - timedelta(minutes=3)).isoformat(), (now - timedelta(minutes=1)).isoformat())).fetchone()
        if source is None:
            continue
        provider, feed, stamp = source
        source_time = datetime.fromisoformat(stamp)
        bars = store.load_frame(symbol=symbol, provider=provider, feed=feed, start=now-timedelta(days=7), end=source_time)
        if bars.empty:
            continue
        observed += 1
        signal = detect_exit(prepare_market_frame(aggregate_minute_bars(bars, "15m")))
        state_payload = {"symbol": symbol, "provider": provider, "feed": feed,
                         "version": STRATEGY_VERSION,
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
                     "source_timestamp": source_time.isoformat(), "detected_at": now.isoformat(), "version": STRATEGY_VERSION,
                     "opening": float(aggregate_minute_bars(bars, '15m').iloc[-1]['open'])}
            event_key = f"{STRATEGY_VERSION}|{provider}|{feed}|{symbol}|{signal['candle']}|{signal['side']}"
            db.execute("INSERT OR IGNORE INTO bollinger_live_events VALUES(?,?,?)", (event_key, now.isoformat(), json.dumps(event)))
        if not notifications_enabled:
            continue
        # Una notificación por compañía, vela, disipador y chat, aun tras reiniciar.
        chat_id = connection()["chat_id"]
        key = f"v1|{chat_id}|{provider}|{feed}|{symbol}|{signal['candle']}|{signal['side']}"
        with _database(database) as db:
            claimed = db.execute("INSERT OR IGNORE INTO bollinger_phone_notifications(event_key,state,attempted_at) VALUES(?,?,?)", (key, "ENVIANDO", now.isoformat())).rowcount
        if not claimed:
            continue
        try:
            result = sender(message_for(symbol, signal, source_time))
            state, message_id, error = "ENVIADO", result.get("message_id"), None
            sent += 1
        except TelegramError as failure:
            # No reenvía automáticamente: un timeout puede ocurrir después de entregar.
            state, message_id, error = "ENVIO_NO_CONFIRMADO", None, str(failure)
            errors.append(error)
        with _database(database) as db:
            db.execute("UPDATE bollinger_phone_notifications SET state=?,message_id=?,error=? WHERE event_key=?", (state, message_id, error, key))
    return {"state": ("VIGILANDO" if notifications_enabled else "VIGILANDO_SIN_AVISOS") if observed else "SIN_DATOS_RECIENTES", "observed": observed, "sent": sent, "errors": errors}


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
    while True:
        try:
            status = tick()
        except Exception:
            status = {"state": "ERROR", "error": "No se pudo completar la revisión. Revisa los datos y la conexión."}
        status.update({"heartbeat": datetime.now(timezone.utc).isoformat(), "pid": os.getpid()})
        temporary = STATUS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(status), encoding="utf-8")
        temporary.replace(STATUS_PATH)
        time.sleep(5)


if __name__ == "__main__":
    main()
