"""Servicio end-to-end y autoritativo para una evaluación JJTrade AI."""

from collections.abc import Iterable
from dataclasses import dataclass

from analysis_models import DecisionAssessment, DirectionBias, GateStatus
from analysis_pipeline import (
    DETECTOR_REGISTRY,
    AnalysisContext,
    DetectorDefinition,
    PipelineReport,
    run_detection_pipeline,
)
from data_quality import DataQualityAssessment, evaluate_data_quality
from decision_engine import build_decision
from invalidation_engine import evaluate_common_invalidations
from levels_engine import MovingAverageLevel, map_moving_average_levels
from panorama_engine import PanoramaAssessment, evaluate_panorama


@dataclass(frozen=True)
class MarketAssessment:
    """Resultado completo, trazable y listo para interfaz o reporte."""

    pipeline: PipelineReport
    data_quality: DataQualityAssessment
    panorama: PanoramaAssessment
    levels: tuple[MovingAverageLevel, ...]
    invalidations: tuple
    decision: DecisionAssessment


def assess_market(
    context: AnalysisContext,
    *,
    panorama_path_clear: bool | None = None,
    news_clear: bool | None = None,
    panorama_human_approval: bool | None = None,
    data_current_review: bool | None = None,
    risk_status: GateStatus = GateStatus.NO_DISPONIBLE,
    risk_option_type: str | None = None,
    governance_status: GateStatus = GateStatus.NO_DISPONIBLE,
    detectors: Iterable[DetectorDefinition] = DETECTOR_REGISTRY,
) -> MarketAssessment:
    """Ejecuta todas las capas sin permitir atajos entre detector y decisión."""
    quality = evaluate_data_quality(
        context.datasets,
        live_market_data=context.live_market_data,
        session_closed=context.session_closed,
    )
    pipeline = run_detection_pipeline(context, detectors=detectors)
    effective_quality = quality
    if pipeline.errors:
        detector_issues = tuple(
            f"Error interno del detector {detector}: {detail}"
            for detector, detail in sorted(pipeline.errors.items())
        )
        effective_quality = DataQualityAssessment(
            status=GateStatus.RECHAZADO,
            issues=quality.issues + detector_issues,
            latest_sessions=quality.latest_sessions,
            candle_counts=quality.candle_counts,
        )
    detected_biases = {
        item.bias
        for item in pipeline.detected
        if item.bias is not DirectionBias.NEUTRAL
    }
    intended_bias = (
        next(iter(detected_biases)) if len(detected_biases) == 1 else None
    )
    effective_risk_status = risk_status
    normalized_risk_option_type = (
        risk_option_type.strip().upper() if risk_option_type is not None else None
    )
    if risk_status is GateStatus.APROBADO:
        if intended_bias is None or normalized_risk_option_type is None:
            effective_risk_status = GateStatus.NO_DISPONIBLE
        elif normalized_risk_option_type != intended_bias.value:
            effective_risk_status = GateStatus.RECHAZADO
    panorama = evaluate_panorama(
        context.datasets,
        intended_bias=intended_bias,
        path_clear=panorama_path_clear,
        news_clear=news_clear,
        human_approval=panorama_human_approval,
    )
    levels = (
        map_moving_average_levels(context.datasets, intended_bias)
        if intended_bias is not None
        else ()
    )
    effective_data_current = (
        False
        if effective_quality.status is not GateStatus.APROBADO
        else data_current_review
    )
    invalidations = evaluate_common_invalidations(
        pipeline.evaluations,
        relevant_news_present=None if news_clear is None else not news_clear,
        data_current=effective_data_current,
    )
    decision = build_decision(
        pipeline.evaluations,
        invalidations=invalidations,
        data_quality_status=effective_quality.status,
        panorama_status=panorama.status,
        risk_status=effective_risk_status,
        governance_status=governance_status,
    )
    return MarketAssessment(
        pipeline=pipeline,
        data_quality=effective_quality,
        panorama=panorama,
        levels=levels,
        invalidations=invalidations,
        decision=decision,
    )
