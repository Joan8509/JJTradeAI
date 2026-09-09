"""Invalidaciones transversales separadas de los detectores de estrategia."""

from collections.abc import Iterable

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)


SOURCE = "docs/strategies/INVALIDACIONES.md"


def _invalidation(
    criterion_id: str,
    name: str,
    active: bool | None,
    detail: str,
) -> CriterionEvaluation:
    """Crea una condición donde CUMPLE significa invalidación activa."""
    status = (
        EvaluationStatus.NO_DISPONIBLE
        if active is None
        else EvaluationStatus.CUMPLE
        if active
        else EvaluationStatus.NO_CUMPLE
    )
    return CriterionEvaluation(
        criterion_id=criterion_id,
        name=name,
        status=status,
        required=True,
        detail=detail,
        source=SOURCE,
    )


def evaluate_common_invalidations(
    evaluations: Iterable[StrategyEvaluation],
    *,
    relevant_news_present: bool | None = None,
    data_current: bool | None = None,
) -> tuple[CriterionEvaluation, ...]:
    """Evalúa bloqueos comunes sin duplicar requisitos de cada estrategia."""
    confirmed = [
        item
        for item in evaluations
        if item.detected and item.required_criteria_satisfied
    ]
    biases = {
        item.bias for item in confirmed if item.bias is not DirectionBias.NEUTRAL
    }
    conflict = len(biases) > 1
    stale = None if data_current is None else not data_current
    return (
        _invalidation(
            "relevant_news",
            "Noticia corporativa o macroeconómica relevante",
            relevant_news_present,
            "La metodología establece que una noticia puede invalidar la estrategia.",
        ),
        _invalidation(
            "stale_data",
            "Datos desactualizados o de sesiones no coincidentes",
            stale,
            "Todas las temporalidades deben corresponder al análisis vigente.",
        ),
        _invalidation(
            "confirmed_bias_conflict",
            "Estrategias confirmadas con direcciones opuestas",
            conflict,
            "No se permite resolver un conflicto direccional por votación simple.",
        ),
    )
