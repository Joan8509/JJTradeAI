"""Detector de retorno a Bollinger tras un salto desde lateralidad previa."""

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/SALIENDO_BOLLINGER_VOLATILIDAD.md"
LATERAL_BARS = 8
LATERAL_MAX_SLOPE_PCT = 0.03
HISTORY_MINIMUM = 20
HISTORY_LOOKBACK = 60
COMPRESSION_PERCENTILE = 0.25
EXCEPTIONAL_GAP_PERCENTILE = 0.90
REVERSAL_MINIMUM_MINUTES = 5
REVERSAL_MINIMUM_GAP_RETRACE = 0.10


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
    return CriterionEvaluation(criterion_id, name, status, True, detail, SOURCE)


def _linear_slope(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    count = len(numeric)
    x_mean = (count - 1) / 2
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    return sum((index - x_mean) * (float(value) - float(numeric.mean())) for index, value in enumerate(numeric)) / denominator


def _prior_lateral(previous_session: pd.DataFrame) -> tuple[bool | None, str]:
    if "bollinger_mid" not in previous_session.columns or len(previous_session) < LATERAL_BARS:
        return None, f"Se requieren {LATERAL_BARS} Puntos Medios de la sesión previa."
    mids = pd.to_numeric(previous_session["bollinger_mid"], errors="coerce").tail(LATERAL_BARS)
    if mids.isna().any() or float(mids.mean()) == 0:
        return None, "Puntos Medios previos incompletos."
    slope_pct = abs(_linear_slope(mids) / float(mids.mean()) * 100)
    return bool(slope_pct <= LATERAL_MAX_SLOPE_PCT), f"Pendiente normalizada PM={slope_pct:.4f}%/vela; máximo={LATERAL_MAX_SLOPE_PCT:.4f}%."


def _prior_compression(data: pd.DataFrame, previous_index: int) -> tuple[bool | None, str]:
    prior = data.iloc[:previous_index]
    required = {"bollinger_upper", "bollinger_lower", "bollinger_mid"}
    if not required.issubset(data.columns) or len(prior) < HISTORY_MINIMUM:
        return None, f"Se requieren {HISTORY_MINIMUM} anchos históricos anteriores."
    widths = ((prior["bollinger_upper"] - prior["bollinger_lower"]) / prior["bollinger_mid"].abs() * 100).replace([float("inf"), float("-inf")], pd.NA).dropna().tail(HISTORY_LOOKBACK)
    previous = data.iloc[previous_index]
    current_width = (float(previous["bollinger_upper"]) - float(previous["bollinger_lower"])) / abs(float(previous["bollinger_mid"])) * 100
    if len(widths) < HISTORY_MINIMUM:
        return None, f"Solo hay {len(widths)} anchos históricos válidos."
    threshold = float(widths.quantile(COMPRESSION_PERCENTILE))
    return bool(current_width <= threshold), f"Ancho previo={current_width:.4f}%; percentil 25 histórico={threshold:.4f}%."


def _exceptional_gap(data: pd.DataFrame, sessions: list[object], current_open: float, previous_close: float) -> tuple[bool | None, str]:
    gaps: list[float] = []
    for index in range(1, len(sessions) - 1):
        prior_rows = data[data["_session"] == sessions[index - 1]]
        current_rows = data[data["_session"] == sessions[index]]
        prior_close = float(prior_rows.iloc[-1]["close"])
        if prior_close:
            gaps.append(abs(float(current_rows.iloc[0]["open"]) - prior_close) / abs(prior_close) * 100)
    gaps = gaps[-HISTORY_LOOKBACK:]
    if len(gaps) < HISTORY_MINIMUM:
        return None, f"Se requieren {HISTORY_MINIMUM} saltos de apertura históricos; disponibles={len(gaps)}."
    current_gap = abs(current_open - previous_close) / abs(previous_close) * 100
    threshold = float(pd.Series(gaps).quantile(EXCEPTIONAL_GAP_PERCENTILE))
    return bool(current_gap >= threshold), f"Salto actual={current_gap:.4f}%; percentil 90 histórico={threshold:.4f}%."


def _fast_reversal(
    minute_1m: pd.DataFrame | None,
    *,
    session: object,
    bullish: bool,
    previous_close: float,
    current_open: float,
) -> tuple[bool | None, str]:
    required = {"date", "open", "close"}
    if minute_1m is None or not required.issubset(minute_1m.columns):
        return None, "No hay barras auxiliares de 1 minuto para verificar los primeros cinco minutos."
    minutes = minute_1m.copy()
    minutes["_session"] = pd.to_datetime(minutes["date"]).dt.date
    first_five = minutes[minutes["_session"] == session].head(REVERSAL_MINIMUM_MINUTES)
    if len(first_five) < REVERSAL_MINIMUM_MINUTES or first_five[["open", "close"]].isna().any().any():
        return None, f"Solo hay {len(first_five)} de {REVERSAL_MINIMUM_MINUTES} minutos cerrados."
    changes = pd.to_numeric(first_five["close"], errors="coerce").diff()
    directional_minutes = int((changes > 0).sum()) if bullish else int((changes < 0).sum())
    end_close = float(first_five.iloc[-1]["close"])
    gap_distance = abs(current_open - previous_close)
    retrace = (end_close - current_open) if bullish else (current_open - end_close)
    retrace_ratio = retrace / gap_distance if gap_distance else 0.0
    passed = directional_minutes >= 3 and retrace_ratio >= REVERSAL_MINIMUM_GAP_RETRACE
    return bool(passed), (
        f"Minutos direccionales={directional_minutes}/4; retroceso del salto="
        f"{retrace_ratio:.1%}; mínimo={REVERSAL_MINIMUM_GAP_RETRACE:.0%}."
    )


def evaluate_retorno_bollinger_lateral(
    intraday_15m: pd.DataFrame,
    *,
    minute_1m: pd.DataFrame | None = None,
    prior_midpoint_lateral: bool | None = None,
    prior_volatility_closed: bool | None = None,
    gap_exceptional_for_symbol: bool | None = None,
    reversal_within_first_minutes: bool | None = None,
) -> StrategyEvaluation:
    """Evalúa la variante lateral sin imponer umbrales no documentados."""
    required = {
        "date",
        "open",
        "close",
        "bollinger_upper",
        "bollinger_lower",
        "bollinger_upper_change",
        "bollinger_lower_change",
    }
    missing = sorted(required.difference(intraday_15m.columns))
    if missing:
        raise ValueError(
            "Faltan columnas de 15m para Retorno a Bollinger: "
            + ", ".join(missing)
        )
    data = intraday_15m.copy().reset_index(drop=True)
    if data.empty:
        raise ValueError("No hay velas de 15m para Retorno a Bollinger.")
    data["_session"] = pd.to_datetime(data["date"]).dt.date
    sessions = sorted(data["_session"].unique())
    if len(sessions) < 2:
        raise ValueError("Retorno a Bollinger requiere al menos dos sesiones.")
    previous_session = data[data["_session"] == sessions[-2]]
    previous = previous_session.iloc[-1]
    first = data[data["_session"] == sessions[-1]].iloc[0]
    values = [
        previous["close"],
        previous["bollinger_upper"],
        previous["bollinger_lower"],
        first["open"],
        first["close"],
        first["bollinger_upper_change"],
        first["bollinger_lower_change"],
    ]
    if pd.isna(values).any():
        raise ValueError("Los indicadores de Retorno a Bollinger están incompletos.")

    previous_close = float(previous["close"])
    current_open = float(first["open"])
    current_close = float(first["close"])
    gap_down = current_open < previous_close
    gap_up = current_open > previous_close
    below_lower = current_open < float(previous["bollinger_lower"])
    above_upper = current_open > float(previous["bollinger_upper"])

    if gap_down and below_lower:
        strategy_id = "RETORNO_BOLLINGER_LATERAL_ALCISTA"
        bias = DirectionBias.CALL
        reversal_direction = current_close > current_open
    elif gap_up and above_upper:
        strategy_id = "RETORNO_BOLLINGER_LATERAL_BAJISTA"
        bias = DirectionBias.PUT
        reversal_direction = current_close < current_open
    else:
        strategy_id = "SIN_RETORNO_BOLLINGER_LATERAL"
        bias = DirectionBias.NEUTRAL
        reversal_direction = False

    bands_closing = (
        float(first["bollinger_upper_change"]) < 0
        and float(first["bollinger_lower_change"]) > 0
    )
    outside_gap = (gap_down and below_lower) or (gap_up and above_upper)
    previous_position = int(previous.name)
    lateral_value, lateral_detail = _prior_lateral(previous_session)
    compression_value, compression_detail = _prior_compression(data, previous_position)
    exceptional_value, exceptional_detail = _exceptional_gap(
        data, sessions, current_open, previous_close
    )
    if prior_midpoint_lateral is not None:
        lateral_value, lateral_detail = prior_midpoint_lateral, "Criterio manual suministrado por compatibilidad."
    if prior_volatility_closed is not None:
        compression_value, compression_detail = prior_volatility_closed, "Criterio manual suministrado por compatibilidad."
    if gap_exceptional_for_symbol is not None:
        exceptional_value, exceptional_detail = gap_exceptional_for_symbol, "Criterio manual suministrado por compatibilidad."
    reversal_value, reversal_detail = _fast_reversal(
        minute_1m,
        session=sessions[-1],
        bullish=bias is DirectionBias.CALL,
        previous_close=previous_close,
        current_open=current_open,
    )
    if reversal_within_first_minutes is not None:
        reversal_value, reversal_detail = reversal_within_first_minutes, "Criterio manual suministrado por compatibilidad."
    criteria = (
        _criterion(
            "prior_midpoint_lateral",
            "Punto Medio 15m lateral al cierre previo",
            lateral_value,
            lateral_detail,
        ),
        _criterion(
            "prior_volatility_closed",
            "Bollinger sin volatilidad al cierre previo",
            compression_value,
            compression_detail,
        ),
        _criterion(
            "gap_outside_bollinger",
            "Salto abre fuera del disipador correspondiente",
            outside_gap,
            f"Apertura={current_open:.4f}; cierre previo={previous_close:.4f}.",
        ),
        _criterion(
            "exceptional_gap",
            "Distancia excepcional para el activo",
            exceptional_value,
            exceptional_detail,
        ),
        _criterion(
            "immediate_reversal",
            "Reversión inmediata hacia Bollinger",
            reversal_direction and reversal_value if reversal_value is not None else None,
            reversal_detail,
        ),
        _criterion(
            "bands_closing",
            "Los disipadores comienzan a cerrarse",
            bands_closing,
            (
                f"Cambio superior={float(first['bollinger_upper_change']):.4f}; "
                f"cambio inferior={float(first['bollinger_lower_change']):.4f}."
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
        else "Retorno a Bollinger desde Lateralidad"
    )
    return StrategyEvaluation(strategy_id, name, bias, detected, criteria)
