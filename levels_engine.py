"""Mapa objetivo de medias móviles delante y detrás del precio."""

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from analysis_models import DirectionBias


@dataclass(frozen=True)
class MovingAverageLevel:
    """Una media móvil y su distancia geométrica al último cierre."""

    timeframe: str
    period: int
    value: float
    close: float
    side: str
    distance: float
    distance_pct: float
    ahead_of_bias: bool


def map_moving_average_levels(
    datasets: Mapping[str, pd.DataFrame],
    intended_bias: DirectionBias,
) -> tuple[MovingAverageLevel, ...]:
    """Ordena niveles por distancia sin decidir si el espacio es suficiente."""
    if intended_bias not in {DirectionBias.CALL, DirectionBias.PUT}:
        return ()
    levels: list[MovingAverageLevel] = []
    for timeframe in ("15m", "1H", "1D"):
        frame = datasets.get(timeframe)
        if frame is None or frame.empty or "close" not in frame.columns:
            continue
        row = frame.iloc[-1]
        if pd.isna(row["close"]):
            continue
        close = float(row["close"])
        for period in (20, 40, 100, 200):
            column = f"moving_average_{period}"
            if column not in frame.columns or pd.isna(row[column]):
                continue
            value = float(row[column])
            side = "SOBRE_PRECIO" if value > close else "BAJO_PRECIO" if value < close else "EN_PRECIO"
            ahead = (
                value > close
                if intended_bias is DirectionBias.CALL
                else value < close
            )
            distance = abs(value - close)
            levels.append(
                MovingAverageLevel(
                    timeframe=timeframe,
                    period=period,
                    value=value,
                    close=close,
                    side=side,
                    distance=distance,
                    distance_pct=(distance / abs(close) * 100 if close else float("nan")),
                    ahead_of_bias=ahead,
                )
            )
    return tuple(
        sorted(levels, key=lambda item: (not item.ahead_of_bias, item.distance_pct))
    )
