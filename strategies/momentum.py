"""Detector multitemporal de Momentum sin probabilidades artificiales."""

import pandas as pd

from analysis_models import CriterionEvaluation, DirectionBias, EvaluationStatus, StrategyEvaluation
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/MOMENTUM.md"
PRIOR_TREND_MINIMUM_BARS = 10
PRIOR_TREND_LOOKBACK = 20
PRIOR_ALIGNMENT_RATIO = 0.70
RECENT_HOURLY_BREAKOUT_BARS = 20
RECENT_DAILY_BREAKOUT_BARS = 5


def _criterion(identifier: str, name: str, value: bool | None, detail: str) -> CriterionEvaluation:
    status = EvaluationStatus.NO_DISPONIBLE if value is None else EvaluationStatus.CUMPLE if value else EvaluationStatus.NO_CUMPLE
    return CriterionEvaluation(identifier, name, status, True, detail, SOURCE)


def _run_start(mask: pd.Series) -> int | None:
    """Devuelve el inicio de la secuencia direccional que termina en la última vela."""
    values = mask.fillna(False).astype(bool).tolist()
    if not values or not values[-1]:
        return None
    start = len(values) - 1
    while start > 0 and values[start - 1]:
        start -= 1
    return start


def _prior_trend_criterion(daily: pd.DataFrame, breakout_start: int | None, bullish: bool) -> tuple[bool | None, str]:
    if breakout_start is None:
        return None, "No existe una ruptura diaria direccional identificable."
    prior = daily.iloc[max(0, breakout_start - PRIOR_TREND_LOOKBACK):breakout_start]
    if len(prior) < PRIOR_TREND_MINIMUM_BARS:
        return None, f"Solo hay {len(prior)} velas previas; se requieren al menos {PRIOR_TREND_MINIMUM_BARS}."
    opposite = (prior["close"] < prior["moving_average_20"]) & (prior["close"] < prior["moving_average_40"])
    slope = prior["moving_average_20"].diff()
    slope_opposite = slope < 0 if bullish else slope > 0
    if not bullish:
        opposite = (prior["close"] > prior["moving_average_20"]) & (prior["close"] > prior["moving_average_40"])
    ratio = (opposite & slope_opposite.fillna(False)).mean()
    return bool(ratio >= PRIOR_ALIGNMENT_RATIO), f"Alineación contraria previa Diario={ratio:.0%}; mínimo={PRIOR_ALIGNMENT_RATIO:.0%}."


def _prior_structure_criterion(hourly: pd.DataFrame, breakout_start: int | None, bullish: bool) -> tuple[bool | None, str]:
    if breakout_start is None:
        return None, "No existe una ruptura horaria direccional identificable."
    prior = hourly.iloc[max(0, breakout_start - PRIOR_TREND_LOOKBACK):breakout_start]
    if len(prior) < PRIOR_TREND_MINIMUM_BARS:
        return None, f"Solo hay {len(prior)} velas previas; se requieren al menos {PRIOR_TREND_MINIMUM_BARS}."
    aligned = (prior["moving_average_100"] < prior["moving_average_200"]) if bullish else (prior["moving_average_100"] > prior["moving_average_200"])
    ratio = aligned.mean()
    return bool(ratio >= PRIOR_ALIGNMENT_RATIO), f"Estructura 100/200 contraria previa Hora={ratio:.0%}; mínimo={PRIOR_ALIGNMENT_RATIO:.0%}."


