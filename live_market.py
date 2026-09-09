"""Modelo canónico y agregación de velas para fuentes de mercado en vivo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

import pandas as pd

from data_providers import DataBundle


CANONICAL_BAR_COLUMNS = ("date", "open", "high", "low", "close", "volume")
SUPPORTED_LIVE_TIMEFRAMES = ("15m", "1H", "1D")


class NoMarketDataError(ValueError):
    """El proveedor respondió correctamente pero no encontró barras."""


@dataclass(frozen=True)
class MarketBar:
    """Vela OHLCV normalizada recibida de un proveedor."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    complete: bool = True


class HistoricalMarketProvider(Protocol):
    """Contrato mínimo para obtener un paquete multitemporal."""

    def fetch_bundle(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
    ) -> DataBundle:
        """Obtiene datos históricos listos para el motor."""


def normalize_minute_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Valida y ordena barras de un minuto sin fabricar intervalos ausentes."""
    missing = [column for column in CANONICAL_BAR_COLUMNS if column not in frame]
    if missing:
        raise ValueError("Faltan columnas de mercado: " + ", ".join(missing))
    if frame.empty:
        raise ValueError("No se recibieron barras de mercado.")

    result = frame.loc[:, CANONICAL_BAR_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], utc=True, errors="raise")
    for column in CANONICAL_BAR_COLUMNS[1:]:
        result[column] = pd.to_numeric(result[column], errors="raise").astype(float)
    if result["date"].duplicated().any():
        raise ValueError("Existen barras de mercado con fechas duplicadas.")
    if (result[list(CANONICAL_BAR_COLUMNS[1:])] < 0).any().any():
        raise ValueError("Las barras de mercado contienen valores negativos.")
    if (result["high"] < result[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError("La columna high no respeta la coherencia OHLC.")
    if (result["low"] > result[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError("La columna low no respeta la coherencia OHLC.")
    return result.sort_values("date").reset_index(drop=True)


def aggregate_minute_bars(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    regular_hours_only: bool = True,
) -> pd.DataFrame:
    """Construye 15m, 1H o 1D anclados a la apertura de Nueva York."""
    if timeframe not in SUPPORTED_LIVE_TIMEFRAMES:
        raise ValueError(f"Temporalidad no admitida: {timeframe}")
    bars = normalize_minute_bars(frame).set_index("date")
    local = bars.tz_convert("America/New_York")
    if regular_hours_only:
        local = local.between_time("09:30", "15:59")
    if local.empty:
        raise ValueError("No hay barras dentro de la sesión solicitada.")

    rule = {"15m": "15min", "1H": "60min", "1D": "1D"}[timeframe]
    kwargs = {"label": "left", "closed": "left"}
    if timeframe != "1D":
        kwargs.update({"origin": "start_day", "offset": "9h30min"})
    aggregated = local.resample(rule, **kwargs).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    aggregated = aggregated.dropna(subset=["open", "high", "low", "close"])
    aggregated.index = aggregated.index.tz_convert("UTC")
    return aggregated.reset_index().rename(columns={"date": "date"})


def closes_timeframe(timestamp: datetime, timeframe: str) -> bool:
    """Indica si una barra de un minuto cierra un bloque intradía canónico."""
    if timestamp.tzinfo is None:
        raise ValueError("El timestamp debe incluir zona horaria.")
    if timeframe not in {"15m", "1H"}:
        raise ValueError("El cierre automático solo admite 15m o 1H.")
    local = pd.Timestamp(timestamp).tz_convert("America/New_York")
    open_time = local.normalize() + pd.Timedelta(hours=9, minutes=30)
    elapsed_minutes = int((local - open_time).total_seconds() // 60)
    session_minutes = 390
    if elapsed_minutes < 0 or elapsed_minutes >= session_minutes:
        return False
    block = 15 if timeframe == "15m" else 60
    return (elapsed_minutes + 1) % block == 0 or elapsed_minutes == session_minutes - 1


def retain_closed_aggregates(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    latest_source_timestamp: datetime,
    session_closes: Mapping[object, datetime] | None = None,
) -> pd.DataFrame:
    """Excluye la última vela agregada cuando su periodo sigue abierto."""
    if timeframe not in SUPPORTED_LIVE_TIMEFRAMES:
        raise ValueError(f"Temporalidad no admitida: {timeframe}")
    if latest_source_timestamp.tzinfo is None:
        raise ValueError("latest_source_timestamp debe incluir zona horaria.")
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    dates = pd.to_datetime(result["date"], utc=True, errors="raise")
    local_starts = dates.dt.tz_convert("America/New_York")
    cutoff = pd.Timestamp(latest_source_timestamp).tz_convert("America/New_York") + pd.Timedelta(minutes=1)
    default_closes = local_starts.dt.normalize() + pd.Timedelta(hours=16)
    if session_closes:
        resolved_closes = pd.Series(
            [
                pd.Timestamp(session_closes.get(start.date(), fallback))
                for start, fallback in zip(local_starts, default_closes)
            ],
            index=result.index,
        )
    else:
        resolved_closes = default_closes
    if timeframe == "15m":
        period_ends = local_starts + pd.Timedelta(minutes=15)
    elif timeframe == "1H":
        normal_ends = local_starts + pd.Timedelta(hours=1)
        period_ends = pd.Series(
            [min(end, close) for end, close in zip(normal_ends, resolved_closes)],
            index=result.index,
        )
    else:
        period_ends = resolved_closes
    return result.loc[period_ends <= cutoff].reset_index(drop=True)
