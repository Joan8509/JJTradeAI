"""Orquestador extensible de detectores multitemporales de JJTrade AI."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
import pandas as pd

from analysis_models import StrategyEvaluation
from investep_engine import evaluate_expuesto_bollinger
from strategies.ct15 import evaluate_ct15
from strategies.cambio_tendencia_hora import evaluate_cambio_tendencia_hora
from strategies.efecto_iman import evaluate_efecto_iman
from strategies.momentum import evaluate_momentum
from strategies.primer_salto import evaluate_first_jump_setup
from strategies.rebote_punto_medio import evaluate_rebote_punto_medio
from strategies.retorno_bollinger_lateral import evaluate_retorno_bollinger_lateral
from strategies.salto_lateralidad_hora import evaluate_salto_lateralidad_hora


@dataclass(frozen=True)
class AnalysisContext:
    """Datos y revisiones explícitas disponibles para todos los detectores."""

    datasets: Mapping[str, pd.DataFrame]
    reviews: Mapping[str, bool | None] = field(default_factory=dict)
    session_closed: bool = False
    auxiliary_datasets: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    live_market_data: bool = False

    def review(self, key: str) -> bool | None:
        """Obtiene una revisión ternaria: sí, no o todavía no disponible."""
        return self.reviews.get(key)


@dataclass(frozen=True)
class DetectorDefinition:
    """Metadatos ejecutables de un detector registrado."""

    detector_id: str
    strategy_ids: tuple[str, ...]
    diagnostic_ids: tuple[str, ...]
    required_timeframes: tuple[str, ...]
    minimum_rows: tuple[tuple[str, int], ...]
    evaluate: Callable[[AnalysisContext], tuple[StrategyEvaluation, ...]]


@dataclass(frozen=True)
class PipelineReport:
    """Evaluaciones producidas y detectores omitidos con su causa."""

    evaluations: tuple[StrategyEvaluation, ...]
    skipped: Mapping[str, str]
    errors: Mapping[str, str]

    @property
    def detected(self) -> tuple[StrategyEvaluation, ...]:
        """Devuelve solo estrategias cuya geometría detectora apareció."""
        return tuple(item for item in self.evaluations if item.detected)


def _evaluate_expuesto(context: AnalysisContext) -> tuple[StrategyEvaluation, ...]:
    return tuple(
        replace(
            evaluate_expuesto_bollinger(context.datasets[timeframe]),
            timeframe=timeframe,
        )
        for timeframe in ("15m", "1H", "1D")
        if timeframe in context.datasets
    )


def _evaluate_primer_salto(
    context: AnalysisContext,
) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_first_jump_setup(
            context.datasets["1D"],
            hourly=context.datasets["1H"],
            session_closed=context.session_closed,
            news_clear=context.review("common.news_clear"),
            path_clear=context.review("jump.path_clear"),
        ),
    )


def _evaluate_salto_lateralidad_hora(
    context: AnalysisContext,
) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_salto_lateralidad_hora(
            context.datasets["1H"],
            news_clear=context.review("common.news_clear"),
            path_clear=context.review("lateral_jump.path_clear"),
        ),
    )


def _evaluate_ct15(context: AnalysisContext) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_ct15(
            context.datasets["15m"],
            hourly=context.datasets.get("1H"),
            daily=context.datasets.get("1D"),
            prior_trend_valid=context.review("ct15.prior_trend"),
            trendline_drawn_correctly=context.review("ct15.trendline_drawn"),
            trendline_broken=context.review("ct15.trendline_broken"),
        ),
    )


def _evaluate_efecto_iman(
    context: AnalysisContext,
) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_efecto_iman(
            context.datasets["15m"],
            context.datasets["1H"],
            context.datasets["1D"],
            worden_volume_crossed=context.review("magnet.worden_volume_cross"),
        ),
    )


def _evaluate_rebote_punto_medio(
    context: AnalysisContext,
) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_rebote_punto_medio(
            context.datasets["15m"],
            context.datasets["1H"],
            context.datasets["1D"],
            midpoint_respected_in_15m=context.review("bounce.midpoint_respected"),
            hourly_candle_closed=True,
        ),
    )


def _evaluate_retorno_bollinger(
    context: AnalysisContext,
) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_retorno_bollinger_lateral(
            context.datasets["15m"],
            minute_1m=context.auxiliary_datasets.get("1m"),
            reversal_within_first_minutes=context.review("return.fast_reversal"),
        ),
    )


def _evaluate_cambio_hora(context: AnalysisContext) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_cambio_tendencia_hora(
            context.datasets["1H"],
            intraday_15m=context.datasets["15m"],
            hourly_candle_closed=True,
        ),
    )


def _evaluate_momentum(context: AnalysisContext) -> tuple[StrategyEvaluation, ...]:
    return (
        evaluate_momentum(
            context.datasets["1H"],
            context.datasets["1D"],
            path_clear=context.review("momentum.path_clear"),
        ),
    )


DETECTOR_REGISTRY: tuple[DetectorDefinition, ...] = (
    DetectorDefinition(
        "EXPUESTO_BOLLINGER",
        ("EXPUESTO_BOLLINGER_INFERIOR", "EXPUESTO_BOLLINGER_SUPERIOR"),
        ("SIN_EXPUESTO_BOLLINGER",),
        (),
        (),
        _evaluate_expuesto,
    ),
    DetectorDefinition(
        "PRIMER_SALTO",
        ("PRIMER_SALTO_RESPETADO_ALCISTA", "PRIMER_SALTO_RESPETADO_BAJISTA"),
        ("SIN_PRIMER_SALTO",),
        ("1H", "1D"),
        (("1H", 1), ("1D", 6)),
        _evaluate_primer_salto,
    ),
    DetectorDefinition(
        "SALTO_LATERALIDAD_HORA",
        ("SALTO_LATERALIDAD_HORA_ALCISTA", "SALTO_LATERALIDAD_HORA_BAJISTA"),
        ("SIN_SALTO_LATERALIDAD_HORA",),
        ("1H",),
        (("1H", 16),),
        _evaluate_salto_lateralidad_hora,
    ),
    DetectorDefinition(
        "CT15",
        ("CT15_ALCISTA", "CT15_BAJISTA"),
        ("SIN_CT15",),
        ("15m",),
        (("15m", 2),),
        _evaluate_ct15,
    ),
    DetectorDefinition(
        "EFECTO_IMAN",
        ("EFECTO_IMAN_TENDENCIA_ALCISTA", "EFECTO_IMAN_TENDENCIA_BAJISTA"),
        ("SIN_EFECTO_IMAN",),
        ("15m", "1H", "1D"),
        (("15m", 1), ("1H", 1), ("1D", 2)),
        _evaluate_efecto_iman,
    ),
    DetectorDefinition(
        "REBOTE_PUNTO_MEDIO",
        ("REBOTE_PUNTO_MEDIO_ALCISTA", "REBOTE_PUNTO_MEDIO_BAJISTA"),
        ("SIN_REBOTE_PUNTO_MEDIO",),
        ("15m", "1H", "1D"),
        (("15m", 1), ("1H", 1), ("1D", 3)),
        _evaluate_rebote_punto_medio,
    ),
    DetectorDefinition(
        "RETORNO_BOLLINGER_LATERAL",
        ("RETORNO_BOLLINGER_LATERAL_ALCISTA", "RETORNO_BOLLINGER_LATERAL_BAJISTA"),
        ("SIN_RETORNO_BOLLINGER_LATERAL",),
        ("15m",),
        (("15m", 2),),
        _evaluate_retorno_bollinger,
    ),
    DetectorDefinition(
        "CAMBIO_TENDENCIA_HORA",
        ("CAMBIO_TENDENCIA_HORA_ALCISTA", "CAMBIO_TENDENCIA_HORA_BAJISTA"),
        ("SIN_CAMBIO_TENDENCIA_HORA",),
        ("15m", "1H"),
        (("15m", 1), ("1H", 14)),
        _evaluate_cambio_hora,
    ),
    DetectorDefinition(
        "MOMENTUM",
        ("MOMENTUM_ALCISTA", "MOMENTUM_BAJISTA"),
        ("SIN_MOMENTUM",),
        ("1H", "1D"),
        (("1H", 1), ("1D", 1)),
        _evaluate_momentum,
    ),
)


def run_detection_pipeline(
    context: AnalysisContext,
    *,
    detectors: Iterable[DetectorDefinition] = DETECTOR_REGISTRY,
) -> PipelineReport:
    """Ejecuta detectores compatibles sin ocultar omisiones ni errores."""
    evaluations: list[StrategyEvaluation] = []
    skipped: dict[str, str] = {}
    errors: dict[str, str] = {}

    for definition in detectors:
        missing = [
            timeframe
            for timeframe in definition.required_timeframes
            if timeframe not in context.datasets
        ]
        if missing:
            skipped[definition.detector_id] = (
                "Faltan temporalidades: " + ", ".join(missing)
            )
            continue
        insufficient = [
            (timeframe, minimum, len(context.datasets[timeframe]))
            for timeframe, minimum in definition.minimum_rows
            if timeframe in context.datasets
            and len(context.datasets[timeframe]) < minimum
        ]
        if insufficient:
            skipped[definition.detector_id] = (
                "Historial insuficiente: "
                + ", ".join(
                    f"{timeframe}={actual}/{minimum}"
                    for timeframe, minimum, actual in insufficient
                )
            )
            continue
        try:
            raw_evaluations = definition.evaluate(context)
            if not isinstance(raw_evaluations, tuple):
                raise ValueError("El detector debe devolver una tupla de evaluaciones.")
            if any(
                not isinstance(item, StrategyEvaluation)
                for item in raw_evaluations
            ):
                raise TypeError(
                    "El detector devolvio un objeto que no es StrategyEvaluation."
                )
            detector_timeframe = "+".join(definition.required_timeframes)
            detector_evaluations = tuple(
                replace(item, timeframe=detector_timeframe)
                if not item.timeframe and detector_timeframe
                else item
                for item in raw_evaluations
            )
            _validate_detector_outputs(
                definition,
                detector_evaluations,
                available_timeframes=set(context.datasets),
            )
            evaluations.extend(detector_evaluations)
        except (TypeError, ValueError) as error:
            errors[definition.detector_id] = str(error)

    return PipelineReport(
        evaluations=tuple(evaluations), skipped=skipped, errors=errors
    )


def _validate_detector_outputs(
    definition: DetectorDefinition,
    evaluations: tuple[StrategyEvaluation, ...],
    *,
    available_timeframes: set[str],
) -> None:
    allowed_ids = set(definition.strategy_ids) | set(definition.diagnostic_ids)
    seen: set[tuple[str, str]] = set()
    expected_timeframe = "+".join(definition.required_timeframes)
    for evaluation in evaluations:
        if not isinstance(evaluation, StrategyEvaluation):
            raise TypeError("El detector devolvio un objeto que no es StrategyEvaluation.")
        if evaluation.strategy_id not in allowed_ids:
            raise ValueError(
                f"ID no declarado por {definition.detector_id}: "
                f"{evaluation.strategy_id}."
            )
        if evaluation.strategy_id in definition.diagnostic_ids:
            if evaluation.detected or evaluation.bias.value != "NEUTRAL":
                raise ValueError(
                    f"El diagnostico {evaluation.strategy_id} debe ser neutral "
                    "y no detectado."
                )
        if expected_timeframe:
            if evaluation.timeframe != expected_timeframe:
                raise ValueError(
                    f"Temporalidad de salida invalida para "
                    f"{definition.detector_id}: {evaluation.timeframe or 'VACIA'}."
                )
        elif evaluation.timeframe not in available_timeframes:
            raise ValueError(
                f"Temporalidad dinamica no disponible para "
                f"{definition.detector_id}: {evaluation.timeframe or 'VACIA'}."
            )
        identity = (evaluation.strategy_id, evaluation.timeframe)
        if identity in seen:
            raise ValueError(
                f"Salida duplicada de {definition.detector_id}: "
                f"{evaluation.strategy_id}@{evaluation.timeframe}."
            )
        seen.add(identity)
