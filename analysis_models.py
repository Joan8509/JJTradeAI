"""Modelos auditables para las evaluaciones y decisiones de JJTrade AI."""

from dataclasses import dataclass, field
from enum import Enum


class EvaluationStatus(str, Enum):
    """Estado verificable de un criterio metodológico."""

    CUMPLE = "CUMPLE"
    NO_CUMPLE = "NO_CUMPLE"
    NO_DISPONIBLE = "NO_DISPONIBLE"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class DirectionBias(str, Enum):
    """Dirección propuesta por una estrategia, aún no definitiva."""

    CALL = "CALL"
    PUT = "PUT"
    NEUTRAL = "NEUTRAL"


class FinalDecision(str, Enum):
    """Decisiones finales admitidas por el pipeline."""

    CALL = "CALL"
    PUT = "PUT"
    NO_OPERAR = "NO_OPERAR"


class GateStatus(str, Enum):
    """Estado de una compuerta posterior a los detectores."""

    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
    NO_DISPONIBLE = "NO_DISPONIBLE"
    REQUIERE_REVISION = "REQUIERE_REVISION"


@dataclass(frozen=True)
class CriterionEvaluation:
    """Resultado de evaluar una condición individual con trazabilidad."""

    criterion_id: str
    name: str
    status: EvaluationStatus
    required: bool
    detail: str
    source: str


@dataclass(frozen=True)
class StrategyEvaluation:
    """Evaluación completa de una estrategia detectora."""

    strategy_id: str
    name: str
    bias: DirectionBias
    detected: bool
    criteria: tuple[CriterionEvaluation, ...] = field(default_factory=tuple)
    timeframe: str = ""

    @property
    def compliance_percentage(self) -> float:
        """Calcula cumplimiento solo sobre criterios evaluables."""
        evaluable = [
            criterion
            for criterion in self.criteria
            if criterion.status
            in {EvaluationStatus.CUMPLE, EvaluationStatus.NO_CUMPLE}
        ]
        if not evaluable:
            return 0.0
        fulfilled = sum(
            criterion.status == EvaluationStatus.CUMPLE
            for criterion in evaluable
        )
        return round(fulfilled / len(evaluable) * 100, 2)

    @property
    def required_criteria_satisfied(self) -> bool:
        """Indica si todos los requisitos obligatorios fueron confirmados."""
        required = [criterion for criterion in self.criteria if criterion.required]
        return bool(required) and all(
            criterion.status == EvaluationStatus.CUMPLE for criterion in required
        )


@dataclass(frozen=True)
class DecisionAssessment:
    """Resultado final explicable del pipeline de decisión."""

    decision: FinalDecision
    confidence: str
    reasons: tuple[str, ...]
    supporting_strategies: tuple[str, ...]
    data_quality_status: GateStatus
    panorama_status: GateStatus
    risk_status: GateStatus
    governance_status: GateStatus
    active_invalidations: tuple[str, ...]
    pending_invalidations: tuple[str, ...] = field(default_factory=tuple)
    tentative_bias: DirectionBias | None = None
    tentative_strategies: tuple[str, ...] = field(default_factory=tuple)
