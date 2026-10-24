"""Persistencia local y control de continuidad para barras de mercado."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Iterator, Protocol

import pandas as pd

from live_market import (
    CANONICAL_BAR_COLUMNS,
    MarketBar,
    NoMarketDataError,
    closes_timeframe,
    normalize_minute_bars,
)


DEFAULT_MARKET_DATABASE = Path(__file__).resolve().parent / "exports" / "market_data.db"


class MinuteBarProvider(Protocol):
    def fetch_minute_bars(
        self, symbol: str, *, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Obtiene barras de un minuto en el rango solicitado."""


@dataclass(frozen=True)
class LiveBarIngestion:
    """Resultado del almacenamiento y eventos temporales de una barra."""

    symbol: str
    timestamp: datetime
    closes_15m: bool
    closes_1h: bool


class MarketBarStore:
    """Almacena barras idempotentes sin mezclar proveedores ni feeds."""

    def __init__(self, database_path: str | Path = DEFAULT_MARKET_DATABASE) -> None:
        from sqlite_runtime_guard import require_safe_wal_runtime
        require_safe_wal_runtime(database_path)
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS minute_bars (
                    provider TEXT NOT NULL,
                    feed TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    received_at TEXT NOT NULL,
                    PRIMARY KEY (provider, feed, symbol, timestamp)
                );
                CREATE INDEX IF NOT EXISTS idx_minute_bars_lookup
                ON minute_bars (provider, feed, symbol, timestamp);
                """
            )

    def upsert_frame(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        provider: str,
        feed: str,
        only_missing: bool = False,
    ) -> int:
        bars = normalize_minute_bars(frame)
        identity = _normalize_identity(symbol, provider, feed)
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (*identity, row.date.isoformat(), row.open, row.high, row.low, row.close, row.volume, now)
            for row in bars.itertuples(index=False)
        ]
        with self._connect() as connection:
            query = """
                INSERT INTO minute_bars (
                    symbol, provider, feed, timestamp, open, high, low, close,
                    volume, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            query += "ON CONFLICT(provider, feed, symbol, timestamp) DO NOTHING" if only_missing else """
                ON CONFLICT(provider, feed, symbol, timestamp) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume,
                    received_at=excluded.received_at
                """
            connection.executemany(query, rows)
            changed = connection.total_changes
        return changed if only_missing else len(rows)

    def upsert_bar(self, bar: MarketBar, *, provider: str, feed: str) -> int:
        frame = pd.DataFrame(
            [{
                "date": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }]
        )
        return self.upsert_frame(frame, symbol=bar.symbol, provider=provider, feed=feed)

    def upsert_bars(self, bars, *, provider: str, feed: str) -> int:
        """Persist an ordered stream burst with the same validation, one commit.

        Validate each bar separately: repeated official updates to the same
        minute remain ordered upserts, not duplicate timestamps in one frame.
        """
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for bar in bars:
            frame = normalize_minute_bars(pd.DataFrame([dict(date=bar.timestamp,
                open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume)]))
            identity = _normalize_identity(bar.symbol, provider, feed)
            row = next(frame.itertuples(index=False))
            rows.append((*identity, row.date.isoformat(), row.open, row.high,
                         row.low, row.close, row.volume, now))
        if not rows:
            return 0
        with self._connect() as connection:
            connection.executemany("INSERT INTO minute_bars "
                "(symbol,provider,feed,timestamp,open,high,low,close,volume,received_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider,feed,symbol,timestamp) "
                "DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,"
                "close=excluded.close,volume=excluded.volume,received_at=excluded.received_at", rows)
        return len(rows)

    def load_frame(
        self,
        *,
        symbol: str,
        provider: str,
        feed: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        symbol, provider, feed = _normalize_identity(symbol, provider, feed)
        clauses = ["symbol = ?", "provider = ?", "feed = ?"]
        values: list[object] = [symbol, provider, feed]
        if start is not None:
            clauses.append("timestamp >= ?")
            values.append(_utc_iso(start))
        if end is not None:
            clauses.append("timestamp <= ?")
            values.append(_utc_iso(end))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT timestamp, open, high, low, close, volume "
                "FROM minute_bars WHERE " + " AND ".join(clauses) + " ORDER BY timestamp",
                values,
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=CANONICAL_BAR_COLUMNS)
        return normalize_minute_bars(
            pd.DataFrame(rows, columns=CANONICAL_BAR_COLUMNS)
        )

    def latest_timestamp(
        self, *, symbol: str, provider: str, feed: str
    ) -> datetime | None:
        symbol, provider, feed = _normalize_identity(symbol, provider, feed)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(timestamp) FROM minute_bars "
                "WHERE symbol = ? AND provider = ? AND feed = ?",
                (symbol, provider, feed),
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None


def find_internal_minute_gaps(frame: pd.DataFrame) -> tuple[datetime, ...]:
    """Detecta minutos ausentes entre la primera y última barra de cada sesión."""
    bars = normalize_minute_bars(frame)
    local_dates = bars["date"].dt.tz_convert("America/New_York").dt.date
    missing: list[datetime] = []
    for _, session in bars.groupby(local_dates):
        timestamps = pd.DatetimeIndex(session["date"])
        expected = pd.date_range(timestamps.min(), timestamps.max(), freq="min")
        missing.extend(timestamp.to_pydatetime() for timestamp in expected.difference(timestamps))
    return tuple(missing)


class MarketContinuityService:
    """Recupera desde la última barra persistida y comprueba huecos internos."""

    def __init__(
        self,
        store: MarketBarStore,
        provider: MinuteBarProvider,
        *,
        provider_name: str,
        feed: str,
    ) -> None:
        self.store = store
        self.provider = provider
        self.provider_name = provider_name
        self.feed = feed

    def recover(
        self,
        symbol: str,
        *,
        end: datetime,
        initial_lookback: timedelta = timedelta(days=10),
    ) -> int:
        latest = self.store.latest_timestamp(
            symbol=symbol, provider=self.provider_name, feed=self.feed
        )
        start = latest + timedelta(minutes=1) if latest else end - initial_lookback
        if start > end:
            return 0
        try:
            frame = self.provider.fetch_minute_bars(symbol, start=start, end=end)
        except NoMarketDataError:
            return 0
        return self.store.upsert_frame(
            frame,
            symbol=symbol,
            provider=self.provider_name,
            feed=self.feed,
        )

    def gaps(self, symbol: str) -> tuple[datetime, ...]:
        frame = self.store.load_frame(
            symbol=symbol, provider=self.provider_name, feed=self.feed
        )
        if frame.empty:
            return ()
        return find_internal_minute_gaps(frame)

    def ingest_live_bar(self, bar: MarketBar) -> LiveBarIngestion:
        """Persiste una barra cerrada e informa qué análisis pueden ejecutarse."""
        if not bar.complete:
            raise ValueError("No se persisten barras de mercado todavía abiertas.")
        self.store.upsert_bar(
            bar, provider=self.provider_name, feed=self.feed
        )
        return LiveBarIngestion(
            symbol=bar.symbol.strip().upper(),
            timestamp=bar.timestamp,
            closes_15m=closes_timeframe(bar.timestamp, "15m"),
            closes_1h=closes_timeframe(bar.timestamp, "1H"),
        )


def _normalize_identity(symbol: str, provider: str, feed: str) -> tuple[str, str, str]:
    values = (symbol.strip().upper(), provider.strip().upper(), feed.strip().lower())
    if not all(values):
        raise ValueError("Símbolo, proveedor y feed son obligatorios.")
    return values


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Las fechas del mercado deben incluir zona horaria.")
    return value.astimezone(timezone.utc).isoformat()
