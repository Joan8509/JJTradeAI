"""Cálculo descriptivo de rangos de precio desde barras intradía."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from live_market import normalize_minute_bars


DEFAULT_OPTION_RANGES_PATH = Path(__file__).resolve().parent / "config" / "option_price_ranges.csv"


def load_option_price_ranges(
    path: str | Path = DEFAULT_OPTION_RANGES_PATH,
) -> dict[str, dict[str, Any]]:
    """Carga la referencia manual de primas de contratos de opciones."""
    result: dict[str, dict[str, Any]] = {}
    with Path(path).open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter=";"):
            ticker = str(row.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            result[ticker] = {
                **row,
                "ticker": ticker,
                "optimal_low": float(row["optimal_low"]),
                "optimal_high": float(row["optimal_high"]),
                "minimum": float(row["minimum"]),
                "maximum": float(row["maximum"]),
            }
    return result


def calculate_price_range(
    minute_bars: pd.DataFrame,
    *,
    current_market_date: date,
    atr_period: int = 14,
    level_lookback: int = 20,
) -> dict[str, Any] | None:
    """Resume precio, rango ATR y niveles recientes; no proyecta garantías."""
    bars = normalize_minute_bars(minute_bars)
    if bars.empty:
        return None
    local_dates = bars["date"].dt.tz_convert("America/New_York").dt.date
    daily = (
        bars.assign(session=local_dates)
        .groupby("session", sort=True)
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    )
    if len(daily) < 2:
        return None
    previous_close = daily["close"].shift(1)
    true_range = pd.concat(
        [
            daily["high"] - daily["low"],
            (daily["high"] - previous_close).abs(),
            (daily["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.tail(min(atr_period, len(true_range))).mean())
    latest_session = daily.index[-1]
    reference_close = (
        float(daily["close"].iloc[-2])
        if latest_session == current_market_date
        else float(daily["close"].iloc[-1])
    )
    levels = daily.tail(level_lookback)
    support = float(levels["low"].min())
    resistance = float(levels["high"].max())
    current = float(bars["close"].iloc[-1])
    span = resistance - support
    relative = (current - support) / span if span > 0 else 0.5
    position = "Cerca del soporte" if relative <= 0.33 else "Cerca de la resistencia" if relative >= 0.67 else "Zona media"
    return {
        "current": current,
        "expected_low": reference_close - atr,
        "expected_high": reference_close + atr,
        "support": support,
        "resistance": resistance,
        "atr": atr,
        "position": position,
        "as_of": bars["date"].iloc[-1].to_pydatetime(),
        "sessions": len(levels),
    }
