"""Incidentes persistentes del procesamiento de barras del scanner."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from safe_diagnostics import sanitize_diagnostic_detail


SERVICE_ID = "live_strategy_scanner"


class ScannerIncidentRepository:
    """Conserva fallos sin secretos y los resuelve solo con evidencia posterior."""

    def __init__(self, database_path: str | Path) -> None:
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
                CREATE TABLE IF NOT EXISTS scanner_processing_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    bar_timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    error_detail TEXT NOT NULL,
                    error_fingerprint TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution_bar_timestamp TEXT,
                    authority TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scanner_incidents_open
                ON scanner_processing_incidents (
                    service_id, symbol, resolved_at, id
                );
                """
            )

    def record(
        self,
        *,
        symbol: str,
        bar_timestamp: datetime,
        error: Exception,
        stage: str = "ANALISIS_15M",
        service_id: str = SERVICE_ID,
    ) -> int:
        if bar_timestamp.tzinfo is None:
            raise ValueError("El timestamp del incidente debe incluir zona horaria.")
        normalized_symbol = symbol.strip().upper()
        normalized_stage = stage.strip().upper()
        if not normalized_symbol or not normalized_stage:
            raise ValueError("Simbolo y etapa son obligatorios.")
        error_type = type(error).__name__[:100]
        raw_detail = str(error)
        safe_detail = sanitize_incident_detail(raw_detail)
        fingerprint = hashlib.sha256(
            f"{error_type}:{safe_detail}".encode("utf-8", errors="replace")
        ).hexdigest()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO scanner_processing_incidents (
                    service_id, symbol, bar_timestamp, created_at, stage,
                    error_type, error_detail, error_fingerprint, authority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    service_id.strip(),
                    normalized_symbol,
                    bar_timestamp.astimezone(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    normalized_stage,
                    error_type,
                    safe_detail,
                    fingerprint,
                    "INCIDENTE_SCANNER_NO_EJECUTA_ORDENES",
                ),
            )
        return int(cursor.lastrowid)

    def resolve_open(
        self,
        *,
        symbol: str,
        resolution_bar_timestamp: datetime,
        service_id: str = SERVICE_ID,
    ) -> int:
        if resolution_bar_timestamp.tzinfo is None:
            raise ValueError("El timestamp de resolucion debe incluir zona horaria.")
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("El simbolo es obligatorio.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE scanner_processing_incidents
                SET resolved_at=?, resolution_bar_timestamp=?
                WHERE service_id=? AND symbol=? AND resolved_at IS NULL
                  AND bar_timestamp < ?
                """,
                (
                    now,
                    resolution_bar_timestamp.astimezone(timezone.utc).isoformat(),
                    service_id.strip(),
                    normalized_symbol,
                    resolution_bar_timestamp.astimezone(timezone.utc).isoformat(),
                ),
            )
        return int(cursor.rowcount)

    def unresolved_count(
        self,
        *,
        symbols: tuple[str, ...] = (),
        service_id: str = SERVICE_ID,
    ) -> int:
        normalized = tuple(
            sorted({item.strip().upper() for item in symbols if item.strip()})
        )
        query = (
            "SELECT COUNT(*) FROM scanner_processing_incidents "
            "WHERE service_id=? AND resolved_at IS NULL"
        )
        parameters: list[Any] = [service_id.strip()]
        if normalized:
            query += " AND symbol IN (" + ",".join("?" for _ in normalized) + ")"
            parameters.extend(normalized)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return int(row[0])

    def recent(
        self,
        *,
        limit: int = 100,
        unresolved_only: bool = False,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("El limite debe ser mayor que cero.")
        query = "SELECT * FROM scanner_processing_incidents"
        if unresolved_only:
            query += " WHERE resolved_at IS NULL"
        query += " ORDER BY id DESC LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (limit,)).fetchall()
        return [dict(row) for row in rows]


def sanitize_incident_detail(value: str) -> str:
    """Conserva diagnostico breve eliminando patrones parecidos a secretos."""
    return sanitize_diagnostic_detail(value, limit=500)
