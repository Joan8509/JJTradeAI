"""Scanner multi-activo para comparar estrategias sin emitir decisiones."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from report_auditor import audit_report


SCAN_STATES = {"NO_DETECTADA", "CANDIDATA", "FALLIDA", "CONFIRMADA"}


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _strategy_state(evaluation: Mapping[str, Any]) -> str:
    if evaluation.get("detected") is not True:
        return "NO_DETECTADA"
    criteria = evaluation.get("criteria", [])
    required = [item for item in criteria if item.get("required") is True]
    statuses = [_status_value(item.get("status")) for item in required]
    if any(status == "NO_CUMPLE" for status in statuses):
        return "FALLIDA"
    if required and all(status == "CUMPLE" for status in statuses):
        return "CONFIRMADA"
    return "CANDIDATA"


def _compliance(required: list[Mapping[str, Any]]) -> float:
    evaluable = [
        item
        for item in required
        if _status_value(item.get("status")) in {"CUMPLE", "NO_CUMPLE"}
    ]
    if not evaluable:
        return 0.0
    fulfilled = sum(_status_value(item.get("status")) == "CUMPLE" for item in evaluable)
    return round(fulfilled / len(evaluable) * 100, 2)


def build_strategy_scan_rows(
    reports: Iterable[Mapping[str, Any]],
    *,
    detected_only: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Convierte reportes auditables en filas comparables por estrategia."""
    rows: list[dict[str, Any]] = []
    for raw_report in reports:
        report = dict(raw_report)
        audit = audit_report(report)
        strategies = report.get("strategies", {})
        evaluations = strategies.get("evaluations", [])
        for evaluation in evaluations:
            if detected_only and evaluation.get("detected") is not True:
                continue
            criteria = evaluation.get("criteria", [])
            required = [item for item in criteria if item.get("required") is True]
            pending = [
                item
                for item in required
                if _status_value(item.get("status"))
                in {"NO_DISPONIBLE", "REQUIERE_REVISION"}
            ]
            failed = [
                item
                for item in required
                if _status_value(item.get("status")) == "NO_CUMPLE"
            ]
            next_required = pending[0] if pending else failed[0] if failed else None
            state = _strategy_state(evaluation)
            if state not in SCAN_STATES:  # pragma: no cover - defensive contract
                raise ValueError(f"Estado de scanner no reconocido: {state}")
            rows.append(
                {
                    "symbol": report["symbol"],
                    "data_as_of": report["data_as_of"],
                    "strategy_id": evaluation.get("strategy_id", ""),
                    "strategy_name": evaluation.get("name", ""),
                    "timeframe": evaluation.get("timeframe", ""),
                    "bias": _status_value(evaluation.get("bias", "NEUTRAL")),
                    "state": state,
                    "compliance_percentage": _compliance(required),
                    "required_count": len(required),
                    "pending_count": len(pending),
                    "failed_count": len(failed),
                    "next_required": (
                        str(next_required.get("name", "")) if next_required else ""
                    ),
                    "final_decision": audit.decision,
                    "readiness": audit.readiness,
                }
            )
    return tuple(rows)
