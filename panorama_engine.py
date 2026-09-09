"""Panorama multitemporal explicable, sin pesos metodológicos inventados."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from analysis_models import DirectionBias, GateStatus


class MarketDirection(str, Enum):
    """Dirección objetiva básica observada en una temporalidad."""

    ALCISTA = "ALCISTA"
    BAJISTA = "BAJISTA"
    MIXTA = "MIXTA"
    NO_DISPONIBLE = "NO_DISPONIBLE"


class BollingerLocation(str, Enum):
    """Ubicación del último cierre respecto a Bollinger."""

    EXPUESTO_SUPERIOR = "EXPUESTO_SUPERIOR"
    EXPUESTO_INFERIOR = "EXPUESTO_INFERIOR"
    DENTRO = "DENTRO"
    NO_DISPONIBLE = "NO_DISPONIBLE"


@dataclass(frozen=True)
class TimeframeSnapshot:
    """Hechos técnicos observables para una temporalidad."""

    timeframe: str
    direction: MarketDirection
    bollinger_location: BollingerLocation
    close: float
    ma20: float | None
    ma40: float | None
    volatility_opening: bool | None


@dataclass(frozen=True)
class PanoramaAssessment:
    """Resumen y compuerta de panorama para el motor de decisión."""

    status: GateStatus
    dominant_direction: MarketDirection
    snapshots: tuple[TimeframeSnapshot, ...]
    conflicts: tuple[str, ...]
    reasons: tuple[str, ...]


def _snapshot(timeframe: str, frame: pd.DataFrame) -> TimeframeSnapshot:
    if frame.empty or "close" not in frame.columns:
        raise ValueError(f"No hay cierre disponible para {timeframe}.")
    row = frame.iloc[-1]
    close = float(row["close"])
    ma20 = (
        float(row["moving_average_20"])
        if "moving_average_20" in frame.columns
        and pd.notna(row["moving_average_20"])
        else None
    )
    ma40 = (
        float(row["moving_average_40"])
        if "moving_average_40" in frame.columns
        and pd.notna(row["moving_average_40"])
        else None
    )
    if ma20 is None or ma40 is None:
        direction = MarketDirection.NO_DISPONIBLE
    elif close > ma20 > ma40:
        direction = MarketDirection.ALCISTA
    elif close < ma20 < ma40:
        direction = MarketDirection.BAJISTA
    else:
        direction = MarketDirection.MIXTA

    if not {"bollinger_upper", "bollinger_lower"}.issubset(frame.columns):
        location = BollingerLocation.NO_DISPONIBLE
    elif pd.isna(row["bollinger_upper"]) or pd.isna(row["bollinger_lower"]):
        location = BollingerLocation.NO_DISPONIBLE
    elif close > float(row["bollinger_upper"]):
        location = BollingerLocation.EXPUESTO_SUPERIOR
    elif close < float(row["bollinger_lower"]):
        location = BollingerLocation.EXPUESTO_INFERIOR
    else:
        location = BollingerLocation.DENTRO

    volatility = (
        bool(row["bollinger_both_expanding"])
        if "bollinger_both_expanding" in frame.columns
        and pd.notna(row["bollinger_both_expanding"])
        else None
    )
    return TimeframeSnapshot(
        timeframe=timeframe,
        direction=direction,
        bollinger_location=location,
        close=close,
        ma20=ma20,
        ma40=ma40,
        volatility_opening=volatility,
    )


def evaluate_panorama(
    datasets: Mapping[str, pd.DataFrame],
    *,
    intended_bias: DirectionBias | None = None,
    path_clear: bool | None = None,
    news_clear: bool | None = None,
    human_approval: bool | None = None,
) -> PanoramaAssessment:
    """Resume 15m, Hora y Diario y exige revisión humana para aprobar."""
    order = ("15m", "1H", "1D")
    snapshots = tuple(
        _snapshot(timeframe, datasets[timeframe])
        for timeframe in order
        if timeframe in datasets
    )
    missing = [timeframe for timeframe in order if timeframe not in datasets]
    reasons: list[str] = []
    conflicts: list[str] = []

    if missing:
        reasons.append("Faltan temporalidades: " + ", ".join(missing) + ".")

    directional = {
        item.timeframe: item.direction
        for item in snapshots
        if item.direction in {MarketDirection.ALCISTA, MarketDirection.BAJISTA}
    }
    unique_directions = set(directional.values())
    if len(unique_directions) == 1:
        dominant = next(iter(unique_directions))
    elif not unique_directions:
        dominant = MarketDirection.NO_DISPONIBLE
    else:
        dominant = MarketDirection.MIXTA
        conflicts.append("Las temporalidades muestran direcciones opuestas.")

    if intended_bias in {DirectionBias.CALL, DirectionBias.PUT}:
        expected = (
            MarketDirection.ALCISTA
            if intended_bias is DirectionBias.CALL
            else MarketDirection.BAJISTA
        )
        for timeframe in ("1D", "1H"):
            observed = directional.get(timeframe)
            if observed is not None and observed is not expected:
                conflicts.append(
                    f"{timeframe} está {observed.value} frente al sesgo "
                    f"{intended_bias.value}."
                )

    if path_clear is None:
        reasons.append("No se validó el espacio hasta el siguiente nivel.")
    elif not path_clear:
        reasons.append("El camino está bloqueado por un techo o piso cercano.")
    if news_clear is None:
        reasons.append("No se revisó el calendario de noticias.")
    elif not news_clear:
        reasons.append("Existe una noticia potencialmente invalidante.")
    if human_approval is None:
        reasons.append("El panorama requiere aprobación humana explícita.")
    elif not human_approval:
        reasons.append("La revisión humana rechazó el panorama.")

    rejected = (
        path_clear is False or news_clear is False or human_approval is False
    )
    approved = (
        not missing
        and not conflicts
        and path_clear is True
        and news_clear is True
        and human_approval is True
    )
    if rejected:
        status = GateStatus.RECHAZADO
    elif approved:
        status = GateStatus.APROBADO
    elif not snapshots:
        status = GateStatus.NO_DISPONIBLE
    else:
        status = GateStatus.REQUIERE_REVISION

    return PanoramaAssessment(
        status=status,
        dominant_direction=dominant,
        snapshots=snapshots,
        conflicts=tuple(dict.fromkeys(conflicts)),
        reasons=tuple(reasons),
    )
