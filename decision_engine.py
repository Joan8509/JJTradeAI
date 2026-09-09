"""Compuerta final conservadora para decisiones asistidas de JJTrade AI."""

from collections.abc import Iterable

from analysis_models import (
    CriterionEvaluation,
    DecisionAssessment,
    DirectionBias,
    EvaluationStatus,
    FinalDecision,
    GateStatus,
    StrategyEvaluation,
)


def _evaluation_label(evaluation: StrategyEvaluation) -> str:
    """Distingue evaluaciones multitemporales sin cambiar el ID metodológico."""
    return (
        f"{evaluation.strategy_id}@{evaluation.timeframe}"
        if evaluation.timeframe
        else evaluation.strategy_id
    )


def _validate_unique_evaluations(
    evaluations: tuple[StrategyEvaluation, ...],
) -> None:
    """Impide contar dos veces la misma evaluación y temporalidad."""
    seen: set[tuple[str, str]] = set()
    strategy_timeframes: dict[str, list[str]] = {}
    for evaluation in evaluations:
        if not isinstance(evaluation, StrategyEvaluation):
            raise TypeError("Cada evaluación debe ser StrategyEvaluation.")
        if not isinstance(evaluation.bias, DirectionBias):
            raise TypeError("El bias de una evaluación debe ser DirectionBias.")
        if type(evaluation.detected) is not bool:
            raise TypeError("detected debe ser booleano.")
        if (
            not isinstance(evaluation.strategy_id, str)
            or not evaluation.strategy_id.strip()
        ):
            raise ValueError("Toda evaluación debe tener un strategy_id válido.")
        if not isinstance(evaluation.name, str) or not evaluation.name.strip():
            raise ValueError("Toda evaluación debe tener un nombre válido.")
        if not isinstance(evaluation.timeframe, str):
            raise ValueError("El timeframe de una evaluación debe ser texto.")
        seen_criterion_ids: set[str] = set()
        for criterion in evaluation.criteria:
            if not isinstance(criterion, CriterionEvaluation):
                raise TypeError("Cada criterio debe ser CriterionEvaluation.")
            if (
                not isinstance(criterion.criterion_id, str)
                or not criterion.criterion_id.strip()
            ):
                raise ValueError("Todo criterio debe tener un criterion_id válido.")
            if not isinstance(criterion.name, str) or not criterion.name.strip():
                raise ValueError("Todo criterio debe tener un nombre válido.")
            if not isinstance(criterion.detail, str) or not criterion.detail.strip():
                raise ValueError("Todo criterio debe tener un detalle válido.")
            if not isinstance(criterion.source, str) or not criterion.source.strip():
                raise ValueError("Todo criterio debe tener una fuente válida.")
            if criterion.criterion_id in seen_criterion_ids:
                raise ValueError(
                    "criterion_id duplicado en "
                    f"{_evaluation_label(evaluation)}: {criterion.criterion_id}."
                )
            seen_criterion_ids.add(criterion.criterion_id)
            if not isinstance(criterion.status, EvaluationStatus):
                raise TypeError(
                    "El status de un criterio debe ser EvaluationStatus."
                )
            if type(criterion.required) is not bool:
                raise TypeError("required debe ser booleano.")
        key = (evaluation.strategy_id, evaluation.timeframe)
        if key in seen:
            raise ValueError(
                "Evaluación de estrategia duplicada: "
                f"{_evaluation_label(evaluation)}."
            )
        seen.add(key)
        strategy_timeframes.setdefault(evaluation.strategy_id, []).append(
            evaluation.timeframe
        )
    for strategy_id, timeframes in strategy_timeframes.items():
        if len(timeframes) > 1 and any(not timeframe for timeframe in timeframes):
            raise ValueError(
                "Las evaluaciones repetidas deben declarar timeframe: "
                f"{strategy_id}."
            )


