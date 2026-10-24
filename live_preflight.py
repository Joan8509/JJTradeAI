"""Diagnóstico local previo al arranque del scanner en vivo."""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path
import re
import sqlite3
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from option_opportunity import load_option_opportunity_policy
from safe_diagnostics import sanitize_diagnostic_detail, sanitize_diagnostic_payload


SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")


def run_live_preflight(
    *, symbols: tuple[str, ...], benchmarks: tuple[str, ...], days: int,
    database: str | Path, option_policy: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    integrity_verified_by_backup: bool = False,
) -> dict[str, Any]:
    """Valida configuración local sin revelar secretos ni llamar la red."""
    env = environment if environment is not None else os.environ
    checks: list[dict[str, str]] = []
    invalid = [item for item in (*symbols, *benchmarks) if not SYMBOL_PATTERN.fullmatch(item)]
    _check(checks, "symbols", bool(symbols) and not invalid, "Símbolos válidos." if symbols and not invalid else "Faltan símbolos o existe formato inválido: " + ", ".join(invalid))
    _check(checks, "backfill_days", days > 0, f"Backfill configurado: {days} días." if days > 0 else "--days debe ser mayor que cero.")
    key = bool(env.get("ALPACA_API_KEY", "").strip())
    secret = bool(env.get("ALPACA_API_SECRET", "").strip())
    _check(checks, "credentials", key and secret, "Credenciales presentes (valores ocultos)." if key and secret else "Faltan ALPACA_API_KEY o ALPACA_API_SECRET.")
    feed = env.get("ALPACA_DATA_FEED", "iex").strip().lower()
    _check(checks, "feed", feed in {"iex", "sip"}, f"Feed en vivo: {feed}." if feed in {"iex", "sip"} else "El scanner requiere iex o sip; delayed_sip no es tiempo real.")
    websocket_available = find_spec("websocket") is not None
    _check(
        checks,
        "websocket_runtime",
        websocket_available,
        (
            "Runtime WebSocket disponible."
            if websocket_available
            else "Falta websocket-client; ejecuta pip install -r requirements.txt."
        ),
    )
    try:
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE preflight_write_probe (id INTEGER)")
            connection.rollback()
            if integrity_verified_by_backup:
                connection.execute('PRAGMA schema_version').fetchone()
            else:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                if integrity != "ok":
                    raise ValueError(f"quick_check={integrity}")
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError) as error:
        _check(
            checks,
            "database",
            False,
            "Base SQLite no disponible: " + sanitize_diagnostic_detail(error),
        )
    else:
        _check(checks, "database", True, f"Base SQLite escribible: {path}.")
        if integrity_verified_by_backup:
            checks.append(dict(name='database_integrity',status='PENDIENTE_BACKUP',
                detail='La copia obligatoria debe superar integridad antes de conectar al mercado.'))
    if option_policy is None:
        checks.append({"name": "option_policy", "status": "OMITIDO", "detail": "Opciones desactivadas; no se consultará la cadena."})
    else:
        try:
            policy = load_option_opportunity_policy(option_policy)
        except ValueError as error:
            _check(
                checks,
                "option_policy",
                False,
                sanitize_diagnostic_detail(error),
            )
        else:
            _check(checks, "option_policy", True, f"Política válida; feed de opciones={policy.option_feed}.")
    failed = [item for item in checks if item["status"] == "ERROR"]
    return {
        "status": "LISTO_LOCAL" if not failed else "BLOQUEADO",
        "network_status": "PENDIENTE", "failed_count": len(failed),
        "symbols": list(symbols), "benchmarks": list(benchmarks),
        "checks": checks, "secrets_exposed": False,
    }


def _check(checks: list[dict[str, str]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "status": "OK" if passed else "ERROR", "detail": detail})


def record_live_preflight(database: str | Path, payload: Mapping[str, Any]) -> int:
    """Conserva el diagnóstico sin almacenar valores de credenciales."""
    safe_payload = sanitize_diagnostic_payload(payload)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS live_preflight_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL)"
        )
        cursor = connection.execute(
            "INSERT INTO live_preflight_runs (created_at, status, payload_json) VALUES (?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                sanitize_diagnostic_detail(
                    payload.get("status", "BLOQUEADO"),
                    limit=50,
                ),
                json.dumps(safe_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def recent_live_preflights(database: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("El límite debe ser mayor que cero.")
    connection = sqlite3.connect(database)
    try:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT * FROM live_preflight_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        connection.close()
    return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]
