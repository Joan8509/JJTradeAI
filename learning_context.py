"""Etiquetas objetivas de contexto para aprendizaje posterior de alertas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd


def build_learning_context(
    frame_15m: pd.DataFrame,
    *,
    decision: str,
    market_context: Mapping[str, Any] | None,
    trigger_timestamp: datetime,
) -> dict[str, str]:
    """Clasifica contexto con reglas fijas y devuelve NO_DISPONIBLE si falta evidencia."""
    trend, volatility = _price_regime(frame_15m)
    benchmark_regime, synchronization = _benchmark_regime(market_context or {})
    normalized_decision = decision.strip().upper()
    if normalized_decision == "CALL" and benchmark_regime == "ALCISTA":
        alignment = "ALINEADO"
    elif normalized_decision == "PUT" and benchmark_regime == "BAJISTA":
        alignment = "ALINEADO"
    elif normalized_decision in {"CALL", "PUT"} and benchmark_regime in {"ALCISTA", "BAJISTA"}:
        alignment = "CONTRARIO"
    elif normalized_decision in {"CALL", "PUT"} and benchmark_regime == "MIXTO":
        alignment = "MIXTO"
    else:
        alignment = "NO_DISPONIBLE"
    return {
        "trend_15m": trend,
        "relative_volatility_15m": volatility,
        "session_segment": _session_segment(trigger_timestamp),
        "benchmark_regime": benchmark_regime,
        "benchmark_alignment": alignment,
        "benchmark_synchronization": synchronization,
        "method": "REGLAS_FIJAS_V1",
    }


def context_from_report(report: Mapping[str, Any], decision: str) -> dict[str, str]:
    """Lee etiquetas guardadas y deriva solo benchmarks compatibles en alertas antiguas."""
    stored = report.get("learning_context")
    if isinstance(stored, Mapping):
        result = {str(key): str(value) for key, value in stored.items()}
        result["benchmark_alignment"] = _alignment(decision, result.get("benchmark_regime", "NO_DISPONIBLE"))
        return result
    benchmark, synchronization = _benchmark_regime(report.get("market_context", {}))
    alignment = _alignment(decision, benchmark)
    return {
        "trend_15m": "NO_DISPONIBLE", "relative_volatility_15m": "NO_DISPONIBLE",
        "session_segment": "NO_DISPONIBLE", "benchmark_regime": benchmark,
        "benchmark_alignment": alignment, "benchmark_synchronization": synchronization,
        "method": "COMPATIBILIDAD_ALERTA_ANTIGUA",
    }


def _alignment(decision: str, benchmark: str) -> str:
    if (decision == "CALL" and benchmark == "ALCISTA") or (decision == "PUT" and benchmark == "BAJISTA"):
        return "ALINEADO"
    if decision in {"CALL", "PUT"} and benchmark in {"ALCISTA", "BAJISTA"}:
        return "CONTRARIO"
    if decision in {"CALL", "PUT"} and benchmark == "MIXTO":
        return "MIXTO"
    return "NO_DISPONIBLE"


def _price_regime(frame: pd.DataFrame) -> tuple[str, str]:
    required = {"close", "high", "low"}
    if not required.issubset(frame.columns) or len(frame) < 25:
        return "NO_DISPONIBLE", "NO_DISPONIBLE"
    values = frame.sort_values("date") if "date" in frame.columns else frame
    close = pd.to_numeric(values["close"], errors="coerce")
    high = pd.to_numeric(values["high"], errors="coerce")
    low = pd.to_numeric(values["low"], errors="coerce")
    if close.tail(25).isna().any() or high.tail(25).isna().any() or low.tail(25).isna().any():
        return "NO_DISPONIBLE", "NO_DISPONIBLE"
    average = close.rolling(20).mean()
    if close.iloc[-1] > average.iloc[-1] and average.iloc[-1] > average.iloc[-5]:
        trend = "ALCISTA"
    elif close.iloc[-1] < average.iloc[-1] and average.iloc[-1] < average.iloc[-5]:
        trend = "BAJISTA"
    else:
        trend = "LATERAL"
    ranges = high - low
    baseline = float(ranges.iloc[-25:-5].median())
    recent = float(ranges.iloc[-5:].mean())
    if baseline <= 0:
        volatility = "NO_DISPONIBLE"
    elif recent / baseline >= 1.25:
        volatility = "ALTA"
    elif recent / baseline <= 0.75:
        volatility = "BAJA"
    else:
        volatility = "NORMAL"
    return trend, volatility


def _benchmark_regime(context: Mapping[str, Any]) -> tuple[str, str]:
    benchmarks = context.get("benchmarks", []) if isinstance(context, Mapping) else []
    available = [item for item in benchmarks if item.get("direction") in {"ALCISTA", "BAJISTA", "NEUTRAL"}]
    if not available:
        return "NO_DISPONIBLE", "NO_DISPONIBLE"
    bullish = sum(item.get("direction") == "ALCISTA" for item in available)
    bearish = sum(item.get("direction") == "BAJISTA" for item in available)
    regime = "ALCISTA" if bullish > bearish else "BAJISTA" if bearish > bullish else "MIXTO"
    synchronized = sum(bool(item.get("synchronized")) for item in available)
    sync = "COMPLETA" if synchronized == len(available) else "PARCIAL" if synchronized else "NINGUNA"
    return regime, sync


def _session_segment(timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        return "NO_DISPONIBLE"
    local = timestamp.astimezone(ZoneInfo("America/New_York"))
    minutes = local.hour * 60 + local.minute
    if 570 <= minutes < 660:
        return "APERTURA"
    if 660 <= minutes < 870:
        return "MEDIA_SESION"
    if 870 <= minutes <= 960:
        return "CIERRE"
    return "FUERA_DE_SESION"
