"""Genera evidencia auditable de una sesion PAPER con mercado real."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Sequence

from scanner_instance import read_instance_status
from safe_diagnostics import sanitize_diagnostic_detail


def build_paper_session_evidence(
    database: str | Path,
    *,
    symbols: tuple[str, ...] = (),
    lock_file: str | Path = "exports/live_scanner.lock",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evalua evidencia persistida sin red, secretos ni ejecucion de ordenes."""
    database_path = Path(database)
    evaluated_at = now or datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        raise ValueError("now debe incluir zona horaria.")
    if not database_path.is_file():
        return _empty_payload(
            database_path,
            evaluated_at,
            "NO_INICIADO",
            ["No existe la base de datos de la sesion PAPER."],
            lock_file,
        )

    try:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            preflight = _latest_remote_preflight(connection)
            session_started_at = (
                str(preflight["_created_at"]) if preflight is not None else None
            )
            expected = _expected_symbols(symbols, preflight)
            health = _latest_health(connection, session_started_at)
            expected_feed = _expected_feed(health)
            bars = _bar_evidence(
                connection, expected, expected_feed, session_started_at
            )
            reconciliations = _reconciliation_evidence(
                connection,
                expected,
                expected_feed,
                bars,
                session_started_at,
            )
            incidents = _processing_incident_evidence(
                connection,
                expected,
                session_started_at,
            )
            integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        finally:
            connection.close()
    except (sqlite3.Error, json.JSONDecodeError, ValueError) as error:
        return _empty_payload(
            database_path,
            evaluated_at,
            "BLOQUEADO",
            [
                "No se pudo auditar la base PAPER: "
                + sanitize_diagnostic_detail(error)
            ],
            lock_file,
        )

    checks = [
        _check(
            "database_integrity",
            integrity == "ok",
            f"SQLite quick_check={integrity}.",
        ),
        _check(
            "remote_preflight",
            bool(preflight and preflight.get("status") == "LISTO"),
            "Preflight remoto LISTO registrado."
            if preflight and preflight.get("status") == "LISTO"
            else "No existe un preflight remoto LISTO.",
        ),
        _check(
            "service_heartbeat",
            health is not None,
            f"Heartbeat observado: {health.get('status')}."
            if health
            else "No existe heartbeat del scanner.",
        ),
        _check(
            "alpaca_service_identity",
            bool(
                health
                and str(health.get("provider", "")).strip().upper() == "ALPACA"
                and expected_feed is not None
            ),
            f"Servicio ALPACA con feed {expected_feed}."
            if health
            and str(health.get("provider", "")).strip().upper() == "ALPACA"
            and expected_feed is not None
            else "El heartbeat no identifica un servicio ALPACA con feed iex o sip.",
        ),
        _check(
            "expected_symbols",
            bool(expected),
            "Simbolos evaluados: " + ", ".join(expected)
            if expected
            else "No se pudieron determinar los simbolos esperados.",
        ),
        _check(
            "real_bars_by_symbol",
            bool(expected) and all(item["bar_count"] >= 15 for item in bars),
            _bar_coverage_detail(bars),
        ),
        _check(
            "approved_reconciliation_by_symbol",
            bool(expected)
            and all(item["evidence_complete"] for item in reconciliations),
            _reconciliation_detail(reconciliations),
        ),
        _check(
            "no_open_processing_incidents",
            not incidents["open"],
            _incident_detail(incidents),
        ),
    ]
    failed = [item for item in checks if item["status"] == "ERROR"]
    hard_failure = any(
        item["name"] == "database_integrity" and item["status"] == "ERROR"
        for item in checks
    ) or any(
        item["status"] == "RECHAZADO"
        or (
            item["difference_count"] is not None
            and item["difference_count"] > 0
        )
        for item in reconciliations
    ) or bool(incidents["open"])
    if not failed:
        status = "APROBADO"
    elif hard_failure:
        status = "BLOQUEADO"
    elif preflight and preflight.get("status") == "LISTO":
        status = "EN_CURSO"
    else:
        status = "NO_INICIADO"

    process = read_instance_status(lock_file)
    return {
        "status": status,
        "evaluated_at": evaluated_at.astimezone(timezone.utc).isoformat(),
        "database": str(database_path),
        "session": {
            "preflight_run_id": preflight.get("_record_id") if preflight else None,
            "started_at": session_started_at,
            "scope": "EVIDENCIA_RECIBIDA_DESPUES_DEL_PREFLIGHT_REMOTO",
        },
        "symbols": list(expected),
        "feed": expected_feed,
        "checks": checks,
        "preflight": _safe_preflight(preflight),
        "process": process,
        "service_health": _safe_health(health),
        "bars": bars,
        "reconciliations": reconciliations,
        "processing_incidents": incidents,
        "next_actions": _next_actions(status, checks, reconciliations, incidents),
        "secrets_exposed": False,
        "paper_only": True,
        "real_trading_authorized": False,
        "order_execution": False,
        "authority": "EVIDENCIA_PAPER_NO_EJECUTA_ORDENES",
    }


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _latest_remote_preflight(
    connection: sqlite3.Connection,
) -> dict[str, Any] | None:
    if not _table_exists(connection, "live_preflight_runs"):
        return None
    row = connection.execute(
        "SELECT id, created_at, payload_json FROM live_preflight_runs "
        "WHERE status='LISTO' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    payload["_record_id"] = int(row["id"])
    payload["_created_at"] = str(row["created_at"])
    return payload


def _latest_health(
    connection: sqlite3.Connection,
    session_started_at: str | None,
) -> dict[str, Any] | None:
    if (
        session_started_at is None
        or not _table_exists(connection, "live_service_health")
    ):
        return None
    row = connection.execute(
        "SELECT * FROM live_service_health "
        "WHERE service_id='live_strategy_scanner' AND started_at>=? LIMIT 1",
        (session_started_at,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["symbols"] = json.loads(result.pop("symbols_json"))
    return result


def _expected_symbols(
    requested: tuple[str, ...], preflight: dict[str, Any] | None
) -> tuple[str, ...]:
    candidates = requested or tuple((preflight or {}).get("symbols", ()))
    return tuple(sorted({str(item).strip().upper() for item in candidates if str(item).strip()}))


def _expected_feed(health: dict[str, Any] | None) -> str | None:
    feed = str((health or {}).get("feed", "")).strip().lower()
    return feed if feed in {"iex", "sip"} else None


def _bar_evidence(
    connection: sqlite3.Connection,
    symbols: tuple[str, ...],
    feed: str | None,
    session_started_at: str | None,
) -> list[dict[str, Any]]:
    if (
        not symbols
        or session_started_at is None
        or not _table_exists(connection, "minute_bars")
    ):
        return [
            {
                "symbol": symbol,
                "feed": feed,
                "bar_count": 0,
                "latest_timestamp": None,
                "latest_received_at": None,
            }
            for symbol in symbols
        ]
    evidence = []
    for symbol in symbols:
        row = connection.execute(
            "SELECT COUNT(*) AS count, MAX(timestamp) AS latest, "
            "MAX(received_at) AS latest_received "
            "FROM minute_bars WHERE provider='ALPACA' AND symbol=? "
            "AND (? IS NULL OR feed=?) AND received_at>=?",
            (symbol, feed, feed, session_started_at),
        ).fetchone()
        evidence.append(
            {
                "symbol": symbol,
                "feed": feed,
                "bar_count": int(row["count"]),
                "latest_timestamp": row["latest"],
                "latest_received_at": row["latest_received"],
            }
        )
    return evidence


def _reconciliation_evidence(
    connection: sqlite3.Connection,
    symbols: tuple[str, ...],
    feed: str | None,
    bars: list[dict[str, Any]],
    session_started_at: str | None,
) -> list[dict[str, Any]]:
    if (
        not symbols
        or session_started_at is None
        or not _table_exists(connection, "market_reconciliations")
    ):
        return [
            {
                "symbol": symbol,
                "feed": feed,
                "status": "FALTANTE",
                "trigger_timestamp": None,
                "created_at": None,
                "difference_count": None,
                "temporally_coherent": False,
                "evidence_complete": False,
            }
            for symbol in symbols
        ]
    evidence = []
    bars_by_symbol = {item["symbol"]: item for item in bars}
    for symbol in symbols:
        row = connection.execute(
            "SELECT status, trigger_timestamp, difference_count, created_at "
            "FROM market_reconciliations "
            "WHERE provider='ALPACA' AND symbol=? "
            "AND (? IS NULL OR feed=?) AND created_at>=? "
            "ORDER BY id DESC LIMIT 1",
            (symbol, feed, feed, session_started_at),
        ).fetchone()
        status = str(row["status"]) if row else "FALTANTE"
        trigger = row["trigger_timestamp"] if row else None
        difference_count = int(row["difference_count"]) if row else None
        coherent = _timestamps_coherent(
            trigger,
            bars_by_symbol.get(symbol, {}).get("latest_timestamp"),
        )
        evidence.append(
            {
                "symbol": symbol,
                "feed": feed,
                "status": status,
                "trigger_timestamp": trigger,
                "created_at": row["created_at"] if row else None,
                "difference_count": difference_count,
                "temporally_coherent": coherent,
                "evidence_complete": (
                    status == "APROBADO"
                    and difference_count == 0
                    and coherent
                ),
            }
        )
    return evidence


def _timestamps_coherent(trigger: Any, latest_bar: Any) -> bool:
    if not trigger or not latest_bar:
        return False
    try:
        trigger_at = datetime.fromisoformat(str(trigger).replace("Z", "+00:00"))
        latest_at = datetime.fromisoformat(str(latest_bar).replace("Z", "+00:00"))
    except ValueError:
        return False
    if trigger_at.tzinfo is None or latest_at.tzinfo is None:
        return False
    return latest_at.astimezone(timezone.utc) >= trigger_at.astimezone(timezone.utc)


def _processing_incident_evidence(
    connection: sqlite3.Connection,
    symbols: tuple[str, ...],
    session_started_at: str | None,
) -> dict[str, Any]:
    """Resume incidentes sin exponer detalles de error en el reporte portable."""
    if (
        not symbols
        or session_started_at is None
        or not _table_exists(connection, "scanner_processing_incidents")
    ):
        return {"open": [], "resolved_in_session": [], "open_count": 0}
    placeholders = ",".join("?" for _ in symbols)
    rows = connection.execute(
        "SELECT id, symbol, bar_timestamp, created_at, stage, error_type, "
        "error_fingerprint, resolved_at, resolution_bar_timestamp, authority "
        "FROM scanner_processing_incidents "
        f"WHERE service_id='live_strategy_scanner' AND symbol IN ({placeholders}) "
        "AND (resolved_at IS NULL OR created_at>=?) ORDER BY id",
        (*symbols, session_started_at),
    ).fetchall()
    safe_rows = [dict(row) for row in rows]
    open_rows = [row for row in safe_rows if row["resolved_at"] is None]
    resolved_rows = [
        row
        for row in safe_rows
        if row["resolved_at"] is not None and row["created_at"] >= session_started_at
    ]
    return {
        "open": open_rows,
        "resolved_in_session": resolved_rows,
        "open_count": len(open_rows),
    }


def _safe_preflight(preflight: dict[str, Any] | None) -> dict[str, Any] | None:
    if preflight is None:
        return None
    return {
        "status": preflight.get("status"),
        "network_status": preflight.get("network_status"),
        "symbols": preflight.get("symbols", []),
        "secrets_exposed": bool(preflight.get("secrets_exposed", False)),
        "run_id": preflight.get("run_id"),
        "record_id": preflight.get("_record_id"),
        "created_at": preflight.get("_created_at"),
    }


def _safe_health(health: dict[str, Any] | None) -> dict[str, Any] | None:
    if health is None:
        return None
    return {
        field: health.get(field)
        for field in (
            "service_id",
            "provider",
            "feed",
            "symbols",
            "status",
            "started_at",
            "updated_at",
            "last_connected_at",
            "last_bar_at",
            "reconnect_count",
        )
    } | {"error_recorded": bool(health.get("last_error"))}


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    return {"name": name, "status": "OK" if passed else "ERROR", "detail": detail}


def _bar_coverage_detail(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No hay simbolos para comprobar barras ALPACA."
    covered = sum(item["bar_count"] >= 15 for item in items)
    return f"{covered}/{len(items)} simbolos con al menos 15 barras ALPACA."


def _reconciliation_detail(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No hay simbolos para comprobar reconciliacion."
    approved = sum(item["evidence_complete"] for item in items)
    return (
        f"{approved}/{len(items)} simbolos con reconciliacion APROBADO, "
        "cero diferencias y coherencia temporal."
    )


def _incident_detail(incidents: dict[str, Any]) -> str:
    count = int(incidents.get("open_count", 0))
    if count:
        return f"{count} incidente(s) de procesamiento sin recuperacion demostrada."
    resolved = len(incidents.get("resolved_in_session", []))
    return (
        "No hay incidentes de procesamiento abiertos; "
        f"{resolved} resuelto(s) durante la sesion."
    )


def _next_actions(
    status: str,
    checks: list[dict[str, str]],
    reconciliations: list[dict[str, Any]],
    incidents: dict[str, Any],
) -> list[str]:
    if status == "APROBADO":
        return [
            "Conservar el reporte y revisar manualmente las alertas de la sesion."
        ]
    if status == "BLOQUEADO":
        if incidents.get("open"):
            return [
                "Revisar el incidente del scanner y demostrar recuperacion con "
                "una vela posterior del mismo simbolo."
            ]
        if any(
            item["status"] == "RECHAZADO"
            or (
                item["difference_count"] is not None
                and item["difference_count"] > 0
            )
            for item in reconciliations
        ):
            return [
                "Revisar las diferencias WebSocket-REST antes de repetir la sesion."
            ]
        return ["Reparar el bloqueo de integridad antes de repetir la sesion."]
    failed = {item["name"] for item in checks if item["status"] == "ERROR"}
    actions = []
    if "remote_preflight" in failed:
        actions.append("Ejecutar el lanzador seguro con credenciales Alpaca.")
    if "service_heartbeat" in failed:
        actions.append("Iniciar el scanner PAPER y confirmar su heartbeat.")
    if "alpaca_service_identity" in failed:
        actions.append("Confirmar proveedor ALPACA y feed iex o sip.")
    if "real_bars_by_symbol" in failed:
        actions.append(
            "Mantener el scanner activo hasta acumular al menos 15 barras por simbolo."
        )
    if "approved_reconciliation_by_symbol" in failed:
        actions.append(
            "Esperar un cierre de 15 minutos y su reconciliacion WebSocket-REST."
        )
    return actions or ["Revisar los checks pendientes antes de repetir la captura."]


def _empty_payload(
    database: Path,
    evaluated_at: datetime,
    status: str,
    reasons: list[str],
    lock_file: str | Path,
) -> dict[str, Any]:
    return {
        "status": status,
        "evaluated_at": evaluated_at.astimezone(timezone.utc).isoformat(),
        "database": str(database),
        "session": {
            "preflight_run_id": None,
            "started_at": None,
            "scope": "EVIDENCIA_RECIBIDA_DESPUES_DEL_PREFLIGHT_REMOTO",
        },
        "symbols": [],
        "feed": None,
        "checks": [
            {"name": "database", "status": "ERROR", "detail": reason}
            for reason in reasons
        ],
        "preflight": None,
        "process": read_instance_status(lock_file),
        "service_health": None,
        "bars": [],
        "reconciliations": [],
        "processing_incidents": {
            "open": [],
            "resolved_in_session": [],
            "open_count": 0,
        },
        "next_actions": (
            ["Verificar o restaurar la base SQLite antes de repetir la sesion."]
            if status == "BLOQUEADO"
            else [
                "Ejecutar el lanzador seguro para iniciar la primera sesion PAPER."
            ]
        ),
        "secrets_exposed": False,
        "paper_only": True,
        "real_trading_authorized": False,
        "order_execution": False,
        "authority": "EVIDENCIA_PAPER_NO_EJECUTA_ORDENES",
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="exports/market_data.db")
    parser.add_argument("--symbols", default="", help="Simbolos separados por coma.")
    parser.add_argument("--lock-file", default="exports/live_scanner.lock")
    parser.add_argument("--output", help="Ruta opcional para el reporte JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = tuple(item.strip() for item in args.symbols.split(",") if item.strip())
    payload = build_paper_session_evidence(
        args.database,
        symbols=symbols,
        lock_file=args.lock_file,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "APROBADO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
