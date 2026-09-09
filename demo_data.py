"""Datos sintéticos reproducibles para recorrer la interfaz de JJTrade AI."""

import math

import pandas as pd


def _frame(dates: pd.DatetimeIndex, start: float, drift: float) -> pd.DataFrame:
    closes = [start + drift * index + math.sin(index / 3) for index in range(len(dates))]
    result = pd.DataFrame({"date": dates, "close": closes})
    result["open"] = result["close"].shift(1).fillna(result["close"] - drift)
    result["high"] = result[["open", "close"]].max(axis=1) + 0.6
    result["low"] = result[["open", "close"]].min(axis=1) - 0.6
    for period in (20, 40, 100, 200):
        result[f"moving_average_{period}"] = result["close"].rolling(
            min(period, len(result)), min_periods=1
        ).mean()
    result["volume"] = [1_000_000 + index * 5_000 for index in range(len(result))]
    result["worden_stochastics"] = [50 + math.sin(index / 4) * 10 for index in range(len(result))]
    return result[
        [
            "date", "open", "high", "low", "close",
            "moving_average_20", "moving_average_40", "moving_average_100",
            "moving_average_200", "volume", "worden_stochastics",
        ]
    ]


def generate_demo_datasets() -> dict[str, pd.DataFrame]:
    """Genera tres temporalidades alineadas hasta 2026-06-24."""
    daily_dates = pd.bdate_range(end="2026-06-24", periods=60)
    hourly_dates = pd.DatetimeIndex(
        [
            day + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(hours=bar)
            for day in pd.bdate_range(end="2026-06-24", periods=10)
            for bar in range(7)
        ]
    )
    intraday_dates = pd.DatetimeIndex(
        [
            day + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=15 * bar)
            for day in pd.bdate_range(end="2026-06-24", periods=3)
            for bar in range(26)
        ]
    )
    return {
        "15m": _frame(intraday_dates, 100.0, 0.04),
        "1H": _frame(hourly_dates, 98.0, 0.06),
        "1D": _frame(daily_dates, 90.0, 0.2),
    }
