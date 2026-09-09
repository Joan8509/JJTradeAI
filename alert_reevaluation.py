"""Reevaluación derivada de una alerta y una revisión humana específicas."""

from dataclasses import asdict
from enum import Enum
from typing import Any, Mapping

from analysis_models import CriterionEvaluation, DirectionBias, EvaluationStatus, GateStatus, StrategyEvaluation
from decision_engine import build_decision


def reevaluate_alert(
    report: Mapping[str, Any],
    review: Mapping[str, Any],
    contract_selection: Mapping[str, Any] | None = None,
    governance_review: Mapping[str, Any] | None = None,
    visual_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    strategies = tuple(_strategy(item) for item in report.get("strategies", {}).get("evaluations", ()))
    invalidations = tuple(_criterion(item) for item in report.get("invalidations", ()))
    invalidations = tuple(_reviewed_invalidation(item, review, report) for item in invalidations)
    panorama = report.get("panorama", {})
    reviews = (review.get("path_clear"), review.get("news_clear"), review.get("panorama_approved"))
    if any(value is False for value in reviews):
        panorama_status = GateStatus.RECHAZADO
    elif all(value is True for value in reviews) and not panorama.get("conflicts"):
        panorama_status = GateStatus.APROBADO
    else:
        panorama_status = GateStatus.REQUIERE_REVISION
    visual_evidence = _visual_evidence_snapshot(
        visual_audit,
        human_review_created_at=review.get("created_at"),
    )
    if visual_evidence["status"] == "RECHAZADO":
        panorama_status = GateStatus.RECHAZADO
    elif (
        visual_evidence["status"] == "REQUIERE_REVISION"
        and panorama_status == GateStatus.APROBADO
    ):
        panorama_status = GateStatus.REQUIERE_REVISION
    original = report.get("decision", {})
    risk_status = GateStatus(original.get("risk_status", "NO_DISPONIBLE"))
    selected_contract = None
    if contract_selection is not None:
        candidate = contract_selection.get("candidate", {})
        if candidate.get("eligible") is True and candidate.get("risk_status") == "APROBADO":
            risk_status = GateStatus.APROBADO
            selected_contract = candidate.get("symbol")
    governance_status = GateStatus(original.get("governance_status", "NO_DISPONIBLE"))
    if governance_review is not None:
        governance_status = GateStatus(str(governance_review.get("status", "NO_DISPONIBLE")))
    decision = build_decision(
        strategies,
        invalidations=invalidations,
        data_quality_status=GateStatus(original.get("data_quality_status", "NO_DISPONIBLE")),
        panorama_status=panorama_status,
        risk_status=risk_status,
        governance_status=governance_status,
    )
    return {
        "decision": _jsonable(asdict(decision)),
        "review_id": review["id"],
        "source_data_as_of": report.get("data_as_of"),
        "panorama_status": panorama_status.value,
        "contract_selection_id": contract_selection.get("id") if contract_selection else None,
        "governance_review_id": governance_review.get("id") if governance_review else None,
        "selected_contract": selected_contract,
        "visual_evidence": visual_evidence,
        "disclaimer": "Reevaluación asistida; no ejecuta órdenes.",
    }


def _strategy(item: Mapping[str, Any]) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy_id=str(item["strategy_id"]), name=str(item["name"]),
        bias=DirectionBias(item["bias"]), detected=bool(item["detected"]),
        criteria=tuple(_criterion(value) for value in item.get("criteria", ())),
        timeframe=str(item.get("timeframe", "")),
    )


def _criterion(item: Mapping[str, Any]) -> CriterionEvaluation:
    return CriterionEvaluation(
        criterion_id=str(item["criterion_id"]), name=str(item["name"]),
        status=EvaluationStatus(item["status"]), required=bool(item["required"]),
        detail=str(item["detail"]), source=str(item["source"]),
    )


def _reviewed_invalidation(item: CriterionEvaluation, review: Mapping[str, Any], report: Mapping[str, Any]) -> CriterionEvaluation:
    status = item.status
    if item.criterion_id == "relevant_news" and review.get("news_clear") is not None:
        status = EvaluationStatus.NO_CUMPLE if review["news_clear"] else EvaluationStatus.CUMPLE
    if item.criterion_id == "stale_data":
        fresh = report.get("live_data_freshness", {}).get("status") == "APROBADO"
        status = EvaluationStatus.NO_CUMPLE if fresh else EvaluationStatus.CUMPLE
    return CriterionEvaluation(item.criterion_id, item.name, status, item.required, item.detail, item.source)


def _visual_evidence_snapshot(
    audit: Mapping[str, Any] | None,
    *,
    human_review_created_at: Any = None,
) -> dict[str, Any]:
    if not isinstance(audit, Mapping) or int(audit.get("evidence_count", 0) or 0) == 0:
        return {
            "status": "OMITIDO",
            "audit_status": "SIN_EVIDENCIA",
            "evidence_ids": [],
            "items": [],
            "authority": "EVIDENCIA_VISUAL_OPCIONAL_NO_MODIFICA_REGLAS",
        }
    items = []
    for raw in audit.get("items", ()):
        if not isinstance(raw, Mapping):
            continue
        items.append(
            {
                "evidence_id": int(raw.get("evidence_id", 0) or 0),
                "timeframe": str(raw.get("timeframe", "")),
                "content_hash": str(raw.get("content_hash", "")),
                "integrity_status": str(raw.get("integrity_status", "ERROR")),
                "review_status": str(
                    raw.get("latest_review_status", "PENDIENTE")
                ),
                "evidence_created_at": raw.get("created_at"),
                "reviewed_at": raw.get("latest_review_at"),
            }
        )
    audit_status = str(audit.get("status", "BLOQUEADO_ARCHIVOS"))
    review_statuses = {item["review_status"] for item in items}
    human_review_covers_visual = _human_review_covers_visual(
        human_review_created_at,
        items,
    )
    if (
        audit_status != "INTEGRO"
        or "DIFIERE" in review_statuses
        or any(item["integrity_status"] != "OK" for item in items)
    ):
        status = "RECHAZADO"
    elif (
        not items
        or review_statuses.intersection({"PENDIENTE", "NO_EVALUABLE"})
        or any(item["review_status"] != "COINCIDE" for item in items)
        or not human_review_covers_visual
    ):
        status = "REQUIERE_REVISION"
    else:
        status = "APROBADO"
    return {
        "status": status,
        "audit_status": audit_status,
        "generated_at": audit.get("generated_at"),
        "evidence_ids": [item["evidence_id"] for item in items],
        "items": items,
        "human_review_created_at": human_review_created_at,
        "human_review_covers_visual_evidence": human_review_covers_visual,
        "authority": "REVISION_VISUAL_CONSERVADORA_NO_MODIFICA_REGLAS",
    }


def _human_review_covers_visual(
    human_review_created_at: Any,
    items: list[dict[str, Any]],
) -> bool:
    human_at = _parse_timestamp(human_review_created_at)
    if human_at is None:
        return False
    visual_times = []
    for item in items:
        for field in ("evidence_created_at", "reviewed_at"):
            parsed = _parse_timestamp(item.get(field))
            if parsed is not None:
                visual_times.append(parsed)
    return bool(visual_times) and human_at >= max(visual_times)


def _parse_timestamp(value: Any):
    if not value:
        return None
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
