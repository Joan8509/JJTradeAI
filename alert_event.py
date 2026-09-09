"""Clasificación de eventos del scanner sin alterar la decisión de trading."""

from __future__ import annotations

from typing import Any, Mapping


def setup_signature(report: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Identidad estable del setup que merece atencion humana."""
    timing = report.get("setup_timing", {})
    if isinstance(timing, Mapping) and timing.get("status") == "VENCIDA":
        return ()
    strategies = report.get("strategies", {})
    evaluations = strategies.get("evaluations", ()) if isinstance(strategies, Mapping) else ()
    detected = [
        item for item in evaluations
        if isinstance(item, Mapping) and item.get("detected") is True
    ]
    confirmed = [item for item in detected if item.get("required_criteria_satisfied") is True]
    relevant = confirmed or detected
    signature = tuple(sorted(
        (str(item.get("strategy_id", "")), str(item.get("bias", "NEUTRAL")))
        for item in relevant if item.get("strategy_id")
    ))
    if signature:
        return signature
    summary = report.get("strategy_summary", {})
    if isinstance(summary, Mapping) and int(summary.get("detected", 0) or 0) > 0:
        return ((
            "__SUMMARY__",
            f"CONFIRMED_{int(summary.get('confirmed', 0) or 0)}_DETECTED_{int(summary.get('detected', 0) or 0)}",
        ),)
    return ()


def classify_alert_transition(
    report: Mapping[str, Any], previous_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Avisa solo cuando un setup aparece, cambia o termina."""
    current = classify_alert_event(report)
    if current["type"] == "INCIDENTE_DATOS":
        return current
    current_signature = setup_signature(report)
    timing = report.get("setup_timing", {})
    if isinstance(timing, Mapping) and timing.get("status") == "VENCIDA":
        return _event(
            "SETUP_VENCIDO", "REGISTRO", "INFO", False,
            str(timing.get("reason", "El setup esta fuera de su ventana metodologica.")),
        )
    if previous_report is None:
        return current
    previous_signature = setup_signature(previous_report)
    if current_signature and current_signature == previous_signature:
        return _event(
            "SETUP_SIN_CAMBIO", "REGISTRO", "INFO", False,
            "El setup activo no cambio desde la evaluacion anterior.",
        )
    if not current_signature and previous_signature:
        return _event(
            "SETUP_FINALIZADO", "REGISTRO", "INFO", False,
            "El setup anterior dejo de estar activo.",
        )
    return current


def classify_alert_event(report: Mapping[str, Any]) -> dict[str, Any]:
    """Distingue setups, incidentes de datos y escaneos informativos."""
    freshness = report.get("live_data_freshness", {})
    reconciliation = report.get("market_data_reconciliation", {})
    if freshness.get("status") == "RECHAZADO" or reconciliation.get("status") in {"RECHAZADO", "NO_DISPONIBLE"}:
        return _event("INCIDENTE_DATOS", "SISTEMA", "ALTA", True, "La integridad o frescura del bloque requiere atención.")
    summary = report.get("strategy_summary", {})
    confirmed = int(summary.get("confirmed", 0) or 0)
    detected = int(summary.get("detected", 0) or 0)
    if confirmed > 0:
        return _event("SETUP_CONFIRMADO", "MERCADO", "ALTA", True, f"{confirmed} estrategia(s) confirmada(s).")
    if detected > 0:
        return _event("SETUP_DETECTADO", "MERCADO", "MEDIA", True, f"{detected} estrategia(s) detectada(s), aún incompletas.")
    return _event("SIN_SETUP", "REGISTRO", "INFO", False, "Escaneo conservado sin estrategia detectada.")


def _event(event_type: str, channel: str, priority: str, requires_ack: bool, reason: str) -> dict[str, Any]:
    return {"type": event_type, "channel": channel, "priority": priority, "requires_ack": requires_ack, "reason": reason, "authority": "CLASIFICACION_NO_MODIFICA_DECISION"}