def evaluate_momentum(
    hourly: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    prolonged_prior_trend: bool | None = None,
    prior_long_term_structure: bool | None = None,
    breakouts_confirmed_closed: bool | None = None,
    path_clear: bool | None = None,
) -> StrategyEvaluation:
    """Evalúa el giro de tendencia, las medias y la volatilidad con velas cerradas."""
    hour_columns = {"close", "moving_average_20", "moving_average_40", "moving_average_100", "moving_average_200"}
    day_columns = {"close", "moving_average_20", "moving_average_40", "bollinger_mid_slope", "bollinger_upper_change", "bollinger_lower_change"}
    for label, frame, columns in (("Hora", hourly, hour_columns), ("Diario", daily, day_columns)):
        missing = sorted(columns.difference(frame.columns))
        if missing:
            raise ValueError(f"Faltan columnas de {label} para Momentum: " + ", ".join(missing))
        if frame.empty or frame.iloc[-1][list(columns)].isna().any():
            raise ValueError(f"Los datos de {label} para Momentum están incompletos.")

    hour, day = hourly.iloc[-1], daily.iloc[-1]
    hc, dc = float(hour["close"]), float(day["close"])
    hmas = [float(hour[f"moving_average_{period}"]) for period in (20, 40, 100, 200)]
    dmas = [float(day[f"moving_average_{period}"]) for period in (20, 40)]
    above_hour, below_hour = all(hc > value for value in hmas), all(hc < value for value in hmas)
    above_day, below_day = all(dc > value for value in dmas), all(dc < value for value in dmas)
    daily_slope = float(day["bollinger_mid_slope"])
    volatility_open = float(day["bollinger_upper_change"]) > 0 and float(day["bollinger_lower_change"]) < 0

    if above_hour and above_day and daily_slope > 0:
        strategy_id, bias, ma_cross = "MOMENTUM_ALCISTA", DirectionBias.CALL, hmas[0] > hmas[1]
    elif below_hour and below_day and daily_slope < 0:
        strategy_id, bias, ma_cross = "MOMENTUM_BAJISTA", DirectionBias.PUT, hmas[0] < hmas[1]
    else:
        strategy_id, bias, ma_cross = "SIN_MOMENTUM", DirectionBias.NEUTRAL, False

    directional_state = (above_hour and above_day) or (below_hour and below_day)
    bullish = bias is DirectionBias.CALL
    hourly_direction = pd.concat([
        (hourly["close"] > hourly[f"moving_average_{period}"]) if bullish else (hourly["close"] < hourly[f"moving_average_{period}"])
        for period in (20, 40, 100, 200)
    ], axis=1).all(axis=1)
    daily_direction = pd.concat([
        (daily["close"] > daily[f"moving_average_{period}"]) if bullish else (daily["close"] < daily[f"moving_average_{period}"])
        for period in (20, 40)
    ], axis=1).all(axis=1)
    hourly_start = _run_start(hourly_direction) if bias is not DirectionBias.NEUTRAL else None
    daily_start = _run_start(daily_direction) if bias is not DirectionBias.NEUTRAL else None
    prolonged_value, prolonged_detail = _prior_trend_criterion(daily, daily_start, bullish)
    structure_value, structure_detail = _prior_structure_criterion(hourly, hourly_start, bullish)
    closed_breakouts = (
        hourly_start is not None and daily_start is not None
        and len(hourly) - hourly_start <= RECENT_HOURLY_BREAKOUT_BARS
        and len(daily) - daily_start <= RECENT_DAILY_BREAKOUT_BARS
    )
    if prolonged_prior_trend is not None:
        prolonged_value, prolonged_detail = prolonged_prior_trend, "Criterio manual suministrado por compatibilidad."
    if prior_long_term_structure is not None:
        structure_value, structure_detail = prior_long_term_structure, "Criterio manual suministrado por compatibilidad."
    if breakouts_confirmed_closed is not None:
        closed_breakouts = breakouts_confirmed_closed
    breakout_detail = f"Inicio de secuencia: Hora={hourly_start}, Diario={daily_start}; máximo={RECENT_HOURLY_BREAKOUT_BARS}H/{RECENT_DAILY_BREAKOUT_BARS}D."

    criteria = (
        _criterion("prolonged_prior_trend", "Tendencia prolongada previa", prolonged_value, prolonged_detail),
        _criterion("prior_long_term_structure", "Estructura previa 100/200 compatible", structure_value, structure_detail),
        _criterion("hourly_all_ma_break", "Precio supera 20/40/100/200 de Hora", above_hour or below_hour, f"Cierre Hora={hc:.4f}; medias={hmas}."),
        _criterion("hourly_20_40_cross", "Orden 20/40 de Hora acompaña Momentum", ma_cross, f"MA20={hmas[0]:.4f}; MA40={hmas[1]:.4f}."),
        _criterion("daily_20_40_break", "Precio supera 20/40 de Diario", above_day or below_day, f"Cierre Diario={dc:.4f}; medias={dmas}."),
        _criterion("daily_midpoint_direction", "Punto Medio Diario acompaña la dirección", (bias is DirectionBias.CALL and daily_slope > 0) or (bias is DirectionBias.PUT and daily_slope < 0), f"Pendiente diaria={daily_slope:.4f}."),
        _criterion("daily_volatility", "Volatilidad Diario abre en la dirección", volatility_open, "Sin volatilidad diaria el escenario es falso Momentum."),
        _criterion("closed_breakouts", "Rupturas confirmadas mediante cierre", closed_breakouts, breakout_detail),
        _criterion("clear_path", "Camino libre al siguiente nivel", path_clear, "Un techo o piso cercano invalida la calidad del recorrido."),
    )
    detected = bool(
        bias is not DirectionBias.NEUTRAL
        and all(
            item.status is EvaluationStatus.CUMPLE
            for item in criteria if item.required
        )
    )
    name = STRATEGY_REGISTRY[strategy_id]["nombre"] if strategy_id in STRATEGY_REGISTRY else "Momentum"
    return StrategyEvaluation(strategy_id, name, bias, detected, criteria)
