"""Detector conservador de Cambio de Tendencia en Hora."""

import pandas as pd

from analysis_models import CriterionEvaluation, DirectionBias, EvaluationStatus, StrategyEvaluation
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/CAMBIO_TENDENCIA_HORA.md"
PRIOR_HOURLY_BARS = 13
MINIMUM_DIRECTIONAL_RATIO = 0.70


def _criterion(identifier: str, name: str, value: bool | None, detail: str) -> CriterionEvaluation:
    status = EvaluationStatus.NO_DISPONIBLE if value is None else EvaluationStatus.CUMPLE if value else EvaluationStatus.NO_CUMPLE
    return CriterionEvaluation(identifier, name, status, True, detail, SOURCE)


def _projection(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce")
    count = len(numeric)
    x_mean = (count - 1) / 2
    mean = float(numeric.mean())
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = sum((index - x_mean) * (float(value) - mean) for index, value in enumerate(numeric)) / denominator
    return slope, mean - slope * x_mean + slope * count


def _objective_history(hourly: pd.DataFrame, bullish: bool) -> tuple[bool | None, bool | None, float | None, str]:
    required = {"high", "low", "close", "bollinger_mid"}
    prior = hourly.iloc[-(PRIOR_HOURLY_BARS + 1):-1]
    if len(prior) < PRIOR_HOURLY_BARS or not required.issubset(hourly.columns):
        return None, None, None, f"Se requieren {PRIOR_HOURLY_BARS} velas previas con OHLC y Punto Medio."
    if prior[list(required)].isna().any().any():
        return None, None, None, "El historial horario contiene valores incompletos."
    directional = (prior["close"] <= prior["bollinger_mid"]) if bullish else (prior["close"] >= prior["bollinger_mid"])
    ratio = float(directional.mean())
    close_slope, _ = _projection(prior["close"])
    prior_trend = ratio >= MINIMUM_DIRECTIONAL_RATIO and (close_slope < 0 if bullish else close_slope > 0)
    side = "high" if bullish else "low"
    line_slope, line_value = _projection(prior[side])
    line_valid = line_slope <= 0 if bullish else line_slope >= 0
    detail = (
        f"Alineación previa={ratio:.0%}; pendiente cierre={close_slope:.4f}; "
        f"línea {side} pendiente={line_slope:.4f}, proyección={line_value:.4f}."
    )
    return bool(prior_trend), bool(line_valid), float(line_value), detail


def _intraday_alignment(intraday_15m: pd.DataFrame | None, bullish: bool) -> tuple[bool | None, str]:
    required = {"close", "bollinger_mid", "bollinger_mid_slope"}
    if intraday_15m is None or intraday_15m.empty or not required.issubset(intraday_15m.columns):
        return None, "No hay 15m completo para confirmar la nueva dirección."
    row = intraday_15m.iloc[-1]
    if row[list(required)].isna().any():
        return None, "Los indicadores de 15m están incompletos."
    aligned = (float(row["close"]) > float(row["bollinger_mid"]) and float(row["bollinger_mid_slope"]) > 0) if bullish else (float(row["close"]) < float(row["bollinger_mid"]) and float(row["bollinger_mid_slope"]) < 0)
    return bool(aligned), f"15m close={float(row['close']):.4f}, PM={float(row['bollinger_mid']):.4f}, pendiente={float(row['bollinger_mid_slope']):.4f}."


def evaluate_cambio_tendencia_hora(
    hourly: pd.DataFrame,
    *,
    intraday_15m: pd.DataFrame | None = None,
    prior_trend_two_days: bool | None = None,
    trendline_drawn_correctly: bool | None = None,
    trendline_broken: bool | None = None,
    hourly_candle_closed: bool = False,
    closed_candle_confirms_both_levels: bool | None = None,
    gap_broke_both_levels: bool | None = None,
    intraday_15m_aligned: bool | None = None,
) -> StrategyEvaluation:
    """Detecta cruce de Punto Medio y línea con barras cerradas."""
    required = {"close", "bollinger_mid"}
    missing = sorted(required.difference(hourly.columns))
    if missing:
        raise ValueError("Faltan columnas de Hora para Cambio de Tendencia: " + ", ".join(missing))
    if len(hourly) < 2:
        raise ValueError("Cambio de Tendencia en Hora requiere al menos dos velas.")
    previous, latest = hourly.iloc[-2], hourly.iloc[-1]
    if previous[list(required)].isna().any() or latest[list(required)].isna().any():
        raise ValueError("El Punto Medio de Hora contiene datos incompletos.")

    previous_close, latest_close = float(previous["close"]), float(latest["close"])
    previous_mid, latest_mid = float(previous["bollinger_mid"]), float(latest["bollinger_mid"])
    bullish_cross = previous_close <= previous_mid and latest_close > latest_mid
    bearish_cross = previous_close >= previous_mid and latest_close < latest_mid
    if bullish_cross:
        strategy_id, bias = "CAMBIO_TENDENCIA_HORA_ALCISTA", DirectionBias.CALL
    elif bearish_cross:
        strategy_id, bias = "CAMBIO_TENDENCIA_HORA_BAJISTA", DirectionBias.PUT
    else:
        strategy_id, bias = "SIN_CAMBIO_TENDENCIA_HORA", DirectionBias.NEUTRAL

    bullish = bias is DirectionBias.CALL
    history_value, line_value_ok, projected_line, history_detail = _objective_history(hourly, bullish) if bias is not DirectionBias.NEUTRAL else (False, False, None, "No existe cruce direccional.")
    objective_break = None if projected_line is None else (latest_close > projected_line if bullish else latest_close < projected_line)
    latest_open = float(latest["open"]) if "open" in hourly.columns and not pd.isna(latest["open"]) else None
    objective_gap = None if projected_line is None or latest_open is None else ((latest_open > latest_mid and latest_open > projected_line and previous_close <= previous_mid) if bullish else (latest_open < latest_mid and latest_open < projected_line and previous_close >= previous_mid))
    objective_closed = bool(hourly_candle_closed and objective_break and (bullish_cross or bearish_cross)) if objective_break is not None else None
    alignment_value, alignment_detail = _intraday_alignment(intraday_15m, bullish)

    if prior_trend_two_days is not None: history_value = prior_trend_two_days
    if trendline_drawn_correctly is not None: line_value_ok = trendline_drawn_correctly
    if trendline_broken is not None: objective_break = trendline_broken
    if closed_candle_confirms_both_levels is not None: objective_closed = hourly_candle_closed and closed_candle_confirms_both_levels
    if gap_broke_both_levels is not None: objective_gap = gap_broke_both_levels
    if intraday_15m_aligned is not None: alignment_value = intraday_15m_aligned
    confirmation = objective_gap is True or objective_closed is True

    criteria = (
        _criterion("prior_trend", "Tendencia previa clara de al menos dos días", history_value, history_detail),
        _criterion("trendline_drawn", "Línea de tendencia trazada correctamente", line_value_ok, history_detail),
        _criterion("midpoint_cross", "Cruce del Punto Medio de Hora", bullish_cross or bearish_cross, f"Cierre previo={previous_close:.4f}; cierre actual={latest_close:.4f}."),
        _criterion("trendline_break", "Ruptura de la línea de tendencia", objective_break, history_detail),
        _criterion("closed_or_gap_confirmation", "Confirmación cerrada o salto que rompe ambos niveles", confirmation, f"Vela cerrada={hourly_candle_closed}; gap={objective_gap}; cierre={objective_closed}."),
        _criterion("intraday_alignment", "Tendencia de 15m alineada", alignment_value, alignment_detail),
    )
    detected = bool(
        bias is not DirectionBias.NEUTRAL
        and all(
            item.status is EvaluationStatus.CUMPLE
            for item in criteria if item.required
        )
    )
    name = STRATEGY_REGISTRY[strategy_id]["nombre"] if strategy_id in STRATEGY_REGISTRY else "Cambio de Tendencia en Hora"
    return StrategyEvaluation(strategy_id, name, bias, detected, criteria)
