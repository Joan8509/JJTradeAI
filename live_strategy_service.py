"""Scanner continuo y auditable disparado por cierres de velas de 15 minutos."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import atexit
from threading import Event, Thread
from typing import Any, Iterator

import pandas as pd

from alpaca_market_data import (
    AlpacaMarketConfig,
    AlpacaMarketDataProvider,
    AlpacaStockBarStream,
    build_alpaca_data_bundle,
    build_alpaca_live_preview_bundle,
)
from live_market import MarketBar, closes_timeframe
from live_freshness import evaluate_live_freshness
from live_service_runtime import ResilientStreamSupervisor, ServiceHealthRepository
from live_bollinger_preview import (
    LiveBollingerPreviewRepository,
    attach_strategy_preview,
    evaluate_live_bollinger_preview,
)
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore, MarketContinuityService, LiveBarIngestion
from market_calendar import AlpacaMarketCalendarProvider, MarketSessionRepository, session_close_map
from market_context import build_market_context
from option_market_data import AlpacaOptionDataProvider
from option_opportunity import OptionOpportunityService, load_option_opportunity_policy
from news_context import AlpacaNewsProvider, build_news_context
from validation_runner import run_validation_bundle_assessment
from data_providers import DataBundle
from governance import GovernanceLimits, GovernanceRequest, OperationWorkflow, TradingMode, evaluate_governance
from learning_context import build_learning_context, context_from_report
from learning_engine import build_directional_learning_signal, build_learning_advisory
from live_preflight import record_live_preflight, run_live_preflight
from market_reconciliation import MarketDataReconciler, MarketReconciliationRepository
from alert_event import classify_alert_event, classify_alert_transition
from database_backup import create_sqlite_backup
from visual_evidence import DEFAULT_VISUAL_EVIDENCE_DIRECTORY
from visual_evidence_backup import create_visual_evidence_backup
from scanner_instance import ScannerInstanceLease, consume_stop_request
from scanner_incident import ScannerIncidentRepository
from safe_diagnostics import sanitize_diagnostic_detail
from setup_timing import evaluate_setup_timing
from paper_signal_evaluator import (
    build_paper_signal_advisory,
    build_paper_directional_learning_signal,
    evaluate_available_signals,
)
from watchlist_config import DEFAULT_BENCHMARKS_TEXT, DEFAULT_SYMBOLS_TEXT
from alpaca_polling_stream import AlpacaPollingBarStream


class AlertRepository:
    """Conserva una sola alerta por símbolo, feed y vela disparadora."""

    def __init__(self, database_path: str | Path = DEFAULT_MARKET_DATABASE) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    feed TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    trigger_timestamp TEXT NOT NULL,
                    data_as_of TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    detected_count INTEGER NOT NULL,
                    confirmed_count INTEGER NOT NULL,
                    event_type TEXT NOT NULL DEFAULT 'LEGACY',
                    event_priority TEXT NOT NULL DEFAULT 'INFO',
                    requires_ack INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL,
                    UNIQUE(provider, feed, symbol, trigger_timestamp)
                );
                CREATE TABLE IF NOT EXISTS alert_human_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    path_clear INTEGER,
                    news_clear INTEGER,
                    panorama_approved INTEGER,
                    notes TEXT NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id)
                );
                CREATE TABLE IF NOT EXISTS alert_reevaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    review_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(alert_id, review_id)
                );
                CREATE TABLE IF NOT EXISTS alert_contract_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    contract_symbol TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    notes TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_governance_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id)
                );
                CREATE TABLE IF NOT EXISTS alert_reevaluations_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    review_id INTEGER NOT NULL,
                    contract_selection_id INTEGER NOT NULL DEFAULT 0,
                    governance_review_id INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(alert_id, review_id, contract_selection_id, governance_review_id)
                );
                CREATE TABLE IF NOT EXISTS alert_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    reevaluation_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    trade_taken INTEGER NOT NULL,
                    result TEXT NOT NULL,
                    pnl REAL,
                    notes TEXT NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id),
                    FOREIGN KEY(reevaluation_id) REFERENCES alert_reevaluations_v2(id)
                );
                CREATE TABLE IF NOT EXISTS alert_acknowledgements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id)
                );
                CREATE INDEX IF NOT EXISTS idx_alert_acknowledgements_alert
                ON alert_acknowledgements (alert_id, id);
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(strategy_alerts)").fetchall()}
            for name, definition in (
                ("event_type", "TEXT NOT NULL DEFAULT 'LEGACY'"),
                ("event_priority", "TEXT NOT NULL DEFAULT 'INFO'"),
                ("requires_ack", "INTEGER NOT NULL DEFAULT 1"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE strategy_alerts ADD COLUMN {name} {definition}")
            legacy = connection.execute("SELECT id, payload_json FROM strategy_alerts WHERE event_type='LEGACY'").fetchall()
            for row in legacy:
                event = classify_alert_event(json.loads(row["payload_json"]))
                connection.execute(
                    "UPDATE strategy_alerts SET event_type=?, event_priority=?, requires_ack=? WHERE id=?",
                    (event["type"], event["priority"], int(event["requires_ack"]), row["id"]),
                )
            connection.execute(
                "INSERT OR IGNORE INTO alert_reevaluations_v2 "
                "(alert_id, review_id, created_at, decision, payload_json) "
                "SELECT alert_id, review_id, created_at, decision, payload_json FROM alert_reevaluations"
            )

    def exists(
        self, *, provider: str, feed: str, symbol: str, trigger_timestamp: datetime
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM strategy_alerts WHERE provider=? AND feed=? "
                "AND symbol=? AND trigger_timestamp=?",
                (
                    provider.strip().upper(),
                    feed.strip().lower(),
                    symbol.strip().upper(),
                    _utc_iso(trigger_timestamp),
                ),
            ).fetchone()
        return row is not None

    def record(
        self,
        *,
        provider: str,
        feed: str,
        symbol: str,
        trigger_timestamp: datetime,
        report: Mapping[str, Any],
    ) -> int | None:
        decision_payload = report.get("decision", {})
        if not isinstance(decision_payload, Mapping):
            decision_payload = {}
        summary = report.get("strategy_summary", {})
        if not isinstance(summary, Mapping):
            summary = {}
        decision = str(decision_payload.get("decision", "NO_OPERAR"))
        stored_report = dict(report)
        with self._connect() as connection:
            previous_row = connection.execute(
                "SELECT payload_json FROM strategy_alerts WHERE provider=? AND feed=? "
                "AND symbol=? AND trigger_timestamp<>? ORDER BY id DESC LIMIT 1",
                (
                    provider.strip().upper(), feed.strip().lower(),
                    symbol.strip().upper(), _utc_iso(trigger_timestamp),
                ),
            ).fetchone()
            previous_report = json.loads(previous_row["payload_json"]) if previous_row else None
            event = classify_alert_transition(stored_report, previous_report)
            stored_report["alert_event"] = event
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strategy_alerts (
                    created_at, provider, feed, symbol, trigger_timestamp,
                    data_as_of, decision, detected_count, confirmed_count,
                    event_type, event_priority, requires_ack,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    provider.strip().upper(),
                    feed.strip().lower(),
                    symbol.strip().upper(),
                    _utc_iso(trigger_timestamp),
                    str(report.get("data_as_of", "SIN_FECHA")),
                    decision,
                    int(summary.get("detected", 0)),
                    int(summary.get("confirmed", 0)),
                    str(event["type"]), str(event["priority"]), int(bool(event["requires_ack"])),
                    json.dumps(stored_report, ensure_ascii=False, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("El límite debe ser mayor que cero.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM strategy_alerts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{**dict(row), "report": json.loads(row["payload_json"])} for row in rows]

    def record_acknowledgement(self, alert_id: int, *, status: str, notes: str = "") -> int:
        """Versiona el acuse humano sin alterar la alerta."""
        normalized = status.strip().upper()
        if normalized not in {"VISTA", "ATENDIDA", "DESCARTADA"}:
            raise ValueError("El estado de acuse no es válido.")
        if normalized == "DESCARTADA" and not notes.strip():
            raise ValueError("Una alerta descartada requiere notas.")
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM strategy_alerts WHERE id=?", (alert_id,)).fetchone()
            if exists is None:
                raise ValueError(f"No existe la alerta {alert_id}.")
            cursor = connection.execute(
                "INSERT INTO alert_acknowledgements (alert_id, created_at, status, notes) VALUES (?, ?, ?, ?)",
                (alert_id, datetime.now(timezone.utc).isoformat(), normalized, notes.strip()),
            )
            return int(cursor.lastrowid)

    def acknowledgements(self, alert_id: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM alert_acknowledgements"
        parameters: tuple[int, ...] = ()
        if alert_id is not None:
            query += " WHERE alert_id=?"
            parameters = (alert_id,)
        query += " ORDER BY id DESC"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def unacknowledged_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM strategy_alerts a WHERE a.requires_ack=1 AND NOT EXISTS (SELECT 1 FROM alert_acknowledgements k WHERE k.alert_id=a.id)"
            ).fetchone()
        return int(row[0])

    def recent_unacknowledged(self, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("El límite debe ser mayor que cero.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT a.* FROM strategy_alerts a WHERE a.requires_ack=1 AND NOT EXISTS (SELECT 1 FROM alert_acknowledgements k WHERE k.alert_id=a.id) ORDER BY a.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{**dict(row), "report": json.loads(row["payload_json"])} for row in rows]

    def record_human_review(
        self,
        alert_id: int,
        *,
        path_clear: bool | None,
        news_clear: bool | None,
        panorama_approved: bool | None,
        notes: str = "",
    ) -> int:
        """Agrega evidencia humana sin sobrescribir revisiones anteriores."""
        if any(value is False for value in (path_clear, news_clear, panorama_approved)) and not notes.strip():
            raise ValueError("Una revisión rechazada requiere notas explicativas.")
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM strategy_alerts WHERE id=?", (alert_id,)
            ).fetchone()
            if exists is None:
                raise ValueError(f"No existe la alerta {alert_id}.")
            cursor = connection.execute(
                """
                INSERT INTO alert_human_reviews (
                    alert_id, created_at, path_clear, news_clear,
                    panorama_approved, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    datetime.now(timezone.utc).isoformat(),
                    _optional_bool(path_clear),
                    _optional_bool(news_clear),
                    _optional_bool(panorama_approved),
                    notes.strip(),
                ),
            )
            return int(cursor.lastrowid)

    def human_reviews(self, alert_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_human_reviews WHERE alert_id=? ORDER BY id DESC",
                (alert_id,),
            ).fetchall()
        return [
            {
                **dict(row),
                "path_clear": _stored_bool(row["path_clear"]),
                "news_clear": _stored_bool(row["news_clear"]),
                "panorama_approved": _stored_bool(row["panorama_approved"]),
            }
            for row in rows
        ]

    def record_reevaluation(self, alert_id: int, review_id: int, payload: Mapping[str, Any]) -> int | None:
        decision = str(payload.get("decision", {}).get("decision", "NO_OPERAR"))
        contract_selection_id = int(payload.get("contract_selection_id") or 0)
        governance_review_id = int(payload.get("governance_review_id") or 0)
        with self._connect() as connection:
            review = connection.execute(
                "SELECT alert_id FROM alert_human_reviews WHERE id=?",
                (review_id,),
            ).fetchone()
            if review is None or int(review["alert_id"]) != alert_id:
                raise ValueError("La revision humana no pertenece a la alerta.")
            if contract_selection_id:
                selection = connection.execute(
                    "SELECT alert_id FROM alert_contract_selections WHERE id=?",
                    (contract_selection_id,),
                ).fetchone()
                if selection is None or int(selection["alert_id"]) != alert_id:
                    raise ValueError(
                        "La seleccion de contrato no pertenece a la alerta."
                    )
            if governance_review_id:
                governance = connection.execute(
                    "SELECT alert_id FROM alert_governance_reviews WHERE id=?",
                    (governance_review_id,),
                ).fetchone()
                if governance is None or int(governance["alert_id"]) != alert_id:
                    raise ValueError(
                        "La revision de gobierno no pertenece a la alerta."
                    )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO alert_reevaluations_v2 (alert_id, review_id, contract_selection_id, governance_review_id, created_at, decision, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (alert_id, review_id, contract_selection_id, governance_review_id, datetime.now(timezone.utc).isoformat(), decision, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def reevaluations(self, alert_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM alert_reevaluations_v2 WHERE alert_id=? ORDER BY id DESC", (alert_id,)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def record_contract_selection(self, alert_id: int, contract_symbol: str, *, notes: str = "") -> int:
        """Selecciona explícitamente un candidato elegible del reporte original."""
        symbol = contract_symbol.strip().upper()
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM strategy_alerts WHERE id=?", (alert_id,)).fetchone()
            if row is None:
                raise ValueError(f"No existe la alerta {alert_id}.")
            report = json.loads(row["payload_json"])
            candidates = report.get("option_selection", {}).get("candidates", [])
            candidate = next((item for item in candidates if str(item.get("symbol", "")).upper() == symbol), None)
            if candidate is None:
                raise ValueError("El contrato no pertenece a los candidatos de la alerta.")
            if candidate.get("eligible") is not True:
                raise ValueError("El contrato seleccionado no es elegible.")
            cursor = connection.execute(
                "INSERT INTO alert_contract_selections (alert_id, created_at, contract_symbol, candidate_json, notes) VALUES (?, ?, ?, ?, ?)",
                (alert_id, datetime.now(timezone.utc).isoformat(), symbol, json.dumps(candidate, ensure_ascii=False, sort_keys=True), notes.strip()),
            )
            return int(cursor.lastrowid)

    def contract_selections(self, alert_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM alert_contract_selections WHERE alert_id=? ORDER BY id DESC", (alert_id,)).fetchall()
        return [{**dict(row), "candidate": json.loads(row["candidate_json"])} for row in rows]

    def record_governance_review(
        self,
        alert_id: int,
        request: GovernanceRequest,
        *,
        limits: GovernanceLimits = GovernanceLimits(),
        notes: str = "",
    ) -> int:
        """Eval\u00faa y conserva una aprobaci\u00f3n operativa sin ejecutar \u00f3rdenes."""
        with self._connect() as connection:
            alert = connection.execute(
                "SELECT symbol FROM strategy_alerts WHERE id=?", (alert_id,)
            ).fetchone()
            if alert is None:
                raise ValueError(f"No existe la alerta {alert_id}.")
            if request.symbol.strip().upper() != str(alert["symbol"]).upper():
                raise ValueError("La revisi\u00f3n de gobierno debe identificar el s\u00edmbolo de la alerta.")
            evaluation = evaluate_governance(request, limits)
            payload = {
                "symbol": request.symbol.strip().upper(),
                "mode": request.mode.value,
                "workflow": request.workflow.value,
                "watchlist_symbols": sorted({item.strip().upper() for item in request.watchlist_symbols if item.strip()}),
                "new_trades_this_week": request.new_trades_this_week,
                "weekly_trade_limit": limits.max_new_trades_per_week,
                "max_watchlist_symbols": limits.max_watchlist_symbols,
                "entry_plan": request.entry_plan.strip(),
                "exit_plan": request.exit_plan.strip(),
                "real_mode_acknowledged": request.real_mode_acknowledged,
            }
            cursor = connection.execute(
                "INSERT INTO alert_governance_reviews (alert_id, created_at, mode, workflow, status, request_json, reasons_json, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, datetime.now(timezone.utc).isoformat(), request.mode.value, request.workflow.value, evaluation.status.value, json.dumps(payload, ensure_ascii=False, sort_keys=True), json.dumps(evaluation.reasons, ensure_ascii=False), notes.strip()),
            )
            return int(cursor.lastrowid)

    def governance_reviews(self, alert_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_governance_reviews WHERE alert_id=? ORDER BY id DESC",
                (alert_id,),
            ).fetchall()
        return [
            {**dict(row), "request": json.loads(row["request_json"]), "reasons": json.loads(row["reasons_json"])}
            for row in rows
        ]

    def record_outcome(
        self,
        alert_id: int,
        reevaluation_id: int,
        *,
        mode: str,
        trade_taken: bool,
        result: str,
        pnl: float | None = None,
        notes: str = "",
    ) -> int:
        """Versiona el resultado informado para una reevaluación específica."""
        normalized_mode = mode.strip().upper()
        normalized_result = result.strip().upper()
        if normalized_mode not in {"PAPER", "REAL"}:
            raise ValueError("El modo debe ser PAPER o REAL.")
        allowed = {"POSITIVO", "NEGATIVO", "EMPATE", "NO_OPERADA"}
        if normalized_result not in allowed:
            raise ValueError("El resultado informado no es válido.")
        if trade_taken == (normalized_result == "NO_OPERADA"):
            raise ValueError("NO_OPERADA requiere trade_taken=False; los demás resultados requieren trade_taken=True.")
        if not trade_taken and pnl is not None:
            raise ValueError("Una operación no tomada no puede tener P&L.")
        with self._connect() as connection:
            reevaluation = connection.execute(
                "SELECT alert_id, governance_review_id "
                "FROM alert_reevaluations_v2 WHERE id=?",
                (reevaluation_id,),
            ).fetchone()
            if reevaluation is None or int(reevaluation["alert_id"]) != alert_id:
                raise ValueError("La reevaluación no pertenece a la alerta indicada.")
            governance_review_id = int(reevaluation["governance_review_id"])
            if governance_review_id:
                governance = connection.execute(
                    "SELECT alert_id, mode FROM alert_governance_reviews WHERE id=?",
                    (governance_review_id,),
                ).fetchone()
                if (
                    governance is None
                    or int(governance["alert_id"]) != alert_id
                ):
                    raise ValueError(
                        "La evidencia de gobierno de la reevaluacion no es valida."
                    )
                if str(governance["mode"]) != normalized_mode:
                    raise ValueError(
                        "El modo del resultado no coincide con el gobierno "
                        "vinculado a la reevaluacion."
                    )
            elif normalized_mode == "REAL":
                raise ValueError(
                    "Un resultado REAL requiere una revision de gobierno REAL "
                    "vinculada a la reevaluacion."
                )
            cursor = connection.execute(
                "INSERT INTO alert_outcomes (alert_id, reevaluation_id, created_at, mode, trade_taken, result, pnl, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, reevaluation_id, datetime.now(timezone.utc).isoformat(), normalized_mode, int(trade_taken), normalized_result, pnl, notes.strip()),
            )
            return int(cursor.lastrowid)

    def outcomes(self, alert_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_outcomes WHERE alert_id=? ORDER BY id DESC", (alert_id,)
            ).fetchall()
        return [{**dict(row), "trade_taken": bool(row["trade_taken"])} for row in rows]

    def alert_learning_records(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Entrega solo la última versión de feedback de cada reevaluación."""
        if mode is not None and mode not in {"PAPER", "REAL"}:
            raise ValueError("El modo debe ser PAPER o REAL.")
        query = """
            SELECT o.*, a.symbol, a.trigger_timestamp, a.payload_json AS alert_payload,
                   r.decision, r.payload_json AS reevaluation_payload
            FROM alert_outcomes o
            JOIN (SELECT reevaluation_id, MAX(id) AS latest_id FROM alert_outcomes GROUP BY reevaluation_id) latest
              ON latest.latest_id = o.id
            JOIN strategy_alerts a ON a.id = o.alert_id
            JOIN alert_reevaluations_v2 r ON r.id = o.reevaluation_id
        """
        parameters: tuple[str, ...] = ()
        if mode is not None:
            query += " WHERE o.mode=?"
            parameters = (mode,)
        query += " ORDER BY o.created_at, o.id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            report = json.loads(row["alert_payload"])
            reevaluation = json.loads(row["reevaluation_payload"])
            evaluations = report.get("strategies", {}).get("evaluations", [])
            context = context_from_report(report, str(row["decision"]))
            context["visual_confirmation"] = str(
                reevaluation.get("visual_evidence", {}).get(
                    "status", "NO_DISPONIBLE"
                )
            )
            records.append({
                "outcome_id": row["id"], "alert_id": row["alert_id"],
                "reevaluation_id": row["reevaluation_id"], "symbol": row["symbol"],
                "mode": row["mode"], "trade_taken": bool(row["trade_taken"]),
                "result": row["result"], "pnl": row["pnl"], "decision": row["decision"],
                "created_at": row["created_at"],
                "event_at": row["trigger_timestamp"],
                "methodology_version": str(report.get("methodology_version") or "SIN_VERSION"),
                "strategies": [
                    str(item.get("strategy_id"))
                    for item in evaluations
                    if item.get("detected") is True
                    and item.get("required_criteria_satisfied") is True
                ],
                "visual_evidence_status": context["visual_confirmation"],
                "context": context,
            })
        return records


Evaluator = Callable[[str, Any], dict[str, Any]]
ReportEnricher = Callable[[str, Any, Mapping[str, Any]], dict[str, Any]]


def detector_failure_from_report(
    report: Mapping[str, Any],
) -> RuntimeError | None:
    """Convierte errores controlados del pipeline en un fallo operativo auditable."""
    strategies = report.get("strategies", {})
    if not isinstance(strategies, Mapping):
        return RuntimeError("El reporte no contiene un bloque de estrategias valido.")
    errors = strategies.get("errors", {})
    if not isinstance(errors, Mapping):
        return RuntimeError("El bloque de errores de detectores no es valido.")
    normalized = [
        f"{str(detector).strip()}: {str(detail).strip()}"
        for detector, detail in sorted(errors.items(), key=lambda item: str(item[0]))
        if str(detector).strip()
    ]
    if not normalized:
        return None
    return RuntimeError(
        "Errores internos de detectores: " + " | ".join(normalized)
    )


def reconcile_scanner_result_incidents(
    repository: ScannerIncidentRepository,
    *,
    bar: MarketBar,
    result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Abre o resuelve incidentes solo cuando existe un analisis nuevo."""
    outcome: dict[str, Any] = {
        "incident_id": None,
        "resolved_count": 0,
        "failure": None,
    }
    if result is None or not closes_timeframe(bar.timestamp, "15m"):
        return outcome
    report = result.get("report")
    if not isinstance(report, Mapping):
        failure = RuntimeError("El resultado del scanner no contiene un reporte valido.")
    else:
        failure = detector_failure_from_report(report)
    if failure is not None:
        outcome["incident_id"] = repository.record(
            symbol=bar.symbol,
            bar_timestamp=bar.timestamp,
            error=failure,
            stage="DETECTORES",
        )
        outcome["failure"] = failure
        return outcome
    outcome["resolved_count"] = repository.resolve_open(
        symbol=bar.symbol,
        resolution_bar_timestamp=bar.timestamp,
    )
    return outcome


def bundle_daily_session_closed(bundle: Any) -> bool:
    """Confirma el cierre Diario solo si coincide con la sesión intradía."""
    closed_through = bundle.metadata.get("closed_through", {})
    if not isinstance(closed_through, Mapping) or "1D" not in closed_through or "15m" not in closed_through:
        return False
    try:
        return pd.Timestamp(closed_through["1D"]).date() == pd.Timestamp(closed_through["15m"]).date()
    except (TypeError, ValueError):
        return False


def _default_evaluator(symbol: str, bundle: Any) -> dict[str, Any]:
    daily_closed = bundle_daily_session_closed(bundle)
    _, report = run_validation_bundle_assessment(
        symbol=symbol,
        bundle=bundle,
        session_closed=daily_closed,
        data_current_review=bool(bundle.metadata.get("freshness_approved", False)),
    )
    return report


class ContinuousStrategyScanner:
    """Ingiere barras y evalúa exactamente una vez cada cierre de 15m."""

    def __init__(
        self,
        continuity: MarketContinuityService,
        alerts: AlertRepository,
        *,
        feed: str,
        evaluator: Evaluator = _default_evaluator,
        preview_evaluator: Evaluator = _default_evaluator,
        report_enricher: ReportEnricher | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        session_closes: Mapping[object, datetime] | None = None,
        benchmarks: tuple[str, ...] = (),
        news_provider: AlpacaNewsProvider | None = None,
        reconciler: MarketDataReconciler | None = None,
        reconciliation_repository: MarketReconciliationRepository | None = None,
    ) -> None:
        self.continuity = continuity
        self.alerts = alerts
        self.feed = feed
        self.evaluator = evaluator
        self.preview_evaluator = preview_evaluator
        self.report_enricher = report_enricher
        self.now = now
        self.session_closes = session_closes
        self.benchmarks = benchmarks
        self.news_provider = news_provider
        self.reconciler = reconciler
        self.reconciliation_repository = reconciliation_repository

    def on_bar(self, bar: MarketBar, *, already_persisted=False) -> dict[str, Any] | None:
        if already_persisted:
            if not bar.complete:
                raise ValueError('No se analizan barras todavía abiertas.')
            ingestion=LiveBarIngestion(bar.symbol,bar.timestamp,
                closes_timeframe(bar.timestamp,'15m'),closes_timeframe(bar.timestamp,'1H'))
        else:
            ingestion = self.continuity.ingest_live_bar(bar)
        minute_bars = self.continuity.store.load_frame(
            symbol=bar.symbol,
            provider=self.continuity.provider_name,
            feed=self.feed,
            end=bar.timestamp,
        )
        if already_persisted:
            # A queued original bar may have received an official update while
            # analysis was busy. Read that canonical revision; never overwrite
            # it by ingesting the old queued bar again.
            exact=minute_bars[minute_bars.date==pd.Timestamp(bar.timestamp)]
            if exact.empty:
                raise ValueError('Falta la barra persistida para analizar.')
            row=exact.iloc[-1]
            bar=MarketBar(bar.symbol,bar.timestamp,float(row.open),float(row.high),
                          float(row.low),float(row.close),float(row.volume))
        preview = evaluate_live_bollinger_preview(
            minute_bars, symbol=bar.symbol, as_of=bar.timestamp
        )
        try:
            preview_report = self.preview_evaluator(
                bar.symbol,
                build_alpaca_live_preview_bundle(
                    minute_bars, symbol=bar.symbol, feed=self.feed
                ),
            )
            preview = attach_strategy_preview(preview, preview_report)
        except Exception as error:
            preview["preview_error"] = sanitize_diagnostic_detail(error)
        LiveBollingerPreviewRepository(
            self.continuity.store.database_path
        ).save(preview)
        if not ingestion.closes_15m:
            return None
        if self.alerts.exists(
            provider=self.continuity.provider_name,
            feed=self.feed,
            symbol=bar.symbol,
            trigger_timestamp=bar.timestamp,
        ):
            return None
        bundle = build_alpaca_data_bundle(
            minute_bars,
            symbol=bar.symbol,
            feed=self.feed,
            session_closes=self.session_closes,
        )
        freshness = evaluate_live_freshness(
            bar,
            minute_bars,
            feed=self.feed,
            checked_at=self.now(),
        )
        if self.reconciler is None:
            reconciliation = {
                "status": "OMITIDO", "difference_count": 0,
                "detail": "Reconciliación REST no configurada.",
                "authority": "CALIDAD_DE_DATOS_NO_CORRIGE_PRECIOS",
            }
        else:
            reconciliation = self.reconciler.reconcile(
                bar.symbol, start=bar.timestamp - timedelta(minutes=14),
                end=bar.timestamp, local=minute_bars,
            )
            repository = self.reconciliation_repository or MarketReconciliationRepository(self.continuity.store.database_path)
            reconciliation["id"] = repository.record(
                provider=self.continuity.provider_name, feed=self.feed,
                symbol=bar.symbol, trigger_timestamp=bar.timestamp, payload=reconciliation,
            )
        reconciliation_approved = reconciliation["status"] in {"APROBADO", "OMITIDO"}
        effective_freshness = freshness.status.value == "APROBADO" and reconciliation_approved
        bundle = DataBundle(
            provider=bundle.provider,
            datasets=bundle.datasets,
            auxiliary_datasets=bundle.auxiliary_datasets,
            metadata={
                **bundle.metadata,
                "freshness_approved": effective_freshness,
            },
        )
        report = self.evaluator(bar.symbol, bundle)
        report["live_data_freshness"] = {
            "status": "APROBADO" if effective_freshness else "RECHAZADO",
            "checked_at": freshness.checked_at.isoformat(),
            "bar_timestamp": freshness.bar_timestamp.isoformat(),
            "age_seconds": freshness.age_seconds,
            "feed": freshness.feed,
            "latest_persisted_matches": freshness.latest_persisted_matches,
            "recent_gap_count": freshness.recent_gap_count,
            "issues": list(freshness.issues) + ([] if reconciliation_approved else ["La reconciliación WebSocket–REST no fue aprobada."]),
        }
        report["market_data_reconciliation"] = reconciliation
        if self.benchmarks:
            report["market_context"] = build_market_context(
                self.continuity.store,
                self.benchmarks,
                provider=self.continuity.provider_name,
                feed=self.feed,
                trigger_timestamp=bar.timestamp,
                session_closes=dict(self.session_closes or {}),
            )
        if self.news_provider is not None:
            try:
                report["news_context"] = build_news_context(
                    self.news_provider, bar.symbol, as_of=bar.timestamp
                )
            except Exception as error:
                report["news_context"] = {
                    "status": "NO_DISPONIBLE",
                    "article_count": 0,
                    "reason": sanitize_diagnostic_detail(error),
                    "articles": [],
                }
        if self.report_enricher is not None:
            report = self.report_enricher(bar.symbol, bundle, report)
        decision_payload = report.get("decision", {})
        decision = str(decision_payload.get("decision", "NO_OPERAR")) if isinstance(decision_payload, Mapping) else "NO_OPERAR"
        report["learning_context"] = build_learning_context(
            bundle.datasets["15m"],
            decision=decision,
            market_context=report.get("market_context", {}),
            trigger_timestamp=bar.timestamp,
        )
        evaluations = report.get("strategies", {}).get("evaluations", [])
        detected_strategies = [
            str(item.get("strategy_id")) for item in evaluations
            if isinstance(item, Mapping) and item.get("detected") is True
        ]
        confirmed_strategies = [
            str(item.get("strategy_id")) for item in evaluations
            if isinstance(item, Mapping)
            and item.get("detected") is True
            and item.get("required_criteria_satisfied") is True
        ]
        report["paper_signal_advisory"] = build_paper_signal_advisory(
            self.continuity.store.database_path,
            strategy_ids=detected_strategies,
            as_of=bar.timestamp,
            methodology_version=str(report.get("methodology_version", "")),
        )
        report["learning_advisory"] = build_learning_advisory(
            self.alerts.alert_learning_records(), strategy_ids=confirmed_strategies,
            context=report["learning_context"], as_of=bar.timestamp,
            methodology_version=str(report.get("methodology_version", "")),
        )
        evaluate_available_signals(
            self.continuity.store.database_path,
            horizons=(60,), symbols=(bar.symbol,),
        )
        report["automatic_learning_signal"] = build_paper_directional_learning_signal(
            self.continuity.store.database_path,
            strategy_ids=confirmed_strategies,
            current_direction=decision,
            as_of=bar.timestamp,
            methodology_version=str(report.get("methodology_version", "")),
        )
        report["directional_learning_signal"] = build_directional_learning_signal(
            self.alerts.alert_learning_records(), strategy_ids=confirmed_strategies,
            context=report["learning_context"],
            current_direction=decision,
            as_of=bar.timestamp,
            methodology_version=str(report.get("methodology_version", "")),
        )
        report["setup_timing"] = evaluate_setup_timing(report)
        report["alert_event"] = classify_alert_event(report)
        alert_id = self.alerts.record(
            provider=self.continuity.provider_name,
            feed=self.feed,
            symbol=bar.symbol,
            trigger_timestamp=bar.timestamp,
            report=report,
        )
        persisted_event = report.get("alert_event", {})
        if alert_id is not None:
            latest = self.alerts.recent(limit=1)
            if latest and int(latest[0]["id"]) == int(alert_id):
                persisted_event = latest[0]["report"].get("alert_event", persisted_event)
        return {"alert_id": alert_id, "report": report, "alert_event": persisted_event}


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("El timestamp de alerta debe incluir zona horaria.")
    return value.astimezone(timezone.utc).isoformat()


def _optional_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _stored_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS_TEXT, help="Símbolos separados por coma.")
    parser.add_argument("--days", type=int, default=365, help="Backfill inicial.")
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        help="Detiene cooperativamente el scanner tras esta duración.",
    )
    parser.add_argument("--database", default=str(DEFAULT_MARKET_DATABASE))
    parser.add_argument("--data-only", action="store_true", help="Solo ingiere datos y actualiza el radar de precios; no evalúa los otros detectores.")
    parser.add_argument("--transport", choices=("auto", "websocket", "polling"), default="auto")
    parser.add_argument(
        "--benchmarks",
        default=DEFAULT_BENCHMARKS_TEXT,
        help="ETFs de contexto separados por coma.",
    )
    parser.add_argument(
        "--option-policy",
        help="JSON explícito de límites para enriquecer alertas con opciones.",
    )
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="Valida configuración local y termina sin consultar Alpaca.",
    )
    parser.add_argument("--backup-directory", default="exports/backups")
    parser.add_argument("--backup-retention", type=int, default=30)
    parser.add_argument("--no-startup-backup", action="store_true")
    parser.add_argument("--lock-file", default="exports/live_scanner.lock")
    parser.add_argument("--stop-file", default="exports/live_scanner.stop")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbols = sorted({item.strip().upper() for item in args.symbols.split(",") if item.strip()})
    benchmarks = tuple(sorted({item.strip().upper() for item in args.benchmarks.split(",") if item.strip()}))
    if not symbols or args.days <= 0:
        raise SystemExit("Indica símbolos y un número de días válido.")
    if args.max_runtime_minutes is not None and args.max_runtime_minutes <= 0:
        raise SystemExit("--max-runtime-minutes debe ser mayor que cero.")
    preflight = run_live_preflight(
        symbols=tuple(symbols), benchmarks=benchmarks, days=args.days,
        database=args.database, option_policy=args.option_policy,
    )
    if any(item["name"] == "database" and item["status"] == "OK" for item in preflight["checks"]):
        preflight["run_id"] = record_live_preflight(args.database, preflight)
    print(json.dumps(preflight, ensure_ascii=False, indent=2))
    if preflight["status"] == "BLOQUEADO":
        return 2
    if args.preflight_only:
        return 0
    if args.backup_retention <= 0:
        print("Backup BLOQUEADO: --backup-retention debe ser mayor que cero.")
        return 2
    lease = ScannerInstanceLease(args.lock_file)
    try:
        metadata = lease.acquire()
    except RuntimeError as error:
        print(f"Scanner BLOQUEADO: {sanitize_diagnostic_detail(error)}")
        return 4
    atexit.register(lease.release)
    print(f"Lease de scanner adquirido: PID {metadata['pid']}")
    if not args.no_startup_backup:
        backup = create_sqlite_backup(
            args.database, args.backup_directory, retention=args.backup_retention
        )
        print(f"Backup previo verificado: {backup['backup_path']}")
        visual_backup = create_visual_evidence_backup(
            backup["backup_path"],
            DEFAULT_VISUAL_EVIDENCE_DIRECTORY,
        )
        print(
            "Backup visual verificado: "
            f"{visual_backup['backup_path']} "
            f"evidencias={visual_backup['evidence_count']}"
        )
    config = AlpacaMarketConfig.from_env()
    provider = AlpacaMarketDataProvider(config)
    store = MarketBarStore(args.database)
    continuity = MarketContinuityService(
        store, provider, provider_name="ALPACA", feed=config.feed
    )
    end = datetime.now(timezone.utc)
    try:
        sessions = AlpacaMarketCalendarProvider(config).fetch_sessions(
            (end - timedelta(days=args.days)).date(),
            (end + timedelta(days=30)).date(),
        )
    except Exception as error:
        preflight["status"] = "BLOQUEADO"
        preflight["network_status"] = "ERROR"
        preflight["checks"].append(
            {
                "name": "alpaca_calendar",
                "status": "ERROR",
                "detail": sanitize_diagnostic_detail(error),
            }
        )
        preflight["run_id"] = record_live_preflight(args.database, preflight)
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        lease.release()
        return 3
    preflight["status"] = "LISTO"
    preflight["network_status"] = "OK"
    preflight["checks"].append({"name": "alpaca_calendar", "status": "OK", "detail": f"Calendario oficial disponible: {len(sessions)} sesiones."})
    preflight["run_id"] = record_live_preflight(args.database, preflight)
    MarketSessionRepository(args.database).upsert(sessions)
    official_closes = session_close_map(sessions)
    stream_symbols = sorted(set(symbols).union(benchmarks))
    for symbol in stream_symbols:
        recovered = continuity.recover(
            symbol, end=end, initial_lookback=timedelta(days=args.days)
        )
        print(f"{symbol}: backfill={recovered}")
    report_enricher = None
    if args.option_policy:
        option_policy = load_option_opportunity_policy(args.option_policy)
        option_service = OptionOpportunityService(
            AlpacaOptionDataProvider(config, option_feed=option_policy.option_feed),
            option_policy,
        )
        report_enricher = option_service.enrich
    scanner = ContinuousStrategyScanner(
        continuity,
        AlertRepository(args.database),
        feed=config.feed,
        report_enricher=report_enricher,
        session_closes=official_closes,
        benchmarks=benchmarks,
        news_provider=AlpacaNewsProvider(config),
        reconciler=MarketDataReconciler(provider, attempts=3, retry_delay=0.75),
    )
    incident_repository = ScannerIncidentRepository(args.database)

    def handle_bar(bar: MarketBar) -> None:
        if bar.symbol not in symbols:
            continuity.ingest_live_bar(bar)
            return
        try:
            if args.data_only:
                if realtime_worker is None:
                    continuity.ingest_live_bar(bar)
                minute_bars = store.load_frame(symbol=bar.symbol, provider="ALPACA", feed=config.feed, end=bar.timestamp)
                preview = evaluate_live_bollinger_preview(minute_bars, symbol=bar.symbol, as_of=bar.timestamp)
                LiveBollingerPreviewRepository(args.database).save(preview)
                return
            result = scanner.on_bar(bar,already_persisted=realtime_worker is not None)
        except Exception as error:
            incident_id = incident_repository.record(
                symbol=bar.symbol,
                bar_timestamp=bar.timestamp,
                error=error,
            )
            print(
                f"Scanner {bar.symbol}: incidente #{incident_id} "
                f"{sanitize_diagnostic_detail(error)}"
            )
            return
        incident_outcome = reconcile_scanner_result_incidents(
            incident_repository,
            bar=bar,
            result=result,
        )
        if incident_outcome["incident_id"] is not None:
            print(
                f"Scanner {bar.symbol}: incidente metodologico "
                f"#{incident_outcome['incident_id']} "
                f"{sanitize_diagnostic_detail(incident_outcome['failure'])}"
            )
        if incident_outcome["resolved_count"]:
            print(
                f"Scanner {bar.symbol}: "
                f"{incident_outcome['resolved_count']} incidente(s) resuelto(s) "
                "tras cierre procesado."
            )
        if result:
            report = result["report"]
            summary = report["strategy_summary"]
            event = result.get("alert_event", {})
            prefix = "ALERTA" if event.get("requires_ack") else "REGISTRO"
            print(
                f"{prefix} #{result['alert_id']} {bar.symbol} {report['data_as_of']} "
                f"evento={event.get('type', 'NO_CLASIFICADO')} "
                f"decision={report['decision']['decision']} "
                f"detectadas={summary['detected']} confirmadas={summary['confirmed']}"
            )
            try:
                paper_evaluation = evaluate_available_signals(
                    args.database,
                    horizons=(15, 30, 60),
                    neutral_threshold_pct=0.05,
                    symbols=(bar.symbol,),
                )
                if paper_evaluation["inserted"]:
                    print(
                        f"PAPER {bar.symbol}: "
                        f"{paper_evaluation['inserted']} evaluacion(es) posterior(es) guardada(s)."
                    )
            except Exception as error:
                print(
                    f"Evaluador PAPER {bar.symbol}: "
                    f"{sanitize_diagnostic_detail(error)}"
                )

    use_polling = args.transport == 'polling' or (args.transport == 'auto' and len(stream_symbols) > 30)
    realtime_worker = None
    if not use_polling:
        from bollinger_tick_stream import RealtimeBollingerWorker, RealtimeBollingerStream
        realtime_worker = RealtimeBollingerWorker(args.database, config.feed, stream_symbols)
    supervisor = ResilientStreamSupervisor(
        stream_factory=lambda: AlpacaPollingBarStream(config, continuity=continuity)
        if use_polling else RealtimeBollingerStream(config, realtime_worker),
        continuity=continuity,
        health=ServiceHealthRepository(args.database),
    )
    monitor_finished = Event()

    def monitor_stop_request() -> None:
        while not monitor_finished.wait(1.0):
            if consume_stop_request(args.stop_file, owner_token=lease.token):
                print("Parada cooperativa solicitada.")
                supervisor.stop()
                return

    stop_monitor = Thread(target=monitor_stop_request, name="scanner-stop-monitor", daemon=True)
    stop_monitor.start()
    if args.max_runtime_minutes is not None:
        def stop_after_deadline() -> None:
            if not monitor_finished.wait(args.max_runtime_minutes * 60):
                print("Duración PAPER completada; iniciando parada cooperativa.")
                supervisor.stop()

        Thread(
            target=stop_after_deadline,
            name="scanner-runtime-deadline",
            daemon=True,
        ).start()
    print(f"Scanner activo: {', '.join(symbols)} feed={config.feed}. Ctrl+C para salir.")
    try:
        supervisor.run(stream_symbols, handle_bar)
    except KeyboardInterrupt:
        supervisor.stop()
    finally:
        monitor_finished.set()
        if realtime_worker is not None:
            realtime_worker.close()
        Path(args.stop_file).unlink(missing_ok=True)
        lease.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
