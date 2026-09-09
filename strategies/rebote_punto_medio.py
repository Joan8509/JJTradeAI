"""Detector multitemporal de Rebote en Punto Medio Diario."""

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/REBOTE_PUNTO_MEDIO.md"
MULTI_DAY_APPROACH_BARS = 3


def _criterion(
    criterion_id: str,
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
    return CriterionEvaluation(
        criterion_id, name, status, True, detail, SOURCE
    )


def _midpoint_respect_review(
    candle_15m: pd.Series,
    *,
    daily_mid: float,
    bullish_context: bool,
    bearish_context: bool,
    manual_value: bool | None,
) -> CriterionEvaluation:
    """Evalua rechazo del Punto Medio con cierre 15m del lado correcto."""
    if manual_value is not None:
        return _criterion(
            "midpoint_respected",
            "El precio respeta y rechaza el Punto Medio en 15m",
            manual_value,
            "Revision manual disponible.",
        )
    if not {"open", "close"}.issubset(candle_15m.index):
        return _criterion(
            "midpoint_respected",
            "El precio respeta y rechaza el Punto Medio en 15m",
            None,
            "La vela de 15m no contiene open/close para evaluar el rechazo.",
        )
    if pd.isna([candle_15m["open"], candle_15m["close"]]).any():
        return _criterion(
            "midpoint_respected",
            "El precio respeta y rechaza el Punto Medio en 15m",
            None,
            "La vela de 15m contiene open/close incompletos.",
        )

    low = float(candle_15m["low"])
    high = float(candle_15m["high"])
    close = float(candle_15m["close"])
    level_reached = low <= daily_mid <= high
    bullish_rejection = bullish_context and level_reached and close > daily_mid
    bearish_rejection = bearish_context and level_reached and close < daily_mid
    return _criterion(
        "midpoint_respected",
        "El precio respeta y rechaza el Punto Medio en 15m",
        bullish_rejection or bearish_rejection,
        (
            f"Rango 15m={low:.4f}-{high:.4f}; cierre={close:.4f}; "
            f"PM Diario={daily_mid:.4f}."
        ),
    )


def _multi_day_approach(
    daily: pd.DataFrame,
    *,
    daily_mid: float,
    bullish_context: bool,
    bearish_context: bool,
) -> tuple[bool | None, str]:
    """Comprueba tres cierres diarios acercándose al nivel desde el lado correcto."""
    if "close" not in daily.columns:
        return None, "Diario no contiene cierres para medir el acercamiento."
    closes = pd.to_numeric(daily["close"], errors="coerce").tail(MULTI_DAY_APPROACH_BARS)
    if len(closes) < MULTI_DAY_APPROACH_BARS or closes.isna().any():
        return None, f"Se requieren {MULTI_DAY_APPROACH_BARS} cierres diarios completos."
    if bullish_context:
        correct_side = bool((closes > daily_mid).all())
    elif bearish_context:
        correct_side = bool((closes < daily_mid).all())
    else:
        return False, "Los Puntos Medios Diario y de Hora no forman un contexto de rebote."
    distances = (closes - daily_mid).abs().tolist()
    approaching = all(later < earlier for earlier, later in zip(distances, distances[1:]))
    return bool(correct_side and approaching), (
        f"Distancias de los últimos {MULTI_DAY_APPROACH_BARS} cierres al PM Diario="
        f"{[round(value, 4) for value in distances]}; lado correcto={correct_side}."
    )


def evaluate_rebote_punto_medio(
    intraday_15m: pd.DataFrame,
    hourly: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    multi_day_approach_confirmed: bool | None = None,
    midpoint_respected_in_15m: bool | None = None,
    hourly_candle_closed: bool = False,
) -> StrategyEvaluation:
    """Evalúa el rebote sin inferir tolerancias o duración no documentadas."""
    requirements = {
        "15m": (intraday_15m, {"high", "low"}),
        "1H": (hourly, {"open", "close", "bollinger_mid_slope"}),
        "1D": (daily, {"bollinger_mid", "bollinger_mid_slope"}),
    }
    for timeframe, (frame, columns) in requirements.items():
        missing = sorted(columns.difference(frame.columns))
        if missing:
            raise ValueError(
                f"Faltan columnas de {timeframe} para Rebote en Punto Medio: "
                + ", ".join(missing)
            )
        if frame.empty:
            raise ValueError(
                f"No hay datos de {timeframe} para Rebote en Punto Medio."
            )

    candle_15m = intraday_15m.iloc[-1]
    hour = hourly.iloc[-1]
    day = daily.iloc[-1]
    values = [
        candle_15m["high"],
        candle_15m["low"],
        hour["open"],
        hour["close"],
        hour["bollinger_mid_slope"],
        day["bollinger_mid"],
        day["bollinger_mid_slope"],
    ]
    if pd.isna(values).any():
        raise ValueError("Los indicadores de Rebote en Punto Medio están incompletos.")

    daily_mid = float(day["bollinger_mid"])
    daily_slope = float(day["bollinger_mid_slope"])
    hourly_slope = float(hour["bollinger_mid_slope"])
    bullish_context = daily_slope > 0 and hourly_slope < 0
    bearish_context = daily_slope < 0 and hourly_slope > 0
    level_reached = float(candle_15m["low"]) <= daily_mid <= float(
        candle_15m["high"]
    )

    if bullish_context:
        strategy_id = "REBOTE_PUNTO_MEDIO_ALCISTA"
        bias = DirectionBias.CALL
        hour_directional = (
            float(hour["close"]) > float(hour["open"])
            and float(hour["close"]) > daily_mid
        )
    elif bearish_context:
        strategy_id = "REBOTE_PUNTO_MEDIO_BAJISTA"
        bias = DirectionBias.PUT
        hour_directional = (
            float(hour["close"]) < float(hour["open"])
            and float(hour["close"]) < daily_mid
        )
    else:
        strategy_id = "SIN_REBOTE_PUNTO_MEDIO"
        bias = DirectionBias.NEUTRAL
        hour_directional = False

    approach_value, approach_detail = _multi_day_approach(
        daily,
        daily_mid=daily_mid,
        bullish_context=bullish_context,
        bearish_context=bearish_context,
    )
    if multi_day_approach_confirmed is not None:
        approach_value = multi_day_approach_confirmed
        approach_detail = "Criterio manual suministrado por compatibilidad."
    hourly_confirmation = hourly_candle_closed and hour_directional
    criteria = (
        _criterion(
            "daily_midpoint_direction",
            "Punto Medio Diario en la dirección principal",
            bullish_context or bearish_context,
            f"Pendiente diaria={daily_slope:.4f}.",
        ),
        _criterion(
            "opposite_hourly_approach",
            "Punto Medio de Hora contrario durante el acercamiento",
            bullish_context or bearish_context,
            f"Pendiente de Hora={hourly_slope:.4f}.",
        ),
        _criterion(
            "multi_day_approach",
            "Acercamiento al nivel durante varios días",
            approach_value,
            approach_detail,
        ),
        _criterion(
            "daily_midpoint_reached",
            "La vela de 15m alcanza el Punto Medio Diario",
            level_reached,
            (
                f"Rango 15m={float(candle_15m['low']):.4f}-"
                f"{float(candle_15m['high']):.4f}; PM Diario={daily_mid:.4f}."
            ),
        ),
        _midpoint_respect_review(
            candle_15m,
            daily_mid=daily_mid,
            bullish_context=bullish_context,
            bearish_context=bearish_context,
            manual_value=midpoint_respected_in_15m,
        ),
        _criterion(
            "hourly_candle_closed",
            "Vela de Hora confirmada como cerrada",
            hourly_candle_closed,
            "Una vela de Hora en formación no confirma el rebote.",
        ),
        _criterion(
            "directional_hourly_confirmation",
            "Vela cerrada de Hora confirma la dirección del rebote",
            hourly_confirmation,
            (
                f"Hora open={float(hour['open']):.4f}, "
                f"close={float(hour['close']):.4f}; PM Diario={daily_mid:.4f}."
            ),
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
        else "Rebote en Punto Medio"
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name=name,
        bias=bias,
        detected=detected,
        criteria=criteria,
    )
