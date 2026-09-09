"""Genera el estado beta actual desde verificaciones reproducibles."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from live_preflight import recent_live_preflights
from market_store import DEFAULT_MARKET_DATABASE
from methodology_coverage import audit_methodology_coverage
from paper_session_evidence import build_paper_session_evidence
from release_health_check import health_payload, run_health_checks
from safety_invariants import audit_safety_invariants
from scanner_incident import ScannerIncidentRepository
from scanner_instance import read_instance_status
from version import APP_VERSION, METHODOLOGY_VERSION
from visual_evidence import VisualEvidenceRepository


def build_beta_status(
    *, release: Mapping[str, Any], preflight: Mapping[str, Any] | None,
    process: Mapping[str, Any],
    methodology: Mapping[str, Any] | None = None,
    safety: Mapping[str, Any] | None = None,
    paper_evidence: Mapping[str, Any] | None = None,
    visual_evidence: Mapping[str, Any] | None = None,
    open_processing_incident_count: int = 0,
) -> dict[str, Any]:
    if open_processing_incident_count < 0:
        raise ValueError("El conteo de incidentes no puede ser negativo.")
    blockers: list[str] = []
    if release.get("status") != "OK":
        blockers.append("El health check de release tiene fallos.")
    methodology_ready = methodology is None or methodology.get("status") == "OK"
    if not methodology_ready:
        blockers.append("La cobertura metodologica tiene inconsistencias.")
    safety_ready = safety is None or safety.get("status") == "OK"
    if not safety_ready:
        blockers.append("Las invariantes PAPER o de aprendizaje tienen hallazgos.")
    if not preflight:
        blockers.append("No existe preflight local.")
    elif preflight.get("status") == "BLOQUEADO":
        blockers.extend(
            str(item.get("detail")) for item in preflight.get("checks", [])
            if item.get("status") == "ERROR"
        )
    environment_ready = bool(preflight and preflight.get("status") in {"LISTO_LOCAL", "LISTO"})
    if open_processing_incident_count:
        blockers.append(
            f"Hay {open_processing_incident_count} incidente(s) de procesamiento abierto(s)."
        )
    code_ready = (
        release.get("status") == "OK"
        and methodology_ready
        and safety_ready
    )
    real_market_validated = bool(
        paper_evidence and paper_evidence.get("status") == "APROBADO"
    )
    if not code_ready:
        status = "BLOQUEADO_CODIGO"
    elif not environment_ready:
        status = "CODIGO_LISTO_ENTORNO_BLOQUEADO"
    elif open_processing_incident_count:
        status = "RECUPERACION_PAPER_REQUERIDA"
    elif process.get("active"):
        status = "SESION_PAPER_EN_CURSO"
    elif real_market_validated:
        status = "BETA_PAPER_VALIDADA"
    else:
        status = "LISTO_PARA_SESION_PAPER"
    checks = release.get("checks", [])
    unit_test = next((item for item in checks if item.get("name") == "unit_tests"), {})
    return {
        "status": status, "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_version": APP_VERSION, "methodology_version": METHODOLOGY_VERSION,
        "code_health": release.get("status", "NO_DISPONIBLE"),
        "release_check_count": int(release.get("check_count", 0)),
        "release_failed_count": int(release.get("failed_count", 0)),
        "unit_tests_status": unit_test.get("status", "NO_DISPONIBLE"),
        "preflight_status": preflight.get("status", "NO_DISPONIBLE") if preflight else "NO_DISPONIBLE",
        "network_status": preflight.get("network_status", "NO_DISPONIBLE") if preflight else "NO_DISPONIBLE",
        "scanner_process_status": process.get("status", "DETENIDO"),
        "blockers": blockers,
        "methodology_coverage_status": (
            methodology.get("status", "NO_DISPONIBLE")
            if methodology
            else "NO_DISPONIBLE"
        ),
        "methodology_detector_count": int(
            methodology.get("detector_count", 0) if methodology else 0
        ),
        "methodology_partial_detector_count": int(
            methodology.get("partial_detector_count", 0) if methodology else 0
        ),
        "methodology_limitations_remain": (
            not bool(methodology.get("methodology_complete", False))
            if methodology
            else True
        ),
        "safety_invariants_status": (
            safety.get("status", "NO_DISPONIBLE")
            if safety
            else "NO_DISPONIBLE"
        ),
        "paper_only_verified": bool(
            safety
            and safety.get("status") == "OK"
            and safety.get("paper_only") is True
            and safety.get("order_execution") is False
        ),
        "learning_isolated": bool(
            safety
            and safety.get("status") == "OK"
            and safety.get("learning_isolated") is True
        ),
        "open_processing_incident_count": open_processing_incident_count,
        "real_market_validation_status": (
            paper_evidence.get("status", "NO_DISPONIBLE")
            if paper_evidence
            else "NO_DISPONIBLE"
        ),
        "real_market_validated": real_market_validated,
        "live_signal_path_status": (
            "LISTO"
            if code_ready
            and environment_ready
            and not open_processing_incident_count
            and real_market_validated
            else "NO_VALIDADO"
        ),
        "live_signal_waits_for_visual_evidence": False,
        "visual_evidence_role": "AUDITORIA_POST_ALERTA_OPCIONAL",
        "visual_evidence_required_for_live_signal": False,
        "visual_evidence_status": (
            visual_evidence.get("status", "NO_DISPONIBLE")
            if visual_evidence
            else "NO_DISPONIBLE"
        ),
        "visual_evidence_count": int(
            visual_evidence.get("evidence_count", 0)
            if visual_evidence
            else 0
        ),
        "visual_complete_alert_count": int(
            visual_evidence.get("complete_alert_count", 0)
            if visual_evidence
            else 0
        ),
        "visual_evidence_validated": bool(
            visual_evidence and visual_evidence.get("status") == "APROBADO"
        ),
        "real_trading_authorized": False,
        "next_actions": _next_actions(status),
        "validation_next_actions": _validation_next_actions(
            methodology=methodology,
            paper_evidence=paper_evidence,
        ),
        "post_alert_audit_actions": _post_alert_audit_actions(visual_evidence),
    }


def _next_actions(status: str) -> list[str]:
    if status == "BLOQUEADO_CODIGO":
        return ["Corregir los checks fallidos antes de iniciar una sesión."]
    if status == "CODIGO_LISTO_ENTORNO_BLOQUEADO":
        return ["Configurar credenciales locales y repetir el preflight seguro."]
    if status == "LISTO_PARA_SESION_PAPER":
        return ["Iniciar una sesión PAPER supervisada durante mercado abierto."]
    if status == "BETA_PAPER_VALIDADA":
        return [
            "Mantener el scanner PAPER activo durante mercado abierto y "
            "registrar feedback posterior de las alertas."
        ]
    if status == "RECUPERACION_PAPER_REQUERIDA":
        return [
            "Revisar los incidentes y demostrar recuperacion con una vela "
            "posterior procesada correctamente."
        ]
    return ["Supervisar integridad por símbolo y registrar feedback de cada alerta."]


def _validation_next_actions(
    *,
    methodology: Mapping[str, Any] | None,
    paper_evidence: Mapping[str, Any] | None,
) -> list[str]:
    actions = []
    if not paper_evidence or paper_evidence.get("status") != "APROBADO":
        actions.append(
            "Completar una sesion PAPER con evidencia Alpaca APROBADA."
        )
    if not methodology or not methodology.get("methodology_complete", False):
        actions.append(
            "Resolver con Joan los limites abiertos de la metodologia."
        )
    return actions


def _post_alert_audit_actions(
    visual_evidence: Mapping[str, Any] | None,
) -> list[str]:
    if visual_evidence and visual_evidence.get("status") == "APROBADO":
        return []
    return [
        "Opcional: conservar despues de la alerta un caso TC2000 con "
        "capturas 15m, 1H y 1D para auditoria; nunca retrasa la señal en vivo."
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=str(DEFAULT_MARKET_DATABASE))
    parser.add_argument("--lock-file", default="exports/live_scanner.lock")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    release = health_payload(run_health_checks())
    history = recent_live_preflights(args.database, limit=1)
    preflight = history[0]["payload"] if history else None
    process = read_instance_status(args.lock_file)
    safety = audit_safety_invariants()
    evidence = build_paper_session_evidence(
        args.database,
        lock_file=args.lock_file,
    )
    incident_count = ScannerIncidentRepository(
        args.database
    ).unresolved_count()
    visual = VisualEvidenceRepository(
        args.database
    ).overall_audit()
    payload = build_beta_status(
        release=release, preflight=preflight,
        process=process,
        methodology=audit_methodology_coverage(),
        safety=safety,
        paper_evidence=evidence,
        visual_evidence=visual,
        open_processing_incident_count=incident_count,
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload["code_health"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
