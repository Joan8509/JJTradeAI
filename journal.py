"""Persistencia local y auditable para análisis y operaciones de JJTrade AI."""

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


DEFAULT_DATABASE = Path(__file__).resolve().parent / "exports" / "jjtrade_journal.db"


class JournalRepository:
    """Administra análisis y resultados sin modificar reglas metodológicas."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Entrega una conexión transaccional y garantiza su cierre físico."""
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    data_as_of TEXT NOT NULL,
                    methodology_version TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    strategies_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_id INTEGER NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    action TEXT NOT NULL,
                    contract_symbol TEXT,
                    strike REAL,
                    expiration TEXT,
                    contracts INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    fees REAL NOT NULL DEFAULT 0,
                    pnl REAL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
                );

                CREATE TABLE IF NOT EXISTS report_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    data_as_of TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    readiness TEXT NOT NULL,
                    learning_ready INTEGER NOT NULL,
                    missing_evidence_json TEXT NOT NULL,
                    blockers_json TEXT NOT NULL,
                    detected_strategies_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self._add_column_if_missing(
                connection, "trades", "mode", "TEXT NOT NULL DEFAULT 'PAPER'"
            )
            self._add_column_if_missing(
                connection,
                "trades",
                "workflow",
                "TEXT NOT NULL DEFAULT 'NUEVA_ENTRADA'",
            )
            self._add_column_if_missing(
                connection, "trades", "entry_plan", "TEXT NOT NULL DEFAULT ''"
            )
            self._add_column_if_missing(
                connection, "trades", "exit_plan", "TEXT NOT NULL DEFAULT ''"
            )
            self._add_column_if_missing(
                connection, "trades", "decision_followed", "INTEGER"
            )
            self._add_column_if_missing(
                connection, "trades", "override_reason", "TEXT NOT NULL DEFAULT ''"
            )

    @staticmethod
    def _add_column_if_missing(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        """Aplica migraciones aditivas compatibles con diarios existentes."""
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    @staticmethod
    def _load_json_mapping(value: str) -> dict[str, Any]:
        """Lee JSON de registros antiguos sin tumbar la vista del diario."""
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_json_list(value: str) -> list[Any]:
        """Lee listas JSON heredadas y usa vacio si el dato fue editado a mano."""
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _payload_int(payload: Mapping[str, Any], key: str) -> int:
        """Normaliza conteos históricos que pudieron guardarse como texto inválido."""
        try:
            return int(payload.get(key, 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _join_text_values(value: Any) -> str:
        """Normaliza valores guardados como lista o texto heredado."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return "|".join(str(item) for item in value if item)
        return str(value)

    @classmethod
    def _analysis_audit_readiness(cls, payload_json: str) -> str:
        """Extrae la auditoria inmediata guardada sin romper registros antiguos."""
        payload = cls._load_json_mapping(payload_json)
        report_audit = payload.get("report_audit", {})
        if not isinstance(report_audit, Mapping):
            return ""
        return str(report_audit.get("readiness", ""))

    def record_analysis(
        self,
        *,
        symbol: str,
        data_as_of: str,
        methodology_version: str,
        decision: str,
        confidence: str,
        strategies: Sequence[str],
        payload: Mapping[str, Any],
    ) -> int:
        """Guarda una evaluación completa y devuelve su identificador."""
        if not symbol.strip():
            raise ValueError("El símbolo es obligatorio.")
        if not str(data_as_of).strip():
            raise ValueError("data_as_of es obligatorio.")
        if not str(methodology_version).strip():
            raise ValueError("La versión metodológica es obligatoria.")
        if decision not in {"CALL", "PUT", "NO_OPERAR"}:
            raise ValueError("La decisión del análisis no es válida.")
        if not str(confidence).strip():
            raise ValueError("La confianza del análisis es obligatoria.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analyses (
                    created_at, symbol, data_as_of, methodology_version,
                    decision, confidence, strategies_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    symbol.strip().upper(),
                    data_as_of,
                    methodology_version,
                    decision,
                    confidence,
                    json.dumps(list(strategies), ensure_ascii=False),
                    json.dumps(dict(payload), ensure_ascii=False, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def record_report_audit(
        self,
        *,
        symbol: str,
        data_as_of: str,
        decision: str,
        readiness: str,
        learning_ready: bool,
        missing_evidence: Sequence[str],
        blockers: Sequence[str],
        detected_strategies: Sequence[str],
        payload: Mapping[str, Any],
    ) -> int:
        """Guarda una auditoría de reporte sin crear operación ni señal nueva."""
        if not symbol.strip():
            raise ValueError("El símbolo es obligatorio.")
        if not str(data_as_of).strip():
            raise ValueError("data_as_of es obligatorio.")
        if decision not in {"CALL", "PUT", "NO_OPERAR"}:
            raise ValueError("La decisión auditada no es válida.")
        if readiness not in {"LISTO_REVISION", "INCOMPLETO", "BLOQUEADO"}:
            raise ValueError("El estado de auditoría no es válido.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO report_audits (
                    created_at, symbol, data_as_of, decision, readiness,
                    learning_ready, missing_evidence_json, blockers_json,
                    detected_strategies_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    symbol.strip().upper(),
                    data_as_of,
                    decision,
                    readiness,
                    int(learning_ready),
                    json.dumps(list(missing_evidence), ensure_ascii=False),
                    json.dumps(list(blockers), ensure_ascii=False),
                    json.dumps(list(detected_strategies), ensure_ascii=False),
                    json.dumps(dict(payload), ensure_ascii=False, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def record_trade(
        self,
        *,
        analysis_id: int,
        action: str,
        contracts: int,
        entry_price: float,
        contract_symbol: str | None = None,
        strike: float | None = None,
        expiration: str | None = None,
        notes: str = "",
        mode: str = "PAPER",
        workflow: str = "NUEVA_ENTRADA",
        entry_plan: str = "",
        exit_plan: str = "",
        override_reason: str = "",
        real_mode_acknowledged: bool = False,
    ) -> int:
        """Registra una operación realmente tomada por el usuario."""
        if action not in {"CALL", "PUT"}:
            raise ValueError("La acción debe ser CALL o PUT.")
        if contracts <= 0 or entry_price < 0:
            raise ValueError("Contratos y precio de entrada deben ser válidos.")
        if mode not in {"PAPER", "REAL"}:
            raise ValueError("El modo debe ser PAPER o REAL.")
        if mode == "REAL" and not real_mode_acknowledged:
            raise ValueError("El modo REAL requiere aceptación humana explícita.")
        if workflow not in {"NUEVA_ENTRADA", "GESTION_POSICION", "REFUERZO"}:
            raise ValueError("El flujo operativo no es válido.")
        with self._connect() as connection:
            analysis = connection.execute(
                "SELECT decision, payload_json FROM analyses WHERE id = ?",
                (analysis_id,),
            ).fetchone()
            if analysis is None:
                raise ValueError(f"No existe el análisis {analysis_id}.")
            decision_followed = analysis["decision"] == action
            audit_readiness = self._analysis_audit_readiness(analysis["payload_json"])
            requires_audit_override = audit_readiness in {
                "INCOMPLETO",
                "BLOQUEADO",
            }
            if (not decision_followed or requires_audit_override) and not override_reason.strip():
                raise ValueError(
                    "Una operación que no sigue la decisión o usa un análisis incompleto requiere justificar la excepción."
                )
            cursor = connection.execute(
                """
                INSERT INTO trades (
                    analysis_id, opened_at, action, contract_symbol, strike,
                    expiration, contracts, entry_price, status, notes,
                    mode, workflow, entry_plan, exit_plan,
                    decision_followed, override_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ABIERTA', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    datetime.now(timezone.utc).isoformat(),
                    action,
                    contract_symbol,
                    strike,
                    expiration,
                    contracts,
                    entry_price,
                    notes,
                    mode,
                    workflow,
                    entry_plan,
                    exit_plan,
                    int(decision_followed),
                    override_reason,
                ),
            )
            return int(cursor.lastrowid)

    def record_planned_trade(self, **trade: Any) -> int:
        """Registra una operación solo cuando existe plan previo completo."""
        entry_plan = str(trade.get("entry_plan", "")).strip()
        exit_plan = str(trade.get("exit_plan", "")).strip()
        if not entry_plan or not exit_plan:
            raise ValueError("Los planes de entrada y salida son obligatorios.")
        if trade.get("workflow", "NUEVA_ENTRADA") == "REFUERZO":
            raise ValueError("REFUERZO no está habilitado en esta versión.")
        analysis_id = int(trade.get("analysis_id", 0))
        action = str(trade.get("action", ""))
        with self._connect() as connection:
            analysis = connection.execute(
                "SELECT decision, payload_json FROM analyses WHERE id = ?",
                (analysis_id,),
            ).fetchone()
        if analysis is None:
            raise ValueError(f"No existe el análisis {analysis_id}.")
        audit_readiness = self._analysis_audit_readiness(analysis["payload_json"])
        requires_audit_override = audit_readiness in {"INCOMPLETO", "BLOQUEADO"}
        if (
            analysis["decision"] != action or requires_audit_override
        ) and not str(trade.get("override_reason", "")).strip():
            raise ValueError(
                "Una operación que no sigue la decisión o usa un análisis incompleto requiere justificar la excepción."
            )
        return self.record_trade(**trade)

    def close_trade(
        self, trade_id: int, *, exit_price: float, fees: float = 0
    ) -> None:
        """Cierra una operación y calcula P&L usando el multiplicador 100."""
        if exit_price < 0 or fees < 0:
            raise ValueError("Precio de salida y comisiones deben ser válidos.")
        with self._connect() as connection:
            trade = connection.execute(
                "SELECT contracts, entry_price, status FROM trades WHERE id = ?",
                (trade_id,),
            ).fetchone()
            if trade is None:
                raise ValueError(f"No existe la operación {trade_id}.")
            if trade["status"] != "ABIERTA":
                raise ValueError("La operación ya está cerrada.")
            pnl = (exit_price - trade["entry_price"]) * trade["contracts"] * 100 - fees
            connection.execute(
                """
                UPDATE trades
                SET closed_at = ?, exit_price = ?, fees = ?, pnl = ?, status = 'CERRADA'
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), exit_price, fees, pnl, trade_id),
            )

    def list_recent_analyses(self, limit: int = 50) -> list[dict[str, Any]]:
        """Lista análisis guardados para vincularlos con una operación."""
        if limit <= 0:
            raise ValueError("El límite debe ser mayor que cero.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, symbol, data_as_of, decision,
                       confidence, strategies_json, payload_json
                FROM analyses ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        analyses: list[dict[str, Any]] = []
        for row in rows:
            payload = self._load_json_mapping(row["payload_json"])
            decision_payload = payload.get("decision", {})
            if not isinstance(decision_payload, Mapping):
                decision_payload = {}
            data_source = payload.get("data_source", {})
            if not isinstance(data_source, Mapping):
                data_source = {}
            data_source_files = data_source.get("files", {})
            if not isinstance(data_source_files, Mapping):
                data_source_files = {}
            report_audit = payload.get("report_audit", {})
            if not isinstance(report_audit, Mapping):
                report_audit = {}
            analyses.append(
                {
                    **dict(row),
                    "strategies": self._load_json_list(row["strategies_json"]),
                    "data_provider": str(data_source.get("provider") or ""),
                    "data_source_timeframes": self._join_text_values(
                        data_source.get("timeframes", ())
                    ),
                    "data_source_files": "|".join(
                        f"{timeframe}:{path}"
                        for timeframe, path in sorted(data_source_files.items())
                    ),
                    "audit_readiness": str(report_audit.get("readiness", "")),
                    "audit_learning_ready": bool(
                        report_audit.get("learning_ready", False)
                    ),
                    "audit_missing_gate_count": self._payload_int(
                        report_audit, "missing_gate_count"
                    ),
                    "audit_missing_strategy_count": self._payload_int(
                        report_audit, "missing_strategy_count"
                    ),
                    "audit_missing_invalidation_count": self._payload_int(
                        report_audit, "missing_invalidation_count"
                    ),
                    "audit_blocker_gate_count": self._payload_int(
                        report_audit, "blocker_gate_count"
                    ),
                    "audit_blocker_invalidation_count": self._payload_int(
                        report_audit, "blocker_invalidation_count"
                    ),
                    "audit_blocker_detector_count": self._payload_int(
                        report_audit, "blocker_detector_count"
                    ),
                    "tentative_bias": str(
                        decision_payload.get(
                            "tentative_bias", payload.get("tentative_bias", "")
                        )
                        or ""
                    ),
                    "tentative_strategies": self._join_text_values(
                        decision_payload.get(
                            "tentative_strategies",
                            payload.get("tentative_strategies", ()),
                        )
                    ),
                }
            )
        return analyses

    def list_recent_report_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        """Lista auditorías de reportes guardadas."""
        if limit <= 0:
            raise ValueError("El límite debe ser mayor que cero.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, symbol, data_as_of, decision, readiness,
                       learning_ready, missing_evidence_json, blockers_json,
                       detected_strategies_json, payload_json
                FROM report_audits ORDER BY id DESC LIMIT ?
                """,
                (limit,),
        ).fetchall()
        audits: list[dict[str, Any]] = []
        for row in rows:
            payload = self._load_json_mapping(row["payload_json"])
            audits.append(
                {
                    **dict(row),
                    "learning_ready": bool(row["learning_ready"]),
                    "missing_evidence": self._load_json_list(
                        row["missing_evidence_json"]
                    ),
                    "blockers": self._load_json_list(row["blockers_json"]),
                    "detected_strategies": self._load_json_list(
                        row["detected_strategies_json"]
                    ),
                    "app_version": str(payload.get("app_version", "")),
                    "methodology_version": str(
                        payload.get("methodology_version", "")
                    ),
                    "package_id": str(payload.get("package_id", "")),
                    "package_session": str(payload.get("package_session", "")),
                    "package_timeframes": str(
                        payload.get("package_timeframes", "")
                    ),
                    "data_provider": str(payload.get("data_provider", "")),
                    "data_source_timeframes": str(
                        payload.get("data_source_timeframes", "")
                    ),
                    "data_source_files": str(payload.get("data_source_files", "")),
                    "data_quality_status": str(
                        payload.get("data_quality_status", "")
                    ),
                    "panorama_status": str(payload.get("panorama_status", "")),
                    "risk_status": str(payload.get("risk_status", "")),
                    "governance_status": str(payload.get("governance_status", "")),
                    "tentative_bias": str(payload.get("tentative_bias", "")),
                    "tentative_strategies": str(
                        payload.get("tentative_strategies", "")
                    ),
                    "first_missing_evidence": str(
                        payload.get("first_missing_evidence", "")
                    ),
                    "first_blocker": str(payload.get("first_blocker", "")),
                    "missing_gate_count": self._payload_int(
                        payload, "missing_gate_count"
                    ),
                    "missing_strategy_count": self._payload_int(
                        payload, "missing_strategy_count"
                    ),
                    "missing_invalidation_count": self._payload_int(
                        payload, "missing_invalidation_count"
                    ),
                    "blocker_gate_count": self._payload_int(
                        payload, "blocker_gate_count"
                    ),
                    "blocker_invalidation_count": self._payload_int(
                        payload, "blocker_invalidation_count"
                    ),
                    "blocker_detector_count": self._payload_int(
                        payload, "blocker_detector_count"
                    ),
                    "evaluated_count": self._payload_int(payload, "evaluated_count"),
                    "detected_count": self._payload_int(payload, "detected_count"),
                    "confirmed_count": self._payload_int(payload, "confirmed_count"),
                    "skipped_count": self._payload_int(payload, "skipped_count"),
                    "error_count": self._payload_int(payload, "error_count"),
                }
            )
        return audits

    def list_open_trades(self) -> list[dict[str, Any]]:
        """Devuelve operaciones abiertas con el símbolo analizado."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*, a.symbol
                FROM trades t JOIN analyses a ON a.id = t.analysis_id
                WHERE t.status = 'ABIERTA' ORDER BY t.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_closed_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        """Devuelve operaciones cerradas con contexto del analisis asociado."""
        if limit <= 0:
            raise ValueError("El limite debe ser mayor que cero.")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*, a.symbol, a.data_as_of, a.decision,
                       a.methodology_version, a.strategies_json
                FROM trades t JOIN analyses a ON a.id = t.analysis_id
                WHERE t.status = 'CERRADA'
                ORDER BY t.closed_at DESC, t.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "strategies": self._load_json_list(row["strategies_json"]),
            }
            for row in rows
        ]

    def weekly_new_trade_count(
        self, mode: str = "PAPER", *, now: datetime | None = None
    ) -> int:
        """Cuenta entradas nuevas desde el lunes UTC de la semana vigente."""
        if mode not in {"PAPER", "REAL"}:
            raise ValueError("El modo debe ser PAPER o REAL.")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        start = (current - timedelta(days=current.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM trades
                WHERE mode = ? AND workflow = 'NUEVA_ENTRADA' AND opened_at >= ?
                """,
                (mode, start.isoformat()),
            ).fetchone()
        return int(row["total"])

    def strategy_statistics(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Calcula estadísticas descriptivas sin reinterpretar estrategias."""
        with self._connect() as connection:
            query = """
                SELECT a.strategies_json, t.pnl
                FROM trades t JOIN analyses a ON a.id = t.analysis_id
                WHERE t.status = 'CERRADA'
                """
            parameters: tuple[str, ...] = ()
            if mode is not None:
                if mode not in {"PAPER", "REAL"}:
                    raise ValueError("El modo debe ser PAPER o REAL.")
                query += " AND t.mode = ?"
                parameters = (mode,)
            rows = connection.execute(query, parameters).fetchall()

        totals: dict[str, dict[str, float]] = {}
        for row in rows:
            for strategy_id in self._load_json_list(row["strategies_json"]):
                stats = totals.setdefault(
                    strategy_id, {"operations": 0, "wins": 0, "total_pnl": 0.0}
                )
                stats["operations"] += 1
                stats["wins"] += row["pnl"] > 0
                stats["total_pnl"] += row["pnl"]

        return [
            {
                "strategy_id": strategy_id,
                "operations": int(stats["operations"]),
                "win_rate": round(stats["wins"] / stats["operations"] * 100, 2),
                "total_pnl": round(stats["total_pnl"], 2),
            }
            for strategy_id, stats in sorted(totals.items())
        ]

    def learning_records(self, mode: str | None = None) -> list[dict[str, Any]]:
        """Entrega resultados cerrados cronológicos para análisis descriptivo."""
        if mode is not None and mode not in {"PAPER", "REAL"}:
            raise ValueError("El modo debe ser PAPER o REAL.")
        query = """
            SELECT t.id, t.closed_at, t.pnl, t.mode, t.decision_followed,
                   a.symbol, a.decision, a.strategies_json, a.methodology_version
            FROM trades t JOIN analyses a ON a.id = t.analysis_id
            WHERE t.status = 'CERRADA'
        """
        parameters: tuple[str, ...] = ()
        if mode is not None:
            query += " AND t.mode = ?"
            parameters = (mode,)
        query += " ORDER BY t.closed_at, t.id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                **dict(row),
                "strategies": self._load_json_list(row["strategies_json"]),
            }
            for row in rows
        ]
