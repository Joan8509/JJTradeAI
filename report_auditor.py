"""Auditoría de reportes JJTrade AI.

Este módulo revisa reportes JSON ya generados y resume si el caso está listo
para revisión humana, si tiene evidencia suficiente para aprendizaje PAPER o si
faltan compuertas críticas. No modifica decisiones ni emite señales nuevas.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import json
import sys
from typing import Any

from version import APP_VERSION, METHODOLOGY_VERSION


PASSING_STATUSES = {"APROBADO", "CUMPLE", "NO_CUMPLE"}
OPEN_STATUSES = {"NO_DISPONIBLE", "REQUIERE_REVISION"}
REJECTING_STATUSES = {"RECHAZADO", "ERROR"}
CRITERION_STATUSES = {"CUMPLE", "NO_CUMPLE", "NO_DISPONIBLE", "REQUIERE_REVISION"}
GATE_STATUSES = {"APROBADO", "RECHAZADO", "NO_DISPONIBLE", "REQUIERE_REVISION", "ERROR"}
FINAL_DECISIONS = {"CALL", "PUT", "NO_OPERAR"}
STRATEGY_BIASES = {"CALL", "PUT", "NEUTRAL"}
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


@dataclass(frozen=True)
class ReportAudit:
    """Resumen auditable de la calidad de un reporte."""

    symbol: str
    data_as_of: str
    decision: str
    data_quality_status: str
    panorama_status: str
    risk_status: str
    governance_status: str
    readiness: str
    learning_ready: bool
    missing_evidence: tuple[str, ...]
    blockers: tuple[str, ...]
    detected_strategies: tuple[str, ...]
    first_missing_evidence: str = ""
    first_blocker: str = ""
    tentative_bias: str = ""
    tentative_strategies: str = ""
    app_version: str = ""
    methodology_version: str = ""
    package_id: str = ""
    package_session: str = ""
    package_timeframes: str = ""
    data_provider: str = ""
    data_source_timeframes: str = ""
    data_source_files: str = ""
    missing_gate_count: int = 0
    missing_strategy_count: int = 0
    missing_invalidation_count: int = 0
    blocker_gate_count: int = 0
    blocker_invalidation_count: int = 0
    blocker_detector_count: int = 0
    evaluated_count: int = 0
    detected_count: int = 0
    confirmed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    report_path: str = ""


AUDIT_FIELDS = tuple(ReportAudit.__dataclass_fields__)


@dataclass(frozen=True)
class ReviewQueueItem:
    """Accion puntual derivada de una auditoria para revision humana."""

    priority: str
    symbol: str
    data_as_of: str
    package_id: str
    readiness: str
    decision: str
    review_type: str
    source: str
    evidence: str
    tentative_bias: str = ""
    detected_strategies: str = ""
    report_path: str = ""


REVIEW_QUEUE_FIELDS = tuple(ReviewQueueItem.__dataclass_fields__)


def _status_value(value: Any) -> str:
    """Normaliza estados serializados como Enum o texto."""
    return str(getattr(value, "value", value))


def _require_status(value: Any, allowed: set[str], context: str) -> str:
    """Rechaza estados desconocidos para no ocultar reportes mal formados."""
    status = _status_value(value)
    if status not in allowed:
        raise ValueError(f"Estado no reconocido en {context}: {status}")
    return status


def _require_nonempty_text(value: Any, context: str) -> str:
    """Exige texto identificable en campos esenciales del reporte."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} debe ser texto no vacío.")
    return value


def _require_iso_datetime(value: Any, context: str) -> str:
    """Exige fecha o fecha-hora ISO sin imponer una zona horaria."""
    text = _require_nonempty_text(value, context)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{context} debe usar formato ISO.") from error
    return text


