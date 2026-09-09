"""Evaluación multitemporal y conservadora de Efecto Imán."""

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


SOURCE = "docs/strategies/EFECTO_IMAN.md"
ABNORMAL_DISTANCE_LOOKBACK_SESSIONS = 60
ABNORMAL_DISTANCE_MINIMUM_SESSIONS = 20
ABNORMAL_DISTANCE_PERCENTILE = 0.90


def _review(
    criterion_id: str,
    name: str,
    value: bool | None,
    unavailable_detail: str,
) -> CriterionEvaluation:
    """Representa una confirmación que aún no puede inferirse de los datos."""
    if value is None:
        status = EvaluationStatus.NO_DISPONIBLE
        detail = unavailable_detail
    elif value:
        status = EvaluationStatus.CUMPLE
        detail = "Confirmado mediante revisión externa o humana."
    else:
        status = EvaluationStatus.NO_CUMPLE
        detail = "La revisión externa o humana rechazó este requisito."
    return CriterionEvaluation(
        criterion_id=criterion_id,
        name=name,
        status=status,
        required=True,
        detail=detail,
        source=SOURCE,
    )


def _hourly_trend_review(
    hourly: pd.DataFrame,
    *,
    bullish_gap: bool,
    bearish_gap: bool,
    manual_value: bool | None,
) -> CriterionEvaluation:
    """Evalua si las medias de Hora muestran una tendencia sostenida."""
    if manual_value is not None:
        return _review(
            "clear_hourly_trend",
            "Tendencia de Hora clara y sostenida",
            manual_value,
            "Revision manual disponible.",
        )

    if not bullish_gap and not bearish_gap:
        return CriterionEvaluation(
            criterion_id="clear_hourly_trend",
            name="Tendencia de Hora clara y sostenida",
            status=EvaluationStatus.NO_CUMPLE,
            required=True,
            detail="No hay salto direccional para inferir una tendencia compatible.",
            source=SOURCE,
        )

    hourly_dates = pd.to_datetime(hourly["date"])
    unique_days = sorted(hourly_dates.dt.date.unique())
    if len(unique_days) < 2:
        return CriterionEvaluation(
            criterion_id="clear_hourly_trend",
            name="Tendencia de Hora clara y sostenida",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="Se necesitan al menos dos sesiones de velas de Hora.",
            source=SOURCE,
        )

    reviewed_days = unique_days[-2:]
    recent_hours = hourly[hourly_dates.dt.date.isin(reviewed_days)]
    values = recent_hours[["close", "moving_average_20", "moving_average_40"]]
    if values.isna().any().any():
        return CriterionEvaluation(
            criterion_id="clear_hourly_trend",
            name="Tendencia de Hora clara y sostenida",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="Las ultimas dos sesiones de Hora contienen indicadores incompletos.",
            source=SOURCE,
        )

    ma20 = recent_hours["moving_average_20"].astype(float)
    ma40 = recent_hours["moving_average_40"].astype(float)
    close = recent_hours["close"].astype(float)

    if bullish_gap:
        ordered = (ma20 > ma40).all()
        price_aligned = (close >= ma20).all()
        slope_ok = ma20.iloc[-1] > ma20.iloc[0]
        direction = "alcista"
    else:
        ordered = (ma20 < ma40).all()
        price_aligned = (close <= ma20).all()
        slope_ok = ma20.iloc[-1] < ma20.iloc[0]
        direction = "bajista"

    status = (
        EvaluationStatus.CUMPLE
        if ordered and price_aligned and slope_ok
        else EvaluationStatus.NO_CUMPLE
    )
    return CriterionEvaluation(
        criterion_id="clear_hourly_trend",
        name="Tendencia de Hora clara y sostenida",
        status=status,
        required=True,
        detail=(
            f"Tendencia {direction} evaluada en {len(reviewed_days)} sesiones "
            f"y {len(recent_hours)} velas de Hora; orden={ordered}, "
            f"precio_alineado={price_aligned}, pendiente_MA20={slope_ok}."
        ),
        source=SOURCE,
    )


