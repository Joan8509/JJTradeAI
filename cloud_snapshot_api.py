"""API de lectura para la web Vercel; nunca expone credenciales ni envía órdenes."""
import hmac
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from bollinger_phone_worker import STATUS_PATH, STRATEGY_VERSION
from bollinger_strategy_study import OUTPUT
from market_calendar import MarketSessionRepository
from market_store import DEFAULT_MARKET_DATABASE
from watchlist_config import load_watchlist


def authorized(header, key):
    return len(key) >= 32 and hmac.compare_digest((header or "").encode(), ("Bearer "+key).encode())


def snapshot(database=DEFAULT_MARKET_DATABASE, *, as_of=None, status_path=STATUS_PATH, study_path=OUTPUT / "latest.json"):
    now = as_of or datetime.now(timezone.utc)
    session = MarketSessionRepository(database).session(now.astimezone(ZoneInfo("America/New_York")).date())
    market_open = session is not None and session.opens_at <= now < session.closes_at
    configured = list(load_watchlist()["symbols"])
    states, events = [], []
    with closing(sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=ro", uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "bollinger_radar_state" in tables:
            for (raw,) in db.execute("SELECT payload_json FROM bollinger_radar_state"):
                row = json.loads(raw)
                stamp = datetime.fromisoformat(row["source_timestamp"])
                if row["symbol"] in configured and row.get("version") == STRATEGY_VERSION and market_open and timedelta(minutes=1) <= now-stamp <= timedelta(minutes=3):
                    states.append({key: row.get(key) for key in ("symbol", "source_timestamp", "status", "signal")})
        if "bollinger_live_events" in tables:
            for (raw,) in db.execute("SELECT payload_json FROM bollinger_live_events ORDER BY detected_at DESC LIMIT 100"):
                row = json.loads(raw)
                if row.get("version") == STRATEGY_VERSION and row["symbol"] in configured:
                    events.append({key: row.get(key) for key in ("symbol", "side", "price", "detected_at")})
    healthy = False
    try:
        radar = json.loads(Path(status_path).read_text(encoding="utf-8"))
        heartbeat = datetime.fromisoformat(radar["heartbeat"])
        healthy = timedelta(0) <= now-heartbeat <= timedelta(seconds=30) and radar.get("state") in {"VIGILANDO", "VIGILANDO_SIN_AVISOS", "FUERA_DE_SESION"}
    except (OSError, ValueError, KeyError):
        pass
    study = None
    try:
        report = json.loads(Path(study_path).read_text(encoding="utf-8"))
        if report.get("version") == STRATEGY_VERSION:
            study = {"generated_at": report["generated_at"], "summary": report["summary"]}
    except (OSError, ValueError, KeyError):
        pass
    return {"schema": "jjtrade-bollinger-v1", "generated_at": now.isoformat(), "version": STRATEGY_VERSION,
            "market_open": market_open, "radar_healthy": healthy, "configured": configured,
            "current": states if healthy else [], "events": events, "study": study}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        key = os.environ.get("JJTRADE_BACKEND_KEY", "")
        if not authorized(self.headers.get("Authorization"), key):
            status, payload = 401, {"error": "Acceso no autorizado."}
        elif self.path != "/snapshot":
            status, payload = 404, {"error": "Ruta no disponible."}
        else:
            try:
                status, payload = 200, snapshot()
            except Exception:
                status, payload = 503, {"error": "Radar temporalmente no disponible."}
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    if len(os.environ.get("JJTRADE_BACKEND_KEY", "")) < 32:
        raise SystemExit("Configura JJTRADE_BACKEND_KEY con al menos 32 caracteres.")
    ThreadingHTTPServer((os.environ.get("JJTRADE_API_HOST", "127.0.0.1"), int(os.environ.get("JJTRADE_API_PORT", "8080"))), Handler).serve_forever()