def _join_text_values(value: Any) -> str:
    """Normaliza campos exportados como lista o texto heredado."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "|".join(str(item) for item in value if item)
    return str(value)


def _mapping_section(report: dict[str, Any], key: str) -> dict[str, Any]:
    """Obtiene una sección objeto opcional o falla con un mensaje claro."""
    section = report.get(key, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"La sección {key} debe ser un objeto.")
    return section


def _optional_text_mapping(
    section: dict[str, Any], key: str, context: str
) -> dict[str, str]:
    """Valida mapas opcionales de identificador a explicación."""
    if key not in section:
        return {}
    value = section[key]
    if not isinstance(value, dict) or any(
        not isinstance(item_key, str)
        or not item_key.strip()
        or not isinstance(detail, str)
        or not detail.strip()
        for item_key, detail in value.items()
    ):
        raise ValueError(f"{context}.{key} debe mapear textos no vacíos.")
    return value


def _list_section(report: dict[str, Any], key: str) -> list[Any]:
    """Obtiene una sección lista opcional o falla con un mensaje claro."""
    section = report.get(key, [])
    if section is None:
        return []
    if not isinstance(section, list):
        raise ValueError(f"La sección {key} debe ser una lista.")
    return section


def _optional_text_list(section: dict[str, Any], key: str) -> tuple[str, ...] | None:
    """Valida una lista textual opcional sin romper reportes heredados."""
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"El campo decision.{key} debe ser una lista de textos.")
    return tuple(value)


def _timeframe_list(section: dict[str, Any], context: str) -> tuple[str, ...]:
    """Valida y normaliza una lista opcional de temporalidades."""
    if "timeframes" not in section:
        return ()
    value = section["timeframes"]
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{context}.timeframes debe ser una lista de textos.")
    normalized = tuple(item.strip().lower() for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{context}.timeframes contiene duplicados.")
    return tuple(value)


def _timeframe_files(section: dict[str, Any], context: str) -> dict[str, str]:
    """Valida el mapa opcional de temporalidad a archivo fuente."""
    if "files" not in section:
        return {}
    value = section["files"]
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(path, str)
        or not path.strip()
        for key, path in value.items()
    ):
        raise ValueError(f"{context}.files debe mapear textos no vacíos.")
    normalized_keys = tuple(key.strip().lower() for key in value)
    if len(set(normalized_keys)) != len(normalized_keys):
        raise ValueError(f"{context}.files contiene temporalidades duplicadas.")
    return value


def _validate_gate_summary_consistency(
    decision: dict[str, Any],
    sections: dict[str, dict[str, Any]],
) -> None:
    """Compara compuertas resumidas con sus secciones detalladas."""
    for gate, section in sections.items():
        decision_key = f"{gate}_status"
        if decision_key not in decision or "status" not in section:
            continue
        summarized = _require_status(
            decision[decision_key], GATE_STATUSES, f"compuerta {gate} en decision"
        )
        detailed = _require_status(
            section["status"], GATE_STATUSES, f"compuerta {gate} detallada"
        )
        if summarized != detailed:
            raise ValueError(
                f"decision.{decision_key}={summarized} no coincide con "
                f"{gate}.status={detailed}."
            )


def _validate_data_quality_details(section: dict[str, Any]) -> None:
    """Valida evidencia estructurada de calidad de datos cuando existe."""
    if "issues" in section:
        issues = section["issues"]
        if not isinstance(issues, list) or any(
            not isinstance(issue, str) or not issue.strip() for issue in issues
        ):
            raise ValueError(
                "data_quality.issues debe ser una lista de textos no vacíos."
            )
    if "candle_counts" in section:
        counts = section["candle_counts"]
        if not isinstance(counts, dict) or any(
            not isinstance(timeframe, str)
            or not timeframe.strip()
            or type(count) is not int
            or count < 0
            for timeframe, count in counts.items()
        ):
            raise ValueError(
                "data_quality.candle_counts debe mapear temporalidades a "
                "enteros no negativos."
            )
        normalized = tuple(timeframe.strip().lower() for timeframe in counts)
        if len(set(normalized)) != len(normalized):
            raise ValueError(
                "data_quality.candle_counts contiene temporalidades duplicadas."
            )


def _strategy_ids(report: dict[str, Any]) -> tuple[str, ...]:
    evaluations = _list_section(_mapping_section(report, "strategies"), "evaluations")
    detected = tuple(
        (item.get("strategy_id", ""), item.get("timeframe", ""))
        for item in evaluations
        if isinstance(item, dict)
        if item.get("detected") is True and item.get("strategy_id")
    )
    counts: dict[str, int] = {}
    for strategy_id, _ in detected:
        counts[strategy_id] = counts.get(strategy_id, 0) + 1
    return tuple(
        f"{strategy_id}@{timeframe}"
        if counts[strategy_id] > 1 and timeframe
        else strategy_id
        for strategy_id, timeframe in detected
    )


def _strategy_label(strategy: dict[str, Any]) -> str:
    """Identifica una evaluación sin cambiar su strategy_id metodológico."""
    strategy_id = str(strategy.get("strategy_id") or "")
    timeframe = str(strategy.get("timeframe") or "")
    return f"{strategy_id}@{timeframe}" if timeframe else strategy_id


def _validate_strategy_contract(report: dict[str, Any]) -> None:
    """Rechaza metadatos de estrategia ambiguos o mal tipados."""
    strategies = _mapping_section(report, "strategies")
    _optional_text_mapping(strategies, "skipped", "strategies")
    _optional_text_mapping(strategies, "errors", "strategies")
    evaluations = _list_section(strategies, "evaluations")
    seen_strategy_keys: set[tuple[str, str]] = set()
    strategy_timeframes: dict[str, list[str]] = {}
    for strategy in evaluations:
        if not isinstance(strategy, dict):
            raise ValueError("Cada evaluación de estrategia debe ser un objeto.")
        if "detected" in strategy and not isinstance(strategy["detected"], bool):
            raise ValueError("El campo detected de una estrategia debe ser booleano.")
        if "bias" in strategy:
            _require_status(
                strategy["bias"],
                STRATEGY_BIASES,
                f"sesgo de estrategia {strategy.get('strategy_id')}",
            )
        if "timeframe" in strategy and not isinstance(strategy["timeframe"], str):
            raise ValueError("El timeframe de una estrategia debe ser texto.")
        strategy_id = strategy.get("strategy_id")
        if isinstance(strategy_id, str) and strategy_id.strip():
            timeframe = strategy.get("timeframe", "")
            strategy_key = (strategy_id, timeframe)
            if strategy_key in seen_strategy_keys:
                raise ValueError(
                    "Evaluación de estrategia duplicada en el reporte: "
                    f"{strategy_id} ({timeframe or 'sin timeframe'})."
                )
            seen_strategy_keys.add(strategy_key)
            strategy_timeframes.setdefault(strategy_id, []).append(timeframe)
        if strategy.get("detected") is True:
            if not isinstance(strategy_id, str) or not strategy_id.strip():
                raise ValueError(
                    "Toda estrategia detectada debe tener un strategy_id válido."
                )
        if "criteria" not in strategy:
            continue
        criteria = strategy["criteria"]
        if not isinstance(criteria, list):
            raise ValueError("Los criterios de estrategia deben ser una lista.")
        seen_criterion_ids: set[str] = set()
        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise ValueError("Cada criterio de estrategia debe ser un objeto.")
            criterion_id = criterion.get("criterion_id")
            if "criterion_id" in criterion and (
                not isinstance(criterion_id, str) or not criterion_id.strip()
            ):
                raise ValueError("criterion_id debe ser texto no vacío.")
            if isinstance(criterion_id, str):
                if criterion_id in seen_criterion_ids:
                    raise ValueError(
                        "criterion_id duplicado en la estrategia "
                        f"{strategy.get('strategy_id')}: {criterion_id}."
                    )
                seen_criterion_ids.add(criterion_id)
            if "required" in criterion and not isinstance(
                criterion["required"], bool
            ):
                raise ValueError("El campo required de un criterio debe ser booleano.")
            if "status" in criterion:
                _require_status(
                    criterion["status"],
                    CRITERION_STATUSES,
                    f"criterio de estrategia {strategy.get('strategy_id')}",
                )
    for strategy_id, timeframes in strategy_timeframes.items():
        if len(timeframes) > 1 and any(not timeframe for timeframe in timeframes):
            raise ValueError(
                "Las evaluaciones repetidas de una estrategia deben declarar "
                f"timeframe: {strategy_id}."
            )


def _confirmed_directional_strategies(
    report: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Deriva identificadores y sesgos confirmados con el contrato del motor."""
    evaluations = _list_section(_mapping_section(report, "strategies"), "evaluations")
    confirmed: list[tuple[str, str]] = []
    for strategy in evaluations:
        if not isinstance(strategy, dict) or strategy.get("detected") is not True:
            continue
        criteria = strategy.get("criteria", [])
        if not isinstance(criteria, list):
            continue
        required = [
            criterion
            for criterion in criteria
            if isinstance(criterion, dict) and criterion.get("required") is True
        ]
        if not required or not all(
            _status_value(criterion.get("status")) == "CUMPLE"
            for criterion in required
        ):
            continue
        bias = _status_value(strategy.get("bias", "NEUTRAL"))
        if bias in {"CALL", "PUT"}:
            strategy_label = _strategy_label(strategy)
            if strategy_label:
                confirmed.append((strategy_label, bias))
    return tuple(confirmed)