def _path_to_ma20_review(
    first_hour: pd.Series,
    *,
    bullish_gap: bool,
    bearish_gap: bool,
    manual_value: bool | None,
) -> CriterionEvaluation:
    """Evalua si hay medias moviles entre el precio y la MA20 de Hora."""
    if manual_value is not None:
        return _review(
            "clear_path_to_ma20",
            "Camino limpio hacia MA20 de Hora",
            manual_value,
            "Revision manual disponible.",
        )

    if not bullish_gap and not bearish_gap:
        return CriterionEvaluation(
            criterion_id="clear_path_to_ma20",
            name="Camino limpio hacia MA20 de Hora",
            status=EvaluationStatus.NO_CUMPLE,
            required=True,
            detail="No hay salto direccional para trazar el recorrido hacia MA20.",
            source=SOURCE,
        )

    candidate_columns = [
        column
        for column in ("moving_average_40", "moving_average_100", "moving_average_200")
        if column in first_hour.index
    ]
    if not candidate_columns:
        return CriterionEvaluation(
            criterion_id="clear_path_to_ma20",
            name="Camino limpio hacia MA20 de Hora",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="La exportacion no contiene medias moviles adicionales para revisar el recorrido.",
            source=SOURCE,
        )

    price = float(first_hour["close"])
    ma20 = float(first_hour["moving_average_20"])
    blockers: list[str] = []
    for column in candidate_columns:
        value = first_hour[column]
        if pd.isna(value):
            return CriterionEvaluation(
                criterion_id="clear_path_to_ma20",
                name="Camino limpio hacia MA20 de Hora",
                status=EvaluationStatus.NO_DISPONIBLE,
                required=True,
                detail=f"{column} no esta disponible en la primera vela de Hora.",
                source=SOURCE,
            )
        average_value = float(value)
        blocks_bullish_retrace = bullish_gap and ma20 < average_value < price
        blocks_bearish_retrace = bearish_gap and price < average_value < ma20
        if blocks_bullish_retrace or blocks_bearish_retrace:
            blockers.append(f"{column}={average_value:.4f}")

    status = EvaluationStatus.NO_CUMPLE if blockers else EvaluationStatus.CUMPLE
    detail = (
        "Medias entre precio y MA20: " + ", ".join(blockers)
        if blockers
        else "No hay medias moviles exportadas entre el precio y MA20 de Hora."
    )
    return CriterionEvaluation(
        criterion_id="clear_path_to_ma20",
        name="Camino limpio hacia MA20 de Hora",
        status=status,
        required=True,
        detail=detail,
        source=SOURCE,
    )


def _abnormal_distance_review(
    hourly: pd.DataFrame,
    *,
    current_day: object,
    current_distance_pct: float,
    manual_value: bool | None,
) -> CriterionEvaluation:
    """Compara la extension actual con maximos diarios historicos del activo."""
    if manual_value is not None:
        return _review(
            "abnormal_gap",
            "Salto anormalmente alejado de MA20 Hora",
            manual_value,
            "Revision manual disponible.",
        )

    history = hourly.copy()
    history["_session"] = pd.to_datetime(history["date"]).dt.date
    history = history[history["_session"] < current_day]
    ma20 = pd.to_numeric(history["moving_average_20"], errors="coerce")
    close = pd.to_numeric(history["close"], errors="coerce")
    valid = ma20.notna() & close.notna() & ma20.ne(0)
    history = history.loc[valid].copy()
    history["_distance_pct"] = (
        (close.loc[valid] - ma20.loc[valid]).abs() / ma20.loc[valid].abs() * 100
    )
    daily_maximums = (
        history.groupby("_session")["_distance_pct"]
        .max()
        .sort_index()
        .tail(ABNORMAL_DISTANCE_LOOKBACK_SESSIONS)
    )
    sample_size = int(len(daily_maximums))
    if sample_size < ABNORMAL_DISTANCE_MINIMUM_SESSIONS:
        return CriterionEvaluation(
            criterion_id="abnormal_gap",
            name="Salto anormalmente alejado de MA20 Hora",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail=(
                f"Distancia actual={current_distance_pct:.2f}%; historial="
                f"{sample_size}/{ABNORMAL_DISTANCE_MINIMUM_SESSIONS} sesiones minimas."
            ),
            source=SOURCE,
        )

    threshold = float(daily_maximums.quantile(ABNORMAL_DISTANCE_PERCENTILE))
    status = (
        EvaluationStatus.CUMPLE
        if current_distance_pct >= threshold
        else EvaluationStatus.NO_CUMPLE
    )
    return CriterionEvaluation(
        criterion_id="abnormal_gap",
        name="Salto anormalmente alejado de MA20 Hora",
        status=status,
        required=True,
        detail=(
            f"Distancia actual={current_distance_pct:.2f}%; percentil 90="
            f"{threshold:.2f}% sobre {sample_size} sesiones del mismo activo."
        ),
        source=SOURCE,
    )


