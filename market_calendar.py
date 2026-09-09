"""Calendario oficial de sesiones estadounidenses obtenido de Alpaca."""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request
from zoneinfo import ZoneInfo
from pathlib import Path
import sqlite3

from alpaca_market_data import AlpacaMarketConfig, Transport, _default_transport


ALPACA_TRADING_URL = "https://paper-api.alpaca.markets"


@dataclass(frozen=True)
class MarketSession:
    session_date: date
    opens_at: datetime
    closes_at: datetime


class AlpacaMarketCalendarProvider:
    """Consulta horarios; no contiene operaciones ni endpoints de órdenes."""

    def __init__(self, config: AlpacaMarketConfig, *, transport: Transport = _default_transport) -> None:
        self.config = config
        self._transport = transport

    def fetch_sessions(self, start: date, end: date) -> tuple[MarketSession, ...]:
        if end < start:
            raise ValueError("El rango de calendario está invertido.")
        request = Request(
            f"{ALPACA_TRADING_URL}/v2/calendar?{urlencode({'start': start.isoformat(), 'end': end.isoformat()})}",
            headers={
                "APCA-API-KEY-ID": self.config.api_key,
                "APCA-API-SECRET-KEY": self.config.api_secret,
                "Accept": "application/json",
            },
        )
        payload = self._transport(request)
        if not isinstance(payload, list):
            raise ValueError("Respuesta de calendario Alpaca inválida.")
        eastern = ZoneInfo("America/New_York")
        sessions = []
        for item in payload:
            session_date = date.fromisoformat(str(item["date"]))
            sessions.append(
                MarketSession(
                    session_date,
                    datetime.combine(session_date, time.fromisoformat(str(item["open"])), eastern),
                    datetime.combine(session_date, time.fromisoformat(str(item["close"])), eastern),
                )
            )
        return tuple(sessions)


def session_close_map(sessions: tuple[MarketSession, ...]) -> dict[date, datetime]:
    return {session.session_date: session.closes_at for session in sessions}


class MarketSessionRepository:
    """Conserva el calendario oficial usado por el proceso en vivo."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS market_sessions (session_date TEXT PRIMARY KEY, opens_at TEXT NOT NULL, closes_at TEXT NOT NULL)")
            connection.commit()
        finally:
            connection.close()

    def upsert(self, sessions: tuple[MarketSession, ...]) -> int:
        connection = sqlite3.connect(self.database)
        try:
            connection.executemany(
                "INSERT INTO market_sessions (session_date, opens_at, closes_at) VALUES (?, ?, ?) ON CONFLICT(session_date) DO UPDATE SET opens_at=excluded.opens_at, closes_at=excluded.closes_at",
                [(item.session_date.isoformat(), item.opens_at.isoformat(), item.closes_at.isoformat()) for item in sessions],
            )
            connection.commit()
        finally:
            connection.close()
        return len(sessions)

    def session(self, session_date: date) -> MarketSession | None:
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute(
                "SELECT session_date, opens_at, closes_at FROM market_sessions WHERE session_date=?", (session_date.isoformat(),)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return MarketSession(date.fromisoformat(row[0]), datetime.fromisoformat(row[1]), datetime.fromisoformat(row[2]))
