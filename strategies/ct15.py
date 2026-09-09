"""Detector auditable de Cambio de Tendencia en 15 minutos (CT15)."""

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/CT15.md"
MINIMUM_TRENDLINE_BARS = 8
LATERAL_MAX_RANGE_PCT = 1.0


def _criterion(
    criterion_id: str,
    name: str,
    value: bool | None,
    detail: str,
    *,
    required: bool = True,
) -> CriterionEvaluation:
    if value is None:
        status = EvaluationStatus.NO_DISPONIBLE
    elif value:
        status = EvaluationStatus.CUMPLE
    else:
        status = EvaluationStatus.NO_CUMPLE
    return CriterionEvaluation(
        criterion_id=criterion_id,
        name=name,
        status=status,
        required=required,
        detail=detail,
        source=SOURCE,
    )


def _inside_bollinger(frame: pd.DataFrame) -> bool | None:
    required = {"close", "bollinger_upper", "bollinger_lower"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    row = frame.iloc[-1]
    if row[list(required)].isna().any():
        return None
    return float(row["bollinger_lower"]) <= float(row["close"]) <= float(
        row["bollinger_upper"]
    )


def _linear_projection(values: pd.Series) -> tuple[float, float]:
    """Calcula pendiente y proyección de mínimos cuadrados un paso adelante."""
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    count = len(numeric)
    x_mean = (count - 1) / 2
    y_mean = float(numeric.mean())
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = sum((index - x_mean) * (float(value) - y_mean) for index, value in enumerate(numeric)) / denominator
    intercept = y_mean - slope * x_mean
    return slope, intercept + slope * count


def _objective_context(
    previous_session: pd.DataFrame,
    *,
    bullish: bool,
    current_open: float,
) -> tuple[bool | None, bool | None, bool | None, str]:
    required = {"high", "low", "close"}
    if len(previous_session) < MINIMUM_TRENDLINE_BARS or not required.issubset(previous_session.columns):
        detail = f"Se requieren {MINIMUM_TRENDLINE_BARS} velas previas con high/low/close."
        return None, None, None, detail
    values = previous_session.tail(MINIMUM_TRENDLINE_BARS)
    if values[list(required)].isna().any().any():
        return None, None, None, "La sesión previa contiene precios incompletos."
    closes = pd.to_numeric(values["close"], errors="raise")
    close_slope, _ = _linear_projection(closes)
    mean_close = abs(float(closes.mean()))
    range_pct = (float(values["high"].max()) - float(values["low"].min())) / mean_close * 100 if mean_close else float("inf")
    lateral = range_pct <= LATERAL_MAX_RANGE_PCT
    prior_trend = (close_slope <= 0 or lateral) if bullish else (close_slope >= 0 or lateral)
    line_column = "high" if bullish else "low"
    line_slope, projected_line = _linear_projection(values[line_column])
    side_correct = line_slope <= 0 if bullish else line_slope >= 0
    broken = current_open > projected_line if bullish else current_open < projected_line
    detail = (
        f"Pendiente cierre={close_slope:.4f}; rango={range_pct:.2f}%; "
        f"línea {line_column} pendiente={line_slope:.4f}, proyección={projected_line:.4f}."
    )
    return bool(prior_trend), bool(side_correct), bool(side_correct and broken), detail


def evaluate_ct15(
    intraday_15m: pd.DataFrame,
    *,
    hourly: pd.DataFrame | None = None,
    daily: pd.DataFrame | None = None,
    prior_trend_valid: bool | None = None,
    trendline_drawn_correctly: bool | None = None,
    trendline_broken: bool | None = None,
) -> StrategyEvaluation:
    """Evalúa exclusivamente la primera vela de la sesión más reciente."""
    required = {
        "date",
        "open",
        "close",
        "bollinger_mid",
        "bollinger_upper",
        "bollinger_lower",
        "bollinger_mid_slope",
        "bollinger_both_expanding",
    }
    missing = sorted(required.difference(intraday_15m.columns))
    if missing:
        raise ValueError("Faltan columnas de 15m para CT15: " + ", ".join(missing))
    if intraday_15m.empty:
        raise ValueError("No hay velas de 15m para evaluar CT15.")

    data = intraday_15m.copy()
    data["_session"] = pd.to_datetime(data["date"]).dt.date
    sessions = sorted(data["_session"].unique())
    if len(sessions) < 2:
        raise ValueError("CT15 requiere al menos dos sesiones de 15 minutos.")
    previous_session = data[data["_session"] == sessions[-2]]
    current_session = data[data["_session"] == sessions[-1]]
    previous = previous_session.iloc[-1]
    first = current_session.iloc[0]
    numeric = [
        previous["close"],
        previous["bollinger_mid"],
        first["open"],
        first["close"],
        first["bollinger_mid"],
        first["bollinger_upper"],
        first["bollinger_lower"],
        first["bollinger_mid_slope"],
    ]
    if pd.isna(numeric).any():
        raise ValueError("CT15 no puede evaluarse con indicadores incompletos.")

    prior_close = float(previous["close"])
    prior_mid = float(previous["bollinger_mid"])
    current_open = float(first["open"])
    first_close = float(first["close"])
    current_mid = float(first["bollinger_mid"])
    bullish_gap = current_open > prior_close
    bearish_gap = current_open < prior_close
    bullish_setup = bullish_gap and prior_close < prior_mid
    bearish_setup = bearish_gap and prior_close > prior_mid

    if bullish_setup:
        strategy_id = "CT15_ALCISTA"
        bias = DirectionBias.CALL
        prior_side_ok = True
        midpoint_broken = current_open > current_mid
        midpoint_turning = float(first["bollinger_mid_slope"]) > 0
    elif bearish_setup:
        strategy_id = "CT15_BAJISTA"
        bias = DirectionBias.PUT
        prior_side_ok = True
        midpoint_broken = current_open < current_mid
        midpoint_turning = float(first["bollinger_mid_slope"]) < 0
    else:
        strategy_id = "SIN_CT15"
        bias = DirectionBias.NEUTRAL
        prior_side_ok = False
        midpoint_broken = False
        midpoint_turning = False

    objective_trend, objective_drawn, objective_broken, trendline_detail = (
        _objective_context(
            previous_session,
            bullish=bias is DirectionBias.CALL,
            current_open=current_open,
        )
        if bias is not DirectionBias.NEUTRAL
        else (False, False, False, "No existe geometría direccional CT15.")
    )
    if prior_trend_valid is None:
        prior_trend_valid = objective_trend
    if trendline_drawn_correctly is None:
        trendline_drawn_correctly = objective_drawn
    if trendline_broken is None:
        trendline_broken = objective_broken

    volatility_opening = bool(first["bollinger_both_expanding"])
    first_inside = float(first["bollinger_lower"]) <= first_close <= float(
        first["bollinger_upper"]
    )
    criteria = (
        _criterion(
            "prior_trend",
            "Tendencia previa válida para la variante",
            prior_trend_valid,
            trendline_detail,
        ),
        _criterion(
            "trendline_drawn",
            "Línea de tendencia trazada por el lado correcto",
            trendline_drawn_correctly,
            trendline_detail,
        ),
        _criterion(
            "prior_close_vs_midpoint",
            "Cierre previo al lado requerido del Punto Medio",
            prior_side_ok,
            f"Cierre previo={prior_close:.4f}; Punto Medio previo={prior_mid:.4f}.",
        ),
        _criterion(
            "directional_gap",
            "Salto en la dirección de CT15",
            bullish_gap or bearish_gap,
            f"Apertura={current_open:.4f}; cierre previo={prior_close:.4f}.",
        ),
        _criterion(
            "midpoint_break",
            "El salto rompe el Punto Medio",
            midpoint_broken,
            f"Apertura={current_open:.4f}; Punto Medio actual={current_mid:.4f}.",
        ),
        _criterion(
            "trendline_break",
            "El salto rompe la línea de tendencia",
            trendline_broken,
            trendline_detail,
        ),
        _criterion(
            "volatility_opening",
            "Apertura simultánea de los disipadores",
            volatility_opening,
            "Se verifica disipador superior subiendo e inferior bajando.",
        ),
        _criterion(
            "first_15m_candle",
            "Evaluación sobre la primera vela de 15 minutos",
            True,
            f"Primera vela de la sesión: {first['date']}.",
        ),
        _criterion(
            "inside_15m_bollinger",
            "Primera vela dentro de Bollinger 15m",
            first_inside,
            "Confirmación adicional; un CT15 alcista expuesto se considera falso.",
            required=False,
        ),
        _criterion(
            "midpoint_turning",
            "Punto Medio virándose en la dirección esperada",
            midpoint_turning,
            f"Pendiente del Punto Medio={float(first['bollinger_mid_slope']):.4f}.",
            required=False,
        ),
        _criterion(
            "hourly_inside_bollinger",
            "Hora dentro de Bollinger",
            _inside_bollinger(hourly) if hourly is not None else None,
            "Confirmación adicional de Hora.",
            required=False,
        ),
        _criterion(
            "daily_inside_bollinger",
            "Diario dentro de Bollinger",
            _inside_bollinger(daily) if daily is not None else None,
            "Confirmación adicional de Diario.",
            required=False,
        ),
    )
    # CT15 es una estrategia valida solamente cuando se satisface la secuencia
    # documental completa. Un salto que cruza el Punto Medio es apenas un
    # candidato y no debe publicarse como estrategia detectada si la tendencia
    # previa, la geometria o la ruptura de la linea fallan o no estan disponibles.
    required_sequence = (
        prior_trend_valid is True
        and trendline_drawn_correctly is True
        and prior_side_ok
        and (bullish_gap or bearish_gap)
        and midpoint_broken
        and trendline_broken is True
        and volatility_opening
    )
    # La metodologia identifica como falso CT15 alcista una apertura expuesta.
    # No se infiere la misma invalidacion para la variante bajista porque aun no
    # esta documentada oficialmente.
    exposure_valid = first_inside if bullish_setup else True
    detected = bool(required_sequence and exposure_valid)
    name = (
        STRATEGY_REGISTRY[strategy_id]["nombre"]
        if strategy_id in STRATEGY_REGISTRY
        else "Cambio de Tendencia en 15"
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name=name,
        bias=bias,
        detected=detected,
        criteria=criteria,
    )