def evaluate_efecto_iman(
    intraday_15m: pd.DataFrame,
    hourly: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    clear_hourly_trend: bool | None = None,
    abnormal_gap: bool | None = None,
    worden_volume_crossed: bool | None = None,
    path_to_hourly_ma20_clear: bool | None = None,
) -> StrategyEvaluation:
    """Evalúa Efecto Imán sin convertir sus sesgos en orden operativa."""
    requirements = {
        "15m": (
            intraday_15m,
            {"date", "high", "low", "bollinger_upper", "bollinger_lower"},
        ),
        "1H": (
            hourly,
            {"date", "close", "moving_average_20", "moving_average_40"},
        ),
        "1D": (daily, {"date", "open", "close"}),
    }
    for timeframe, (frame, columns) in requirements.items():
        missing = sorted(columns.difference(frame.columns))
        if missing:
            raise ValueError(
                f"Faltan columnas de {timeframe} para Efecto Imán: "
                + ", ".join(missing)
            )
        if frame.empty:
            raise ValueError(f"No hay datos de {timeframe} para Efecto Imán.")
    if len(daily) < 2:
        raise ValueError("Efecto Imán requiere al menos dos sesiones diarias.")

    current_day = pd.Timestamp(daily.iloc[-1]["date"]).date()
    current_candles = intraday_15m[
        pd.to_datetime(intraday_15m["date"]).dt.date == current_day
    ]
    if current_candles.empty:
        raise ValueError("No existe una vela de 15m para la última sesión diaria.")

    current_hours = hourly[pd.to_datetime(hourly["date"]).dt.date == current_day]
    if current_hours.empty:
        raise ValueError("No existe una vela de Hora para la última sesión diaria.")

    first_15m = current_candles.iloc[0]
    first_hour = current_hours.iloc[0]
    latest_day = daily.iloc[-1]
    previous_day = daily.iloc[-2]
    values = [
        first_15m["high"],
        first_15m["low"],
        first_15m["bollinger_upper"],
        first_15m["bollinger_lower"],
        first_hour["close"],
        first_hour["moving_average_20"],
        first_hour["moving_average_40"],
        latest_day["open"],
        previous_day["close"],
    ]
    if pd.isna(values).any():
        raise ValueError("Los últimos datos contienen indicadores incompletos.")

    gap = float(latest_day["open"]) - float(previous_day["close"])
    bullish_gap = gap > 0
    bearish_gap = gap < 0
    hourly_ma20 = float(first_hour["moving_average_20"])
    hourly_ma40 = float(first_hour["moving_average_40"])
    hourly_close = float(first_hour["close"])
    distance_pct = (
        abs(hourly_close - hourly_ma20) / abs(hourly_ma20) * 100
        if hourly_ma20 != 0
        else float("nan")
    )

    if bullish_gap:
        strategy_id = "EFECTO_IMAN_TENDENCIA_ALCISTA"
        bias = DirectionBias.PUT
        ma_order_ok = hourly_ma20 > hourly_ma40
        first_candle_outside = (
            float(first_15m["low"]) > float(first_15m["bollinger_upper"])
        )
    elif bearish_gap:
        strategy_id = "EFECTO_IMAN_TENDENCIA_BAJISTA"
        bias = DirectionBias.CALL
        ma_order_ok = hourly_ma20 < hourly_ma40
        first_candle_outside = (
            float(first_15m["high"]) < float(first_15m["bollinger_lower"])
        )
    else:
        strategy_id = "SIN_EFECTO_IMAN"
        bias = DirectionBias.NEUTRAL
        ma_order_ok = False
        first_candle_outside = False

    criteria = (
        CriterionEvaluation(
            criterion_id="directional_gap",
            name="Salto en la dirección de la tendencia",
            status=(
                EvaluationStatus.CUMPLE
                if bullish_gap or bearish_gap
                else EvaluationStatus.NO_CUMPLE
            ),
            required=True,
            detail=f"Diferencia apertura/cierre anterior: {gap:.4f}.",
            source=SOURCE,
        ),
        CriterionEvaluation(
            criterion_id="hourly_ma_order",
            name="Orden direccional de medias 20/40 en Hora",
            status=(
                EvaluationStatus.CUMPLE
                if ma_order_ok
                else EvaluationStatus.NO_CUMPLE
            ),
            required=True,
            detail=f"MA20={hourly_ma20:.4f}; MA40={hourly_ma40:.4f}.",
            source=SOURCE,
        ),
        _hourly_trend_review(
            hourly,
            bullish_gap=bullish_gap,
            bearish_gap=bearish_gap,
            manual_value=clear_hourly_trend,
        ),
        _abnormal_distance_review(
            hourly,
            current_day=current_day,
            current_distance_pct=distance_pct,
            manual_value=abnormal_gap,
        ),
        CriterionEvaluation(
            criterion_id="first_15m_outside_bollinger",
            name="Primera vela de 15m completamente fuera de Bollinger",
            status=(
                EvaluationStatus.CUMPLE
                if first_candle_outside
                else EvaluationStatus.NO_CUMPLE
            ),
            required=True,
            detail="Se compara toda la vela con el disipador correspondiente.",
            source=SOURCE,
        ),
        CriterionEvaluation(
            criterion_id="second_15m_started",
            name="Inicio de la segunda vela de 15m",
            status=(
                EvaluationStatus.CUMPLE
                if len(current_candles) >= 2
                else EvaluationStatus.REQUIERE_REVISION
            ),
            required=True,
            detail=f"Velas disponibles en la sesión: {len(current_candles)}.",
            source=SOURCE,
        ),
        _review(
            "worden_volume_cross",
            "Volumen de Hora cruza la línea roja de Worden",
            worden_volume_crossed,
            "La exportación no contiene la serie de la línea roja para calcular el cruce.",
        ),
        _path_to_ma20_review(
            first_hour,
            bullish_gap=bullish_gap,
            bearish_gap=bearish_gap,
            manual_value=path_to_hourly_ma20_clear,
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
        else "Efecto Imán"
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name=name,
        bias=bias,
        detected=detected,
        criteria=criteria,
    )
