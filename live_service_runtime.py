"""Supervisión, reconexión y salud del servicio de mercado en vivo."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import Event
import time
from typing import Any, Iterator, Protocol

from live_market import MarketBar
from market_store import DEFAULT_MARKET_DATABASE, MarketContinuityService
from safe_diagnostics import sanitize_diagnostic_detail


class BarStream(Protocol):
    def run(
        self,
        symbols: Iterable[str],
        on_bar: Callable[[MarketBar], None],
        *,
        on_error: Callable[[Exception], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None: ...

    def stop(self) -> None: ...


class ServiceHealthRepository:
    """Guarda el último estado del proceso sin almacenar credenciales."""

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS live_service_health (
                    service_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    feed TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_connected_at TEXT,
                    last_bar_at TEXT,
                    reconnect_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def start(
        self, service_id: str, *, provider: str, feed: str, symbols: Iterable[str]
    ) -> None:
        now = _now_iso()
        normalized = sorted({item.strip().upper() for item in symbols if item.strip()})
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO live_service_health (
                    service_id, provider, feed, symbols_json, status,
                    started_at, updated_at
                ) VALUES (?, ?, ?, ?, 'INICIANDO', ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET
                    provider=excluded.provider, feed=excluded.feed,
                    symbols_json=excluded.symbols_json, status='INICIANDO',
                    started_at=excluded.started_at, updated_at=excluded.updated_at,
                    last_error=''
                """,
                (
                    service_id,
                    provider.strip().upper(),
                    feed.strip().lower(),
                    json.dumps(normalized),
                    now,
                    now,
                ),
            )

    def update(
        self,
        service_id: str,
        status: str,
        *,
        error: str | None = None,
        connected: bool = False,
        bar_timestamp: datetime | None = None,
        increment_reconnect: bool = False,
    ) -> None:
        allowed = {"INICIANDO", "CONECTANDO", "CONECTADO", "DESCONECTADO", "DETENIDO"}
        if status not in allowed:
            raise ValueError(f"Estado de servicio no reconocido: {status}")
        now = _now_iso()
        bar_iso = _utc_iso(bar_timestamp) if bar_timestamp else None
        safe_error = (
            sanitize_diagnostic_detail(error, limit=1000)
            if error is not None
            else None
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE live_service_health SET
                    status=?, updated_at=?,
                    last_error=CASE WHEN ? IS NOT NULL THEN ? ELSE last_error END,
                    last_connected_at=CASE WHEN ? THEN ? ELSE last_connected_at END,
                    last_bar_at=CASE WHEN ? IS NOT NULL THEN ? ELSE last_bar_at END,
                    reconnect_count=reconnect_count + ?
                WHERE service_id=?
                """,
                (
                    status,
                    now,
                    safe_error,
                    safe_error,
                    int(connected),
                    now,
                    bar_iso,
                    bar_iso,
                    int(increment_reconnect),
                    service_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Servicio no inicializado: {service_id}")

    def get(self, service_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM live_service_health WHERE service_id=?", (service_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["symbols"] = json.loads(result.pop("symbols_json"))
        return result


class ResilientStreamSupervisor:
    """Reconecta el stream y recupera por REST antes de cada intento."""

    def __init__(
        self,
        *,
        stream_factory: Callable[[], BarStream],
        continuity: MarketContinuityService,
        health: ServiceHealthRepository,
        service_id: str = "live_strategy_scanner",
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if initial_backoff <= 0 or max_backoff < initial_backoff:
            raise ValueError("Configuración de backoff inválida.")
        self.stream_factory = stream_factory
        self.continuity = continuity
        self.health = health
        self.service_id = service_id
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.sleeper = sleeper
        self.now = now
        self._stop = Event()
        self._stream: BarStream | None = None

    def run(
        self,
        symbols: Iterable[str],
        on_bar: Callable[[MarketBar], None],
        *,
        max_attempts: int | None = None,
    ) -> None:
        normalized = sorted({item.strip().upper() for item in symbols if item.strip()})
        if not normalized:
            raise ValueError("Debe indicarse al menos un símbolo.")
        self.health.start(
            self.service_id,
            provider=self.continuity.provider_name,
            feed=self.continuity.feed,
            symbols=normalized,
        )
        delay = self.initial_backoff
        attempts = 0
        while not self._stop.is_set():
            if max_attempts is not None and attempts >= max_attempts:
                break
            attempts += 1
            self.health.update(self.service_id, "CONECTANDO")
            try:
                end = self.now()
                for symbol in normalized:
                    self.continuity.recover(
                        symbol, end=end, initial_lookback=timedelta(days=1)
                    )
                self._stream = self.stream_factory()

                def tracked_bar(bar: MarketBar) -> None:
                    self.health.update(
                        self.service_id, "CONECTADO", bar_timestamp=bar.timestamp
                    )
                    on_bar(bar)

                def status_changed(status: str) -> None:
                    nonlocal delay
                    if status == "CONECTADO":
                        delay = self.initial_backoff
                        self.health.update(
                            self.service_id, "CONECTADO", connected=True
                        )

                self._stream.run(
                    normalized,
                    tracked_bar,
                    on_error=lambda error: self.health.update(
                        self.service_id, "DESCONECTADO", error=str(error)
                    ),
                    on_status=status_changed,
                )
                if self._stop.is_set():
                    break
                self.health.update(
                    self.service_id, "DESCONECTADO", increment_reconnect=True
                )
            except Exception as error:
                self.health.update(
                    self.service_id,
                    "DESCONECTADO",
                    error=str(error),
                    increment_reconnect=True,
                )
            if max_attempts is not None and attempts >= max_attempts:
                break
            self.sleeper(delay)
            delay = min(delay * 2, self.max_backoff)
        self.health.update(self.service_id, "DETENIDO")

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
        try:
            self.health.update(self.service_id, "DETENIDO")
        except ValueError:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("El timestamp debe incluir zona horaria.")
    return value.astimezone(timezone.utc).isoformat()
