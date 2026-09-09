"""Reconciliación objetiva entre barras WebSocket persistidas y REST."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import math
import time
from pathlib import Path
import sqlite3
import json

import pandas as pd

from live_market import normalize_minute_bars
from market_store import MinuteBarProvider
from safe_diagnostics import sanitize_diagnostic_detail


@dataclass(frozen=True)
class ReconciliationPolicy:
    price_absolute_tolerance: float = 0.000001
    volume_absolute_tolerance: float = 0.0

    def __post_init__(self) -> None:
        if self.price_absolute_tolerance < 0 or self.volume_absolute_tolerance < 0:
            raise ValueError("Las tolerancias de reconciliación no pueden ser negativas.")


class MarketDataReconciler:
    def __init__(self, provider: MinuteBarProvider, policy: ReconciliationPolicy = ReconciliationPolicy(), *, attempts: int = 1, retry_delay: float = 0.0, sleeper=time.sleep) -> None:
        if attempts <= 0 or retry_delay < 0:
            raise ValueError("Los reintentos de reconciliación no son válidos.")
        self.provider = provider
        self.policy = policy
        self.attempts = attempts
        self.retry_delay = retry_delay
        self.sleeper = sleeper

    def reconcile(self, symbol: str, *, start: datetime, end: datetime, local: pd.DataFrame) -> dict[str, Any]:
        """Consulta REST y compara cada minuto, sin modificar el almacén local."""
        last_result = None
        for attempt in range(1, self.attempts + 1):
            try:
                remote = self.provider.fetch_minute_bars(symbol, start=start, end=end + timedelta(minutes=1))
            except Exception as error:
                last_result = _payload(
                    "NO_DISPONIBLE",
                    start,
                    end,
                    (),
                    "REST no disponible: " + sanitize_diagnostic_detail(error),
                )
            else:
                last_result = compare_minute_frames(local, remote, start=start, end=end, policy=self.policy)
                if last_result["status"] == "APROBADO":
                    last_result["attempts"] = attempt
                    return last_result
            if attempt < self.attempts:
                self.sleeper(self.retry_delay)
        last_result["attempts"] = self.attempts
        return last_result


def compare_minute_frames(local: pd.DataFrame, remote: pd.DataFrame, *, start: datetime, end: datetime, policy: ReconciliationPolicy = ReconciliationPolicy()) -> dict[str, Any]:
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("El rango de reconciliación debe ser válido y tener zona horaria.")
    left = _window(local, start, end).set_index("date")
    right = _window(remote, start, end).set_index("date")
    expected = pd.date_range(start, end, freq="min")
    differences: list[dict[str, Any]] = []
    for timestamp in expected:
        local_has_bar = timestamp in left.index
        rest_has_bar = timestamp in right.index
        if not local_has_bar or not rest_has_bar:
            if local_has_bar != rest_has_bar:
                differences.append(
                    {
                        "timestamp": timestamp.isoformat(),
                        "field": "bar",
                        "local": local_has_bar,
                        "rest": rest_has_bar,
                    }
                )
            continue
        for field in ("open", "high", "low", "close", "volume"):
            local_value = float(left.loc[timestamp, field])
            remote_value = float(right.loc[timestamp, field])
            tolerance = policy.volume_absolute_tolerance if field == "volume" else policy.price_absolute_tolerance
            if not math.isclose(local_value, remote_value, rel_tol=0.0, abs_tol=tolerance):
                differences.append({"timestamp": timestamp.isoformat(), "field": field, "local": local_value, "rest": remote_value})
    status = "APROBADO" if not differences else "RECHAZADO"
    detail = "WebSocket y REST coinciden." if not differences else f"Se encontraron {len(differences)} discrepancias."
    return _payload(status, start, end, tuple(differences), detail)


def _window(frame: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    bars = normalize_minute_bars(frame)
    return bars[(bars["date"] >= start) & (bars["date"] <= end)]


def _payload(status: str, start: datetime, end: datetime, differences: tuple[dict[str, Any], ...], detail: str) -> dict[str, Any]:
    return {"status": status, "start": start.isoformat(), "end": end.isoformat(), "compared_bar_count": int((end - start).total_seconds() // 60) + 1, "difference_count": len(differences), "differences": list(differences), "detail": detail, "authority": "CALIDAD_DE_DATOS_NO_CORRIGE_PRECIOS"}


class MarketReconciliationRepository:
    """Persiste comprobaciones antes de que el evaluador pueda fallar."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS market_reconciliations (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, provider TEXT NOT NULL, feed TEXT NOT NULL, symbol TEXT NOT NULL, trigger_timestamp TEXT NOT NULL, status TEXT NOT NULL, difference_count INTEGER NOT NULL, payload_json TEXT NOT NULL, UNIQUE(provider, feed, symbol, trigger_timestamp))"
            )
            connection.commit()
        finally:
            connection.close()

    def record(self, *, provider: str, feed: str, symbol: str, trigger_timestamp: datetime, payload: dict[str, Any]) -> int:
        if trigger_timestamp.tzinfo is None:
            raise ValueError("El timestamp de reconciliación debe incluir zona horaria.")
        connection = sqlite3.connect(self.database)
        try:
            cursor = connection.execute(
                "INSERT INTO market_reconciliations (created_at, provider, feed, symbol, trigger_timestamp, status, difference_count, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(provider, feed, symbol, trigger_timestamp) DO UPDATE SET created_at=excluded.created_at, status=excluded.status, difference_count=excluded.difference_count, payload_json=excluded.payload_json RETURNING id",
                (datetime.now(trigger_timestamp.tzinfo).isoformat(), provider.strip().upper(), feed.strip().lower(), symbol.strip().upper(), trigger_timestamp.isoformat(), str(payload.get("status", "NO_DISPONIBLE")), int(payload.get("difference_count", 0)), json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
            row = cursor.fetchone()
            connection.commit()
            return int(row[0])
        finally:
            connection.close()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("El límite debe ser mayor que cero.")
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM market_reconciliations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            connection.close()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def latest_by_symbol(self, symbols: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        normalized = tuple(sorted({item.strip().upper() for item in symbols if item.strip()}))
        if not normalized:
            return {}
        placeholders = ",".join("?" for _ in normalized)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                f"SELECT * FROM market_reconciliations WHERE symbol IN ({placeholders}) ORDER BY id DESC",
                normalized,
            ).fetchall()
        finally:
            connection.close()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = {**dict(row), "payload": json.loads(row["payload_json"])}
            latest.setdefault(str(row["symbol"]), item)
        return latest
