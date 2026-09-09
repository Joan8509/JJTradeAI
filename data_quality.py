"""Validaciones objetivas de integridad antes del análisis metodológico."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import pandas as pd

from analysis_models import GateStatus


@dataclass(frozen=True)
class DataQualityAssessment:
    """Resultado de validar archivos multitemporales."""

    status: GateStatus
    issues: tuple[str, ...]
    latest_sessions: Mapping[str, str]
    candle_counts: Mapping[str, int]


def evaluate_data_quality(
    datasets: Mapping[str, pd.DataFrame],
    *,
    live_market_data: bool = False,
    session_closed: bool = False,
) -> DataQualityAssessment:
    """Rechaza datos vacíos, desordenados, duplicados o desalineados."""
    issues: list[str] = []
    latest_sessions: dict[str, str] = {}
    latest_timestamps: dict[str, pd.Timestamp] = {}
    candle_counts: dict[str, int] = {}
    if not datasets:
        return DataQualityAssessment(
            GateStatus.NO_DISPONIBLE, ("No se cargaron datos.",), {}, {}
        )
    for timeframe, frame in datasets.items():
        candle_counts[timeframe] = len(frame)
        if frame.empty:
            issues.append(f"{timeframe}: archivo vacío.")
            continue
        if "date" not in frame.columns:
            issues.append(f"{timeframe}: falta la columna date.")
            continue
        try:
            dates = pd.to_datetime(frame["date"], errors="raise")
        except (TypeError, ValueError) as error:
            issues.append(f"{timeframe}: fechas inválidas.")
            continue
        if not dates.is_monotonic_increasing:
            issues.append(f"{timeframe}: fechas fuera de orden.")
        if dates.duplicated().any():
            issues.append(f"{timeframe}: existen fechas duplicadas.")
        latest_sessions[timeframe] = dates.iloc[-1].date().isoformat()
        latest_timestamps[timeframe] = pd.Timestamp(dates.iloc[-1])
        ohlc_columns = {"open", "high", "low", "close"}
        if ohlc_columns.issubset(frame.columns):
            numeric_ohlc = frame[list(ohlc_columns)].apply(
                pd.to_numeric, errors="coerce"
            )
            if numeric_ohlc.isna().any().any():
                issues.append(f"{timeframe}: OHLC contiene valores no numericos.")
            else:
                highest_body_value = numeric_ohlc[["open", "low", "close"]].max(axis=1)
                lowest_body_value = numeric_ohlc[["open", "high", "close"]].min(axis=1)
                if (numeric_ohlc["high"] < highest_body_value).any():
                    issues.append(f"{timeframe}: high no respeta coherencia OHLC.")
                if (numeric_ohlc["low"] > lowest_body_value).any():
                    issues.append(f"{timeframe}: low no respeta coherencia OHLC.")
        for column in ("close", "bollinger_mid", "bollinger_upper", "bollinger_lower"):
            if column in frame.columns and pd.isna(frame.iloc[-1][column]):
                issues.append(f"{timeframe}: {column} no está disponible en la última vela.")

    sessions_aligned = len(set(latest_sessions.values())) <= 1
    if not sessions_aligned and live_market_data:
        sessions_aligned = _expected_live_session_alignment(
            latest_sessions,
            latest_timestamps,
            session_closed=session_closed,
        )
    if not sessions_aligned:
        detail = ", ".join(
            f"{timeframe}={session}"
            for timeframe, session in sorted(latest_sessions.items())
        )
        issues.append("Las temporalidades no terminan en la misma sesión: " + detail + ".")
    return DataQualityAssessment(
        status=GateStatus.RECHAZADO if issues else GateStatus.APROBADO,
        issues=tuple(issues),
        latest_sessions=latest_sessions,
        candle_counts=candle_counts,
    )


def _expected_live_session_alignment(
    latest_sessions: Mapping[str, str],
    latest_timestamps: Mapping[str, pd.Timestamp],
    *,
    session_closed: bool,
) -> bool:
    """Acepta cierres superiores previos cuando aún no pueden existir hoy."""
    if "15m" not in latest_sessions:
        return False
    reference = date.fromisoformat(latest_sessions["15m"])
    stamp_15m = latest_timestamps["15m"]
    if stamp_15m.tzinfo is None:
        local_15m = stamp_15m.tz_localize("America/New_York")
    else:
        local_15m = stamp_15m.tz_convert("America/New_York")
    for timeframe, session_text in latest_sessions.items():
        session = date.fromisoformat(session_text)
        if session == reference:
            continue
        age_days = (reference - session).days
        recent_prior_session = 1 <= age_days <= 4
        if timeframe == "1D" and recent_prior_session and not session_closed:
            continue
        if timeframe == "1H" and recent_prior_session and (
            local_15m.hour, local_15m.minute
        ) < (10, 30):
            continue
        return False
    return True