def _detected_directional_strategies(
    report: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Deriva identificadores y sesgos direccionales detectados."""
    evaluations = _list_section(_mapping_section(report, "strategies"), "evaluations")
    detected: list[tuple[str, str]] = []
    for strategy in evaluations:
        if not isinstance(strategy, dict) or strategy.get("detected") is not True:
            continue
        strategy_id = strategy.get("strategy_id")
        bias = _status_value(strategy.get("bias", "NEUTRAL"))
        if (
            isinstance(strategy_id, str)
            and strategy_id.strip()
            and bias in {"CALL", "PUT"}
        ):
            detected.append((_strategy_label(strategy), bias))
    return tuple(detected)


def _collect_strategy_gaps(report: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    evaluations = _list_section(_mapping_section(report, "strategies"), "evaluations")
    for strategy in evaluations:
        if not isinstance(strategy, dict):
            raise ValueError("Cada evaluación de estrategia debe ser un objeto.")
        if strategy.get("detected") is not True:
            continue
        criteria = strategy.get("criteria", [])
        if criteria is None:
            criteria = []
        if not isinstance(criteria, list):
            raise ValueError("Los criterios de estrategia deben ser una lista.")
        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise ValueError("Cada criterio de estrategia debe ser un objeto.")
            if not criterion.get("required", False):
                continue
            status = _require_status(
                criterion.get("status"),
                CRITERION_STATUSES,
                f"criterio de estrategia {strategy.get('strategy_id')}",
            )
            if status in OPEN_STATUSES:
                gaps.append(
                    f"{_strategy_label(strategy)}: "
                    f"{criterion.get('name')} ({status})"
                )
    return gaps


def _strategy_summary(report: dict[str, Any]) -> dict[str, int]:
    """Obtiene o deriva el resumen de radar de estrategias."""
    def _summary_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    summary = report.get("strategy_summary")
    if isinstance(summary, dict):
        return {
            "evaluated": _summary_int(summary.get("evaluated", 0)),
            "detected": _summary_int(summary.get("detected", 0)),
            "confirmed": _summary_int(summary.get("confirmed", 0)),
            "skipped": _summary_int(summary.get("skipped", 0)),
            "errors": _summary_int(summary.get("errors", 0)),
        }
    if summary is not None:
        raise ValueError("La secciÃ³n strategy_summary debe ser un objeto.")
    return _derived_strategy_summary(report)


def _derived_strategy_summary(report: dict[str, Any]) -> dict[str, int]:
    """Calcula conteos exclusivamente desde la evidencia detallada."""
    strategies = _mapping_section(report, "strategies")
    evaluations = _list_section(strategies, "evaluations")
    confirmed = 0
    for item in evaluations:
        if not isinstance(item, dict) or item.get("detected") is not True:
            continue
        criteria = item.get("criteria", [])
        if criteria is None:
            criteria = []
        if not isinstance(criteria, list):
            raise ValueError("Los criterios de estrategia deben ser una lista.")
        required_criteria = [
            criterion
            for criterion in criteria
            if isinstance(criterion, dict) and criterion.get("required", False)
        ]
        if required_criteria and all(
            isinstance(criterion, dict)
            and _require_status(
                criterion.get("status"),
                CRITERION_STATUSES,
                f"criterio de estrategia {item.get('strategy_id')}",
            )
            == "CUMPLE"
            for criterion in required_criteria
        ):
            confirmed += 1
    return {
        "evaluated": len(evaluations),
        "detected": sum(
            isinstance(item, dict) and item.get("detected") is True
            for item in evaluations
        ),
        "confirmed": confirmed,
        "skipped": len(_mapping_section(strategies, "skipped")),
        "errors": len(_mapping_section(strategies, "errors")),
    }


def _validate_modern_strategy_summary(report: dict[str, Any]) -> None:
    """Exige que el resumen 1.0 coincida con la evidencia del radar."""
    if report.get("schema_version") != "1.0" or "strategy_summary" not in report:
        return
    summary = _mapping_section(report, "strategy_summary")
    fields = ("evaluated", "detected", "confirmed", "skipped", "errors")
    if any(
        type(summary.get(field)) is not int or summary[field] < 0
        for field in fields
    ):
        raise ValueError(
            "strategy_summary del esquema 1.0 requiere conteos enteros no negativos."
        )
    declared = {field: summary[field] for field in fields}
    derived = _derived_strategy_summary(report)
    if declared != derived:
        raise ValueError(
            "strategy_summary no coincide con strategies.evaluations, skipped y errors."
        )


def audit_report(report: dict[str, Any], *, report_path: str = "") -> ReportAudit:
    """Evalúa la completitud metodológica de un reporte exportado."""
    if not isinstance(report, dict):
        raise ValueError("El reporte JSON debe ser un objeto.")
    symbol = _require_nonempty_text(report.get("symbol"), "symbol").strip().upper()
    data_as_of = _require_iso_datetime(report.get("data_as_of"), "data_as_of")
    if "schema_version" in report:
        schema_version = _require_nonempty_text(
            report["schema_version"], "schema_version"
        )
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"schema_version no soportada: {schema_version}.")
    for version_key in ("app_version", "methodology_version"):
        if version_key in report and not (
            version_key == "app_version" and report[version_key] is None
        ):
            _require_nonempty_text(report[version_key], version_key)
    missing: list[str] = []
    blockers: list[str] = []
    missing_gate_count = 0
    missing_invalidation_count = 0
    blocker_gate_count = 0
    blocker_invalidation_count = 0
    blocker_detector_count = 0

    decision = _mapping_section(report, "decision")
    _validate_strategy_contract(report)
    data_quality_section = _mapping_section(report, "data_quality")
    _validate_data_quality_details(data_quality_section)
    panorama_section = _mapping_section(report, "panorama")
    risk_section = _mapping_section(report, "risk")
    governance_section = _mapping_section(report, "governance")
    _validate_gate_summary_consistency(
        decision,
        {
            "data_quality": data_quality_section,
            "panorama": panorama_section,
            "risk": risk_section,
            "governance": governance_section,
        },
    )
    data_quality = decision.get(
        "data_quality_status",
        data_quality_section.get("status", "NO_DISPONIBLE"),
    )
    panorama = decision.get(
        "panorama_status",
        panorama_section.get("status", "NO_DISPONIBLE"),
    )
    risk = decision.get(
        "risk_status",
        risk_section.get("status", "NO_DISPONIBLE"),
    )
    governance = decision.get(
        "governance_status",
        governance_section.get("status", "NO_DISPONIBLE"),
    )
    final_decision = _require_status(
        decision.get("decision", "NO_OPERAR"),
        FINAL_DECISIONS,
        "decision final",
    )
    if "confidence" in decision:
        confidence = _require_nonempty_text(
            decision["confidence"], "decision.confidence"
        )
        if confidence != "NO_CALIBRADA":
            raise ValueError(
                "decision.confidence debe permanecer NO_CALIBRADA."
            )
    if "reasons" in decision:
        reasons = decision["reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason.strip() for reason in reasons
        ):
            raise ValueError(
                "decision.reasons debe ser una lista de textos no vacíos."
            )

    gate_statuses = {
        "calidad_datos": data_quality,
        "panorama": panorama,
        "riesgo": risk,
        "gobierno_operativo": governance,
    }
    normalized_gate_statuses: dict[str, str] = {}
    for gate, status in gate_statuses.items():
        status = _require_status(status, GATE_STATUSES, f"compuerta {gate}")
        normalized_gate_statuses[gate] = status
        if status in OPEN_STATUSES:
            missing.append(f"{gate}: {status}")
            missing_gate_count += 1
        elif status in REJECTING_STATUSES:
            blockers.append(f"{gate}: {status}")
            blocker_gate_count += 1
            if gate == "calidad_datos":
                issues = data_quality_section.get("issues", ())
                if isinstance(issues, (list, tuple)):
                    blockers.extend(
                        f"calidad_datos_issue: {issue}"
                        for issue in issues
                        if issue
                    )

    detailed_active_invalidations: list[str] = []
    detailed_pending_invalidations: list[str] = []
    seen_invalidation_ids: set[str] = set()
    for item in _list_section(report, "invalidations"):
        if not isinstance(item, dict):
            raise ValueError("Cada invalidación debe ser un objeto.")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Toda invalidación debe tener un nombre válido.")
        if "required" in item and not isinstance(item["required"], bool):
            raise ValueError(
                "El campo required de una invalidación debe ser booleano."
            )
        criterion_id = item.get("criterion_id")
        if "criterion_id" in item and (
            not isinstance(criterion_id, str) or not criterion_id.strip()
        ):
            raise ValueError(
                "criterion_id de invalidación debe ser texto no vacío."
            )
        if isinstance(criterion_id, str):
            if criterion_id in seen_invalidation_ids:
                raise ValueError(
                    f"criterion_id de invalidación duplicado: {criterion_id}."
                )
            seen_invalidation_ids.add(criterion_id)
        status = _require_status(
            item.get("status"),
            CRITERION_STATUSES,
            f"invalidación {name}",
        )
        if status == "CUMPLE":
            blockers.append(f"invalidacion_activa: {name}")
            detailed_active_invalidations.append(name)
            blocker_invalidation_count += 1
        elif status in OPEN_STATUSES:
            missing.append(f"invalidacion_pendiente: {name}")
            detailed_pending_invalidations.append(name)
            missing_invalidation_count += 1

    declared_pending_invalidations = _optional_text_list(
        decision, "pending_invalidations"
    )
    declared_active_invalidations = _optional_text_list(
        decision, "active_invalidations"
    )
    if (
        declared_active_invalidations is not None
        and declared_active_invalidations != tuple(detailed_active_invalidations)
    ):
        raise ValueError(
            "decision.active_invalidations no coincide con la evidencia "
            "detallada de invalidaciones."
        )
    if (
        declared_pending_invalidations is not None
        and declared_pending_invalidations != tuple(detailed_pending_invalidations)
    ):
        raise ValueError(
            "decision.pending_invalidations no coincide con la evidencia "
            "detallada de invalidaciones."
        )

    if final_decision in {"CALL", "PUT"}:
        nonapproved_gates = tuple(
            f"{gate}={status}"
            for gate, status in normalized_gate_statuses.items()
            if status != "APROBADO"
        )
        if nonapproved_gates:
            raise ValueError(
                f"La decisión {final_decision} contradice compuertas no aprobadas: "
                + ", ".join(nonapproved_gates)
                + "."
            )
        if blocker_invalidation_count or missing_invalidation_count:
            raise ValueError(
                f"La decisión {final_decision} contradice invalidaciones activas "
                "o pendientes."
            )
        if "reasons" in decision and not decision["reasons"]:
            raise ValueError(
                f"La decisión {final_decision} debe incluir razones explicativas."
            )

    strategy_errors = _mapping_section(_mapping_section(report, "strategies"), "errors")
    for detector, error in strategy_errors.items():
        blockers.append(f"detector_error: {detector}: {error}")
        blocker_detector_count += 1

    strategy_gaps = _collect_strategy_gaps(report)
    missing.extend(strategy_gaps)
    detected = _strategy_ids(report)
    confirmed_directional = _confirmed_directional_strategies(report)
    confirmed_directional_biases = {bias for _, bias in confirmed_directional}
    detected_directional = _detected_directional_strategies(report)
    detected_directional_biases = {bias for _, bias in detected_directional}
    declared_supporting_strategies = _optional_text_list(
        decision, "supporting_strategies"
    )
    expected_supporting_strategies = tuple(
        strategy_id for strategy_id, _ in confirmed_directional
    )
    if (
        declared_supporting_strategies is not None
        and declared_supporting_strategies != expected_supporting_strategies
    ):
        raise ValueError(
            "decision.supporting_strategies no coincide con las estrategias "
            "direccionales confirmadas."
        )
    expected_tentative_bias = (
        next(iter(detected_directional_biases))
        if not confirmed_directional
        and len(detected_directional_biases) == 1
        else None
    )
    expected_tentative_strategies = tuple(
        strategy_id
        for strategy_id, bias in detected_directional
        if bias == expected_tentative_bias
    )
    modern_tentative_summary = isinstance(
        decision.get("tentative_strategies"), list
    )
    if modern_tentative_summary:
        declared_tentative_bias = decision.get("tentative_bias") or None
        declared_tentative_strategies = _optional_text_list(
            decision, "tentative_strategies"
        )
        if declared_tentative_strategies is None:
            declared_tentative_strategies = ()
        if (
            declared_tentative_bias != expected_tentative_bias
            or declared_tentative_strategies != expected_tentative_strategies
        ):
            raise ValueError(
                "El resumen tentativo de decision no coincide con las "
                "estrategias direccionales detectadas."
            )
    if final_decision in {"CALL", "PUT"}:
        if confirmed_directional_biases != {final_decision}:
            evidence = ", ".join(sorted(confirmed_directional_biases)) or "ninguna"
            raise ValueError(
                f"La decisión {final_decision} no tiene respaldo direccional "
                f"confirmado y exclusivo; sesgos confirmados: {evidence}."
            )
    strategy_summary = _strategy_summary(report)
    _validate_modern_strategy_summary(report)
    validation_package = _mapping_section(report, "validation_package")
    package_symbol = validation_package.get("symbol")
    if package_symbol is not None:
        package_symbol = _require_nonempty_text(
            package_symbol, "validation_package.symbol"
        )
        if package_symbol.strip().upper() != symbol.strip().upper():
            raise ValueError(
                "validation_package.symbol no coincide con symbol del reporte."
            )
    package_session_value = validation_package.get("session")
    if package_session_value is not None:
        package_session_value = _require_iso_datetime(
            package_session_value, "validation_package.session"
        )
    package_id_value = validation_package.get("package_id")
    if package_id_value is not None:
        package_id_value = _require_nonempty_text(
            package_id_value, "validation_package.package_id"
        )
        if package_session_value is not None:
            expected_package_id = f"{symbol}_{package_session_value}"
            if package_id_value != expected_package_id:
                raise ValueError(
                    "validation_package.package_id no coincide con símbolo y sesión."
                )
    package_timeframes = _timeframe_list(
        validation_package, "validation_package"
    )
    data_source = _mapping_section(report, "data_source")
    data_source_timeframes = _timeframe_list(data_source, "data_source")
    if package_timeframes and data_source_timeframes:
        normalized_package = {item.strip().lower() for item in package_timeframes}
        normalized_source = {item.strip().lower() for item in data_source_timeframes}
        if normalized_package != normalized_source:
            raise ValueError(
                "validation_package.timeframes no coincide con "
                "data_source.timeframes."
            )
    package_files = _timeframe_files(validation_package, "validation_package")
    data_source_files = _timeframe_files(data_source, "data_source")
    for context, timeframes, files in (
        ("validation_package", package_timeframes, package_files),
        ("data_source", data_source_timeframes, data_source_files),
    ):
        if timeframes and files:
            normalized_timeframes = {item.strip().lower() for item in timeframes}
            normalized_files = {item.strip().lower() for item in files}
            if normalized_timeframes != normalized_files:
                raise ValueError(
                    f"{context}.files no coincide con {context}.timeframes."
                )
    candle_counts = data_quality_section.get("candle_counts", {})
    declared_timeframes = package_timeframes or data_source_timeframes
    if candle_counts and declared_timeframes:
        normalized_counts = {item.strip().lower() for item in candle_counts}
        normalized_declared = {
            item.strip().lower() for item in declared_timeframes
        }
        if normalized_counts != normalized_declared:
            raise ValueError(
                "data_quality.candle_counts no coincide con las temporalidades "
                "declaradas."
            )

    if blockers:
        readiness = "BLOQUEADO"
    elif missing:
        readiness = "INCOMPLETO"
    else:
        readiness = "LISTO_REVISION"

    learning_ready = (
        readiness == "LISTO_REVISION"
        and bool(detected)
        and final_decision in {"CALL", "PUT", "NO_OPERAR"}
    )

    return ReportAudit(
        symbol=symbol,
        data_as_of=data_as_of,
        decision=final_decision,
        data_quality_status=_status_value(data_quality),
        panorama_status=_status_value(panorama),
        risk_status=_status_value(risk),
        governance_status=_status_value(governance),
        readiness=readiness,
        learning_ready=learning_ready,
        missing_evidence=tuple(missing),
        blockers=tuple(blockers),
        detected_strategies=detected,
        first_missing_evidence=str(missing[0]) if missing else "",
        first_blocker=str(blockers[0]) if blockers else "",
        tentative_bias=str(decision.get("tentative_bias") or ""),
        tentative_strategies=_join_text_values(
            decision.get("tentative_strategies", ())
        ),
        app_version=str(report.get("app_version") or ""),
        methodology_version=str(report.get("methodology_version") or ""),
        package_id=str(package_id_value or ""),
        package_session=str(validation_package.get("session") or ""),
        package_timeframes="|".join(str(item) for item in package_timeframes),
        data_provider=str(data_source.get("provider") or ""),
        data_source_timeframes="|".join(str(item) for item in data_source_timeframes),
        data_source_files="|".join(
            f"{timeframe}:{path}"
            for timeframe, path in sorted(data_source_files.items())
        ),
        missing_gate_count=missing_gate_count,
        missing_strategy_count=len(strategy_gaps),
        missing_invalidation_count=missing_invalidation_count,
        blocker_gate_count=blocker_gate_count,
        blocker_invalidation_count=blocker_invalidation_count,
        blocker_detector_count=blocker_detector_count,
        evaluated_count=strategy_summary["evaluated"],
        detected_count=strategy_summary["detected"],
        confirmed_count=strategy_summary["confirmed"],
        skipped_count=strategy_summary["skipped"],
        error_count=strategy_summary["errors"],
        report_path=report_path,
    )


def load_report(path: str | Path) -> dict[str, Any]:
    """Lee un reporte JSON exportado."""
    report_path = Path(path)
    if not report_path.is_file():
        raise ValueError(f"El reporte no existe: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"El reporte JSON no es válido: {report_path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"El reporte JSON debe ser un objeto: {report_path}")
    return payload


def audit_report_file(path: str | Path) -> ReportAudit:
    """Audita un archivo JSON de reporte."""
    report_path = Path(path)
    return audit_report(load_report(report_path), report_path=str(report_path))


def audit_report_directory(
    path: str | Path, *, skip_invalid: bool = False
) -> tuple[ReportAudit, ...]:
    """Audita todos los reportes JSON de una carpeta."""
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"La carpeta de reportes no existe: {root}")
    audits: list[ReportAudit] = []
    for item in sorted(root.glob("*.json")):
        try:
            audits.append(audit_report_file(item))
        except ValueError as error:
            if not skip_invalid:
                raise
            print(f"Reporte omitido: {error}", file=sys.stderr)
    return tuple(audits)


def write_audit_csv(audits: tuple[ReportAudit, ...], output_path: str | Path) -> None:
    """Guarda un resumen CSV de auditoría."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            **asdict(audit),
            "learning_ready": "SI" if audit.learning_ready else "NO",
            "missing_evidence": " | ".join(audit.missing_evidence),
            "blockers": " | ".join(audit.blockers),
            "detected_strategies": " | ".join(audit.detected_strategies),
        }
        for audit in audits
    ]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _review_item_source(evidence: str) -> str:
    """Extrae una fuente breve desde el texto auditable."""
    if ":" in evidence:
        return evidence.split(":", 1)[0].strip()
    return evidence.strip()