def _validate_unique_invalidations(
    invalidations: tuple[CriterionEvaluation, ...],
) -> None:
    """Exige identidad legible y única para cada invalidación."""
    seen_ids: set[str] = set()
    for invalidation in invalidations:
        if not isinstance(invalidation, CriterionEvaluation):
            raise TypeError("Cada invalidación debe ser CriterionEvaluation.")
        if not isinstance(invalidation.status, EvaluationStatus):
            raise TypeError(
                "El status de una invalidación debe ser EvaluationStatus."
            )
        if type(invalidation.required) is not bool:
            raise TypeError("required de una invalidación debe ser booleano.")
        if (
            not isinstance(invalidation.criterion_id, str)
            or not invalidation.criterion_id.strip()
        ):
            raise ValueError("Toda invalidación debe tener un criterion_id válido.")
        if not isinstance(invalidation.name, str) or not invalidation.name.strip():
            raise ValueError("Toda invalidación debe tener un nombre válido.")
        if not isinstance(invalidation.detail, str) or not invalidation.detail.strip():
            raise ValueError("Toda invalidación debe tener un detalle válido.")
        if not isinstance(invalidation.source, str) or not invalidation.source.strip():
            raise ValueError("Toda invalidación debe tener una fuente válida.")
        if invalidation.criterion_id in seen_ids:
            raise ValueError(
                "Invalidación duplicada: " + invalidation.criterion_id + "."
            )
        seen_ids.add(invalidation.criterion_id)


def _validate_gate_statuses(gates: dict[str, GateStatus]) -> None:
    """Rechaza textos u otros valores que eludan el contrato de compuertas."""
    for name, status in gates.items():
        if not isinstance(status, GateStatus):
            raise TypeError(f"{name} debe ser GateStatus.")


