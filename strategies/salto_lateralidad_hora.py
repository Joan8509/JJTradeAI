"""Detector conservador de ruptura/salto desde lateralidad en Hora."""

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/SALTO_LATERALIDAD_HORA.md"
LATERAL_BARS = 10
LATERAL_MAX_WIDTH_PCT = 2.0
LATERAL_MAX_SLOPE_PCT = 0.05


def _criterion(
    identifier: str,
    name: str,
    value: bool | None,
    detail: str,
) -> CriterionEvaluation:
    status = (
        EvaluationStatus.NO_DISPONIBLE
        if value is None
        else EvaluationStatus.CUMPLE
        if value
        else EvaluationStatus.NO_CUMPLE
    )
    return CriterionEvaluation(identifier, name, status, True, detail, SOURCE)


def _slope(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    count = len(numeric)
    x_mean = (count - 1) / 2
    mean = float(numeric.mean())
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    return sum((index - x_mean) * (float(value) - mean) for index, value in enumerate(numeric)) / denominator


def _objective_lateral(hourly: pd.DataFrame) -> tuple[bool | None, float | None, float | None, str]:
    required = {"high", "low", "close"}
    lateral = hourly.iloc[-(LATERAL_BARS + 1):-1]
    if len(lateral) < LATERAL_BARS or not required.issubset(hourly.columns):
        return None, None, None, f"Se requieren {LATERAL_BARS} velas con high/low/close."
    if lateral[list(required)].isna().any().any():
        return None, None, None, "El canal horario contiene valores incompletos."
    top, bottom = float(lateral["high"].max()), float(lateral["low"].min())
    mean_close = abs(float(lateral["close"].mean()))
    width_pct = (top - bottom) / mean_close * 100 if mean_close else float("inf")
    slope_pct = abs(_slope(lateral["close"]) / mean_close * 100) if mean_close else float("inf")
    passed = width_pct <= LATERAL_MAX_WIDTH_PCT and slope_pct <= LATERAL_MAX_SLOPE_PCT
    return bool(passed), top, bottom, f"Canal={bottom:.4f}-{top:.4f}; ancho={width_pct:.2f}%; pendiente={slope_pct:.4f}%/vela."


def evaluate_salto_lateralidad_hora(
    hourly: pd.DataFrame,
    *,
    lateral_channel_confirmed: bool | None = None,
    breakout_or_gap_confirmed: bool | None = None,
    near_hourly_ma20: bool | None = None,
    directional_volatility_confirmed: bool | None = None,
    news_clear: bool | None = None,
    path_clear: bool | None = None,
) -> StrategyEvaluation:
    """Evalua una ruptura de lateralidad en Hora sin estimar tamano del salto."""
    required = {"close", "moving_average_20", "moving_average_40"}
    missing = sorted(required.difference(hourly.columns))
    if missing:
        raise ValueError(
            "Faltan columnas de Hora para Salto de Lateralidad: "
            + ", ".join(missing)
        )
    if len(hourly) < 16:
        raise ValueError(
            "Salto de Lateralidad en Hora requiere al menos 16 registros: "
            "5 de tendencia previa, 10 de lateralidad y 1 de confirmacion."
        )
    if hourly[list(required)].tail(16).isna().any().any():
        raise ValueError("Los datos de Hora para Salto de Lateralidad estan incompletos.")

    prior = hourly.iloc[-16:-11]
    latest = hourly.iloc[-1]
    prior_first_close = float(prior.iloc[0]["close"])
    prior_last_close = float(prior.iloc[-1]["close"])
    latest_close = float(latest["close"])
    latest_ma20 = float(latest["moving_average_20"])
    latest_ma40 = float(latest["moving_average_40"])

    bullish_prior = prior_last_close > prior_first_close
    bearish_prior = prior_last_close < prior_first_close
    bullish_floor = latest_close > latest_ma20 > latest_ma40
    bearish_roof = latest_close < latest_ma20 < latest_ma40

    if bullish_prior and bullish_floor:
        strategy_id = "SALTO_LATERALIDAD_HORA_ALCISTA"
        bias = DirectionBias.CALL
        direction_detail = "alcista"
    elif bearish_prior and bearish_roof:
        strategy_id = "SALTO_LATERALIDAD_HORA_BAJISTA"
        bias = DirectionBias.PUT
        direction_detail = "bajista"
    else:
        strategy_id = "SIN_SALTO_LATERALIDAD_HORA"
        bias = DirectionBias.NEUTRAL
        direction_detail = "neutral"

    lateral_value, channel_top, channel_bottom, lateral_detail = _objective_lateral(hourly)
    latest_open = float(latest["open"]) if "open" in hourly.columns and not pd.isna(latest["open"]) else None
    if channel_top is None or channel_bottom is None or bias is DirectionBias.NEUTRAL:
        breakout_value = None
        near_value = None
    elif bias is DirectionBias.CALL:
        breakout_value = latest_close > channel_top or (latest_open is not None and latest_open > channel_top)
        prior_close = float(hourly.iloc[-2]["close"])
        near_value = abs(prior_close - float(hourly.iloc[-2]["moving_average_20"])) <= channel_top - channel_bottom
    else:
        breakout_value = latest_close < channel_bottom or (latest_open is not None and latest_open < channel_bottom)
        prior_close = float(hourly.iloc[-2]["close"])
        near_value = abs(prior_close - float(hourly.iloc[-2]["moving_average_20"])) <= channel_top - channel_bottom
    volatility_value = None
    if {"bollinger_upper_change", "bollinger_lower_change"}.issubset(hourly.columns):
        upper_change = latest["bollinger_upper_change"]
        lower_change = latest["bollinger_lower_change"]
        if not pd.isna([upper_change, lower_change]).any():
            volatility_value = float(upper_change) > 0 and float(lower_change) < 0
    if lateral_channel_confirmed is not None: lateral_value = lateral_channel_confirmed
    if breakout_or_gap_confirmed is not None: breakout_value = breakout_or_gap_confirmed
    if near_hourly_ma20 is not None: near_value = near_hourly_ma20
    if directional_volatility_confirmed is not None: volatility_value = directional_volatility_confirmed

    criteria = (
        _criterion(
            "prior_trend_minimum",
            "Tendencia previa minima de cinco registros de Hora",
            bullish_prior or bearish_prior,
            (
                f"Cierre inicial={prior_first_close:.4f}; "
                f"cierre final={prior_last_close:.4f}; direccion={direction_detail}."
            ),
        ),
        _criterion(
            "lateral_channel",
            "Lateralidad previa de al menos diez registros de Hora",
            lateral_value,
            lateral_detail,
        ),
        _criterion(
            "ma20_40_floor_or_roof",
            "MA20/MA40 actuan como piso o techo de la estructura",
            bullish_floor or bearish_roof,
            (
                f"Cierre={latest_close:.4f}; MA20={latest_ma20:.4f}; "
                f"MA40={latest_ma40:.4f}."
            ),
        ),
        _criterion(
            "breakout_or_gap",
            "Ruptura por vela de confirmacion en Hora o salto",
            breakout_value,
            lateral_detail,
        ),
        _criterion(
            "near_hourly_ma20",
            "Precio cercano a MA20 de Hora antes de buscar continuidad",
            near_value,
            lateral_detail,
        ),
        _criterion(
            "directional_volatility",
            "Volatilidad acompana la direccion esperada",
            volatility_value,
            "Disipador superior debe subir e inferior bajar en la vela cerrada.",
        ),
        _criterion(
            "news_clear",
            "Ausencia de noticia corporativa o macro invalidante",
            news_clear,
            "Earnings, splits o noticias macro fuertes invalidan la estrategia.",
        ),
        _criterion(
            "path_clear",
            "Camino libre hasta el siguiente techo o piso relevante",
            path_clear,
            "Un edge line cercano puede disminuir o bloquear el movimiento.",
        ),
    )
    detected = bool(
        bias is not DirectionBias.NEUTRAL
        and all(
            item.status is EvaluationStatus.CUMPLE
            for item in criteria if item.required
        )
    )
    name = (
        STRATEGY_REGISTRY[strategy_id]["nombre"]
        if strategy_id in STRATEGY_REGISTRY
        else "Salto de Lateralidad en Hora"
    )
    return StrategyEvaluation(strategy_id, name, bias, detected, criteria)
