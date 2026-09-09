"""Detector conservador de un primer salto respetado al cierre.

No predice la magnitud ni garantiza un salto posterior. Los criterios que no
pueden deducirse de OHLC permanecen como NO_DISPONIBLE o REQUIERE_REVISION.
"""

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/PRIMER_SALTO.md"
PRIOR_DAILY_BARS = 5
PRIOR_DIRECTIONAL_RATIO = 0.75


def _manual_criterion(
    criterion_id: str,
    name: str,
    value: bool | None,
    *,
    required: bool,
    unavailable_detail: str,
) -> CriterionEvaluation:
    """Convierte una revisión externa opcional en evidencia auditable."""
    if value is None:
        status = EvaluationStatus.NO_DISPONIBLE
        detail = unavailable_detail
    elif value:
        status = EvaluationStatus.CUMPLE
        detail = "Confirmado por revisión externa o humana."
    else:
        status = EvaluationStatus.NO_CUMPLE
        detail = "La revisión externa o humana no confirmó este criterio."
    return CriterionEvaluation(
        criterion_id=criterion_id,
        name=name,
        status=status,
        required=required,
        detail=detail,
        source=SOURCE,
    )


def _projection(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce")
    count = len(numeric)
    x_mean = (count - 1) / 2
    mean = float(numeric.mean())
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = sum((index - x_mean) * (float(value) - mean) for index, value in enumerate(numeric)) / denominator
    return slope, mean - slope * x_mean + slope * count


def _objective_prior(daily: pd.DataFrame, bullish_gap: bool, bearish_gap: bool) -> tuple[bool | None, bool | None, str]:
    required = {"high", "low", "close"}
    prior = daily.iloc[-(PRIOR_DAILY_BARS + 1):-1]
    if len(prior) < PRIOR_DAILY_BARS or not required.issubset(daily.columns):
        return None, None, f"Se requieren {PRIOR_DAILY_BARS} sesiones previas con high/low/close."
    if prior[list(required)].isna().any().any():
        return None, None, "El historial diario previo está incompleto."
    close_slope, _ = _projection(prior["close"])
    changes = pd.to_numeric(prior["close"], errors="raise").diff().dropna()
    if bullish_gap:
        ratio = float((changes <= 0).mean())
        trend = close_slope < 0 and ratio >= PRIOR_DIRECTIONAL_RATIO
        line_slope, line_value = _projection(prior["high"])
        line_valid = line_slope <= 0
        broken = float(daily.iloc[-1]["close"]) > line_value
    elif bearish_gap:
        ratio = float((changes >= 0).mean())
        trend = close_slope > 0 and ratio >= PRIOR_DIRECTIONAL_RATIO
        line_slope, line_value = _projection(prior["low"])
        line_valid = line_slope >= 0
        broken = float(daily.iloc[-1]["close"]) < line_value
    else:
        return False, False, "No existe salto direccional."
    detail = f"Alineación previa={ratio:.0%}; pendiente cierre={close_slope:.4f}; línea={line_value:.4f}, pendiente={line_slope:.4f}."
    return bool(trend), bool(line_valid and broken), detail


def _hourly_confirmation(hourly: pd.DataFrame | None, bullish: bool, bearish: bool) -> tuple[bool | None, str]:
    required = {"open", "close"}
    if hourly is None or hourly.empty or not required.issubset(hourly.columns):
        return None, "No hay una vela horaria cerrada disponible."
    row = hourly.iloc[-1]
    if row[list(required)].isna().any():
        return None, "La última vela horaria está incompleta."
    confirmed = (bullish and float(row["close"]) > float(row["open"])) or (bearish and float(row["close"]) < float(row["open"]))
    return bool(confirmed), f"Hora open={float(row['open']):.4f}, close={float(row['close']):.4f}."


def evaluate_first_jump_setup(
    daily_df: pd.DataFrame,
    *,
    hourly: pd.DataFrame | None = None,
    session_closed: bool = False,
    prior_trend_confirmed: bool | None = None,
    trendline_broken: bool | None = None,
    hourly_confirmation_closed: bool | None = None,
    news_clear: bool | None = None,
    path_clear: bool | None = None,
) -> StrategyEvaluation:
    """Evalúa si la última sesión forma un primer salto respetado.

    ``session_closed`` debe ser explícito porque la estrategia se valida cerca
    del cierre. Una vela diaria en formación no puede confirmar el patrón.
    """
    required_columns = {"open", "close"}
    missing = sorted(required_columns.difference(daily_df.columns))
    if missing:
        raise ValueError(
            "Faltan columnas para evaluar Primer Salto: " + ", ".join(missing)
        )
    if len(daily_df) < 2:
        raise ValueError("Primer Salto requiere al menos dos sesiones diarias.")

    previous = daily_df.iloc[-2]
    latest = daily_df.iloc[-1]
    if pd.isna(previous["close"]) or latest[["open", "close"]].isna().any():
        raise ValueError("Las últimas sesiones contienen precios incompletos.")

    previous_close = float(previous["close"])
    current_open = float(latest["open"])
    current_close = float(latest["close"])
    bullish_gap = current_open > previous_close
    bearish_gap = current_open < previous_close
    held = (bullish_gap and current_close > previous_close) or (
        bearish_gap and current_close < previous_close
    )
    objective_trend, objective_break, objective_detail = _objective_prior(
        daily_df, bullish_gap, bearish_gap
    )
    objective_hourly, hourly_detail = _hourly_confirmation(hourly, bullish_gap, bearish_gap)
    if prior_trend_confirmed is None:
        prior_trend_confirmed = objective_trend
    if trendline_broken is None:
        trendline_broken = objective_break
    if hourly_confirmation_closed is None:
        hourly_confirmation_closed = objective_hourly

    if bullish_gap:
        strategy_id = "PRIMER_SALTO_RESPETADO_ALCISTA"
        bias = DirectionBias.CALL
        direction = "alcista"
    elif bearish_gap:
        strategy_id = "PRIMER_SALTO_RESPETADO_BAJISTA"
        bias = DirectionBias.PUT
        direction = "bajista"
    else:
        strategy_id = "SIN_PRIMER_SALTO"
        bias = DirectionBias.NEUTRAL
        direction = "neutral"

    gap_criterion = CriterionEvaluation(
        criterion_id="daily_gap",
        name="Salto frente al cierre anterior",
        status=(
            EvaluationStatus.CUMPLE
            if bullish_gap or bearish_gap
            else EvaluationStatus.NO_CUMPLE
        ),
        required=True,
        detail=(
            f"Apertura {current_open:.4f}, cierre anterior {previous_close:.4f}; "
            f"dirección {direction}."
        ),
        source=SOURCE,
    )
    close_criterion = CriterionEvaluation(
        criterion_id="jump_held_at_close",
        name="Salto respetado al cierre",
        status=(
            EvaluationStatus.REQUIERE_REVISION
            if not session_closed
            else EvaluationStatus.CUMPLE
            if held
            else EvaluationStatus.NO_CUMPLE
        ),
        required=True,
        detail=(
            "La sesión aún no fue marcada como cerrada."
            if not session_closed
            else f"Cierre de sesión: {current_close:.4f}."
        ),
        source=SOURCE,
    )

    criteria = (
        gap_criterion,
        close_criterion,
        _manual_criterion(
            "prior_trend",
            "Tendencia previa suficiente",
            prior_trend_confirmed,
            required=True,
            unavailable_detail="Requiere panorama de Hora y duración validada.",
        ),
        _manual_criterion(
            "trendline_break",
            "Ruptura de línea de tendencia y niveles",
            trendline_broken,
            required=True,
            unavailable_detail="La línea de tendencia aún requiere revisión humana.",
        ),
        _manual_criterion(
            "hourly_closed_confirmation",
            "Confirmación de Hora cerrada para entrada nueva",
            hourly_confirmation_closed,
            required=True,
            unavailable_detail="No se recibió confirmación de una vela de Hora cerrada.",
        ),
        _manual_criterion(
            "news_clear",
            "Sin noticia invalidante",
            news_clear,
            required=True,
            unavailable_detail="No se ha revisado un calendario actualizado de noticias.",
        ),
        _manual_criterion(
            "path_clear",
            "Espacio hasta el siguiente techo o piso",
            path_clear,
            required=True,
            unavailable_detail="El siguiente nivel relevante no ha sido validado.",
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
        else "Primer Salto"
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name=name,
        bias=bias,
        detected=detected,
        criteria=criteria,
    )