def build_decision(
    evaluations: Iterable[StrategyEvaluation],
    *,
    invalidations: Iterable[CriterionEvaluation] = (),
    data_quality_status: GateStatus = GateStatus.APROBADO,
    panorama_status: GateStatus = GateStatus.NO_DISPONIBLE,
    risk_status: GateStatus = GateStatus.NO_DISPONIBLE,
    governance_status: GateStatus = GateStatus.NO_DISPONIBLE,
) -> DecisionAssessment:
    """Construye una decisión solo cuando todas las compuertas están aprobadas.

    La confianza permanece sin calibrar hasta disponer de suficientes
    operaciones históricas. Esta función no asigna probabilidades artificiales.
    """
    strategy_evaluations = tuple(evaluations)
    _validate_unique_evaluations(strategy_evaluations)
    invalidation_evaluations = tuple(invalidations)
    _validate_unique_invalidations(invalidation_evaluations)
    _validate_gate_statuses(
        {
            "data_quality_status": data_quality_status,
            "panorama_status": panorama_status,
            "risk_status": risk_status,
            "governance_status": governance_status,
        }
    )
    active_invalidations = tuple(
        item.name
        for item in invalidation_evaluations
        if item.status == EvaluationStatus.CUMPLE
    )
    pending_invalidations = tuple(
        item.name
        for item in invalidation_evaluations
        if item.status
        in {
            EvaluationStatus.NO_DISPONIBLE,
            EvaluationStatus.REQUIERE_REVISION,
        }
    )
    reasons: list[str] = []

    detected = tuple(item for item in strategy_evaluations if item.detected)
    confirmed = tuple(
        item for item in detected if item.required_criteria_satisfied
    )
    directional_detected = tuple(
        item for item in detected if item.bias != DirectionBias.NEUTRAL
    )
    directional_confirmed = tuple(
        item for item in confirmed if item.bias != DirectionBias.NEUTRAL
    )
    detected_biases = {
        item.bias for item in directional_detected
    }
    tentative_bias = (
        next(iter(detected_biases))
        if directional_detected
        and not directional_confirmed
        and len(detected_biases) == 1
        else None
    )
    tentative_strategies = (
        tuple(
            _evaluation_label(item)
            for item in directional_detected
            if item.bias == tentative_bias
        )
        if tentative_bias is not None
        else ()
    )

    if not detected:
        reasons.append("No se detectó ninguna estrategia.")
    elif not directional_confirmed:
        if not confirmed:
            reasons.append(
                "Las estrategias detectadas todavía tienen requisitos pendientes "
                "o incumplidos."
            )
        elif tentative_bias is not None:
            reasons.append(
                "Las estrategias direccionales detectadas todavía tienen "
                "requisitos pendientes o incumplidos."
            )
        if tentative_bias is not None:
            supporting = ", ".join(tentative_strategies)
            reasons.append(
                f"Sesgo tentativo detectado: {tentative_bias.value} por "
                f"{supporting}; faltan confirmaciones obligatorias."
            )
        elif len(detected_biases) > 1:
            reasons.append(
                "Las estrategias detectadas tienen sesgos tentativos en conflicto."
            )

    if active_invalidations:
        reasons.append("Existe al menos una invalidación activa.")
        reasons.append(
            "Invalidaciones activas: " + ", ".join(active_invalidations) + "."
        )
    if pending_invalidations:
        reasons.append(
            "Hay invalidaciones pendientes de revisión: "
            + ", ".join(pending_invalidations)
            + "."
        )
    if data_quality_status != GateStatus.APROBADO:
        reasons.append("La calidad de datos no está aprobada.")
    if panorama_status != GateStatus.APROBADO:
        reasons.append("El panorama general no está aprobado.")
    if risk_status != GateStatus.APROBADO:
        reasons.append("La evaluación de riesgo no está aprobada.")
    if governance_status != GateStatus.APROBADO:
        reasons.append("El plan y la disciplina operativa no están aprobados.")
    blocked_gates = {
        "calidad_datos": data_quality_status,
        "panorama": panorama_status,
        "riesgo": risk_status,
        "gobierno_operativo": governance_status,
    }
    blocked_gate_details = tuple(
        f"{name}={status.value}"
        for name, status in blocked_gates.items()
        if status != GateStatus.APROBADO
    )
    if blocked_gate_details:
        reasons.append(
            "Compuertas no aprobadas: " + ", ".join(blocked_gate_details) + "."
        )

    biases = {item.bias for item in directional_confirmed}
    if len(biases) == 1:
        bias = next(iter(biases))
        supporting = ", ".join(
            _evaluation_label(item)
            for item in directional_confirmed
            if item.bias == bias
        )
        reasons.append(
            f"Sesgo direccional confirmado: {bias.value} por {supporting}."
        )
    if len(biases) > 1:
        reasons.append("Las estrategias confirmadas tienen sesgos en conflicto.")
    elif not biases and confirmed:
        reasons.append("No existe un sesgo direccional confirmado.")

    gates_passed = (
        bool(confirmed)
        and not active_invalidations
        and not pending_invalidations
        and data_quality_status == GateStatus.APROBADO
        and panorama_status == GateStatus.APROBADO
        and risk_status == GateStatus.APROBADO
        and governance_status == GateStatus.APROBADO
        and len(biases) == 1
    )

    if gates_passed:
        bias = next(iter(biases))
        decision = (
            FinalDecision.CALL
            if bias == DirectionBias.CALL
            else FinalDecision.PUT
        )
        reasons.append("Todas las compuertas obligatorias fueron aprobadas.")
    else:
        decision = FinalDecision.NO_OPERAR

    return DecisionAssessment(
        decision=decision,
        confidence="NO_CALIBRADA",
        reasons=tuple(reasons),
        supporting_strategies=tuple(
            _evaluation_label(item) for item in directional_confirmed
        ),
        data_quality_status=data_quality_status,
        panorama_status=panorama_status,
        risk_status=risk_status,
        governance_status=governance_status,
        active_invalidations=active_invalidations,
        pending_invalidations=pending_invalidations,
        tentative_bias=tentative_bias,
        tentative_strategies=tentative_strategies,
    )
