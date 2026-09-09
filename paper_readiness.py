"""Estado consolidado para una sesión PAPER supervisada."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def evaluate_paper_readiness(
    *,
    preflight: Mapping[str, Any] | None,
    process: Mapping[str, Any] | None,
    operational: Mapping[str, Any] | None,
    pending_alert_count: int,
) -> dict[str, Any]:
    """Resume preparación sin autorizar operaciones reales ni ejecutar órdenes."""
    blockers: list[str] = []
    warnings: list[str] = []
    checks = preflight.get("checks", []) if preflight else []
    for check in checks:
        if check.get("status") == "ERROR":
            blockers.append(str(check.get("detail") or check.get("name")))
        elif check.get("status") == "OMITIDO":
            warnings.append(str(check.get("detail") or check.get("name")))
    preflight_status = str(preflight.get("status", "NO_DISPONIBLE")) if preflight else "NO_DISPONIBLE"
    process_active = bool((process or {}).get("active"))
    operational_status = str((operational or {}).get("status", "NO_INICIADO"))
    if not preflight:
        blockers.append("No existe un preflight local registrado.")
    elif preflight_status == "BLOQUEADO" and not blockers:
        blockers.append("El preflight local está bloqueado.")
    if blockers:
        status = "BLOQUEADO_CONFIG"
    elif not process_active:
        status = "LISTO_INICIAR"
    elif operational_status in {"LISTO", "LISTO_EN_ESPERA"}:
        status = "LISTO_PAPER"
    elif operational_status in {"INICIANDO", "NO_INICIADO"}:
        status = "INICIANDO"
    else:
        status = "DEGRADADO"
    next_actions = _next_actions(status, blockers, warnings)
    return {
        "status": status, "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "preflight_status": preflight_status, "process_active": process_active,
        "operational_status": operational_status,
        "pending_alert_count": max(0, int(pending_alert_count)),
        "blockers": blockers, "warnings": warnings, "next_actions": next_actions,
        "paper_only": True, "real_trading_authorized": False,
        "authority": "READINESS_NO_EJECUTA_ORDENES",
    }


def _next_actions(status: str, blockers: list[str], warnings: list[str]) -> list[str]:
    if status == "BLOQUEADO_CONFIG":
        actions = ["Resolver los errores del preflight y ejecutarlo nuevamente."]
        if any("ALPACA_API" in item for item in blockers):
            actions.insert(0, "Configurar ALPACA_API_KEY y ALPACA_API_SECRET en el entorno local.")
        return actions
    if status == "LISTO_INICIAR":
        return ["Iniciar el scanner en PAPER y confirmar el preflight remoto."]
    if status == "INICIANDO":
        return ["Esperar conexión, primera vela y reconciliación por símbolo."]
    if status == "DEGRADADO":
        return ["Revisar heartbeat, reconciliaciones y último error antes de atender setups."]
    actions = ["Mantener supervisión humana y registrar el resultado de cada criterio."]
    if warnings:
        actions.append("Revisar funciones omitidas antes de necesitarlas en la sesión.")
    return actions
