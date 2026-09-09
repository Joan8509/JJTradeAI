"""Vigencia temporal documentada de setups metodologicos."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


CT15_IDS = {"CT15_ALCISTA", "CT15_BAJISTA"}


def _relevant_strategy_ids(report: Mapping[str, Any]) -> tuple[str, ...]:
    strategies = report.get("strategies", {})
    evaluations = strategies.get("evaluations", ()) if isinstance(strategies, Mapping) else ()
    detected = [
        item for item in evaluations
        if isinstance(item, Mapping) and item.get("detected") is True
    ]
    confirmed = [item for item in detected if item.get("required_criteria_satisfied") is True]
    relevant = confirmed or detected
    return tuple(sorted({str(item.get("strategy_id")) for item in relevant if item.get("strategy_id")}))


def evaluate_setup_timing(report: Mapping[str, Any]) -> dict[str, Any]:
    """Bloquea CT15 fuera de la primera vela sin alterar su deteccion original."""
    strategy_ids = _relevant_strategy_ids(report)
    if not strategy_ids or not set(strategy_ids).issubset(CT15_IDS):
        return {
            "status": "NO_APLICA",
            "strategy_ids": list(strategy_ids),
            "reason": "No existe una ventana temporal cerrada aplicable a todo el setup.",
            "authority": "VIGENCIA_NO_MODIFICA_DETECCION_ORIGINAL",
        }
    data_source = report.get("data_source", {})
    closed_through = data_source.get("closed_through", {}) if isinstance(data_source, Mapping) else {}
    value = closed_through.get("15m") if isinstance(closed_through, Mapping) else None
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return {
            "status": "NO_EVALUADA",
            "strategy_ids": list(strategy_ids),
            "reason": "No existe hora cerrada de 15m para verificar la ventana CT15.",
            "authority": "VIGENCIA_NO_MODIFICA_DETECCION_ORIGINAL",
        }
    if timestamp.tzinfo is None:
        return {
            "status": "NO_EVALUADA",
            "strategy_ids": list(strategy_ids),
            "reason": "La hora de CT15 no incluye zona horaria.",
            "authority": "VIGENCIA_NO_MODIFICA_DETECCION_ORIGINAL",
        }
    local = timestamp.astimezone(ZoneInfo("America/New_York"))
    valid = (local.hour, local.minute) == (9, 30)
    return {
        "status": "VIGENTE" if valid else "VENCIDA",
        "strategy_ids": list(strategy_ids),
        "evaluated_bar_start_et": local.isoformat(),
        "reason": (
            "CT15 corresponde a la primera vela de 15 minutos."
            if valid else
            "CT15 solo es valido en la primera vela de 15 minutos; la ventana ya termino."
        ),
        "authority": "VIGENCIA_NO_MODIFICA_DETECCION_ORIGINAL",
    }