def _review_item_type(evidence: str, *, is_blocker: bool) -> str:
    """Clasifica una accion de revision sin cambiar la decision."""
    if evidence.startswith("calidad_datos"):
        return "CALIDAD_DATOS"
    if evidence.startswith("invalidacion_"):
        return "INVALIDACION"
    if evidence.startswith("detector_error"):
        return "DETECTOR"
    if evidence.startswith(("panorama:", "riesgo:", "gobierno_operativo:")):
        return "COMPUERTA"
    if ":" in evidence:
        return "ESTRATEGIA"
    return "BLOQUEO" if is_blocker else "EVIDENCIA"


def build_review_queue(audits: tuple[ReportAudit, ...]) -> tuple[ReviewQueueItem, ...]:
    """Expande faltantes y bloqueos en una cola CSV filtrable."""
    items: list[ReviewQueueItem] = []
    for audit in audits:
        common = {
            "symbol": audit.symbol,
            "data_as_of": audit.data_as_of,
            "package_id": audit.package_id,
            "readiness": audit.readiness,
            "decision": audit.decision,
            "tentative_bias": audit.tentative_bias,
            "detected_strategies": " | ".join(audit.detected_strategies),
            "report_path": audit.report_path,
        }
        for blocker in audit.blockers:
            items.append(
                ReviewQueueItem(
                    priority="1_BLOQUEO",
                    review_type=_review_item_type(blocker, is_blocker=True),
                    source=_review_item_source(blocker),
                    evidence=blocker,
                    **common,
                )
            )
        for missing in audit.missing_evidence:
            items.append(
                ReviewQueueItem(
                    priority="2_FALTANTE",
                    review_type=_review_item_type(missing, is_blocker=False),
                    source=_review_item_source(missing),
                    evidence=missing,
                    **common,
                )
            )
    return tuple(items)


def write_review_queue_csv(
    audits: tuple[ReportAudit, ...], output_path: str | Path
) -> None:
    """Guarda una fila por accion pendiente o bloqueo de auditoria."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(item) for item in build_review_queue(audits)]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    """Construye el parser CLI de auditoría."""
    parser = argparse.ArgumentParser(description="Audita reportes JSON JJTrade AI.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"JJTrade AI {APP_VERSION} / {METHODOLOGY_VERSION}",
    )
    parser.add_argument("--report", help="Ruta a un reporte JSON individual.")
    parser.add_argument("--reports-dir", help="Carpeta con reportes JSON.")
    parser.add_argument("--output-csv", help="Ruta CSV para guardar auditoría.")
    parser.add_argument(
        "--output-review-csv",
        help="Ruta CSV para guardar una cola de revision por faltante o bloqueo.",
    )
    parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="En modo carpeta, omite JSONs inválidos y audita los reportes válidos.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI para auditar reportes."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if bool(args.report) == bool(args.reports_dir):
        raise SystemExit("Use exactamente uno: --report o --reports-dir.")
    try:
        audits = (
            (audit_report_file(args.report),)
            if args.report
            else audit_report_directory(args.reports_dir, skip_invalid=args.skip_invalid)
        )
    except ValueError as error:
        parser.error(str(error))
    if args.output_csv:
        write_audit_csv(audits, args.output_csv)
    if args.output_review_csv:
        write_review_queue_csv(audits, args.output_review_csv)
    if not args.output_csv and not args.output_review_csv:
        for audit in audits:
            package_info = (
                f"package_id={audit.package_id}"
                f" package_session={audit.package_session}"
                f" package_timeframes={audit.package_timeframes} "
                if audit.package_id
                else ""
            )
            print(
                f"{audit.symbol} {audit.data_as_of} "
                f"{audit.readiness} decision={audit.decision} "
                f"learning_ready={'SI' if audit.learning_ready else 'NO'} "
                f"{package_info}"
                f"data_quality={audit.data_quality_status} "
                f"panorama={audit.panorama_status} "
                f"risk={audit.risk_status} "
                f"governance={audit.governance_status} "
                f"evaluated={audit.evaluated_count} "
                f"detected={audit.detected_count} "
                f"confirmed={audit.confirmed_count} "
                f"missing_gates={audit.missing_gate_count} "
                f"missing_strategies={audit.missing_strategy_count} "
                f"blockers={len(audit.blockers)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
