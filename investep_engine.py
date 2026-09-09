"""Motor agregador de detectores de estrategias de la metodología Investep."""

from collections.abc import Callable
from typing import TypedDict

import pandas as pd

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from strategy_registry import STRATEGY_REGISTRY


class StrategyAnalysis(TypedDict):
    """Contrato común que debe devolver cada detector de estrategia."""

    estrategias_detectadas: list[str]
    sesgo_inicial: str
    senal: str
    confianza: str
    motivo: str


class StrategiesDetection(TypedDict):
    """Resultado acumulado de todos los detectores registrados."""

    estrategias_detectadas: list[str]
    sesgos_detectados: list[str]
    pendientes_confirmacion: list[str]
    analisis: list[StrategyAnalysis]


def analyze_expuesto_bollinger(df: pd.DataFrame) -> StrategyAnalysis:
    """Detecta exposición en la última vela sin emitir una decisión final."""
    required_columns = {"close", "bollinger_upper", "bollinger_lower"}
    missing_columns = sorted(required_columns.difference(df.columns))
    if missing_columns:
        raise ValueError(
            "Faltan columnas para analizar Expuesto en Bollinger: "
            + ", ".join(missing_columns)
        )
    if df.empty:
        raise ValueError("No hay velas disponibles para analizar.")

    latest = df.iloc[-1]
    if latest[list(required_columns)].isna().any():
        raise ValueError("La última vela no tiene bandas de Bollinger calculadas.")

    if latest["close"] < latest["bollinger_lower"]:
        return {
            "estrategias_detectadas": ["EXPUESTO_BOLLINGER_INFERIOR"],
            "sesgo_inicial": "CALL_REBOTE",
            "senal": "PENDIENTE_CONFIRMACION",
            "confianza": "BAJA",
            "motivo": (
                "El precio cerró por debajo de la banda inferior de Bollinger. "
                "Posible sobreextensión bajista, pero requiere confirmación "
                "antes de operar."
            ),
        }
    if latest["close"] > latest["bollinger_upper"]:
        return {
            "estrategias_detectadas": ["EXPUESTO_BOLLINGER_SUPERIOR"],
            "sesgo_inicial": "PUT_RETROCESO",
            "senal": "PENDIENTE_CONFIRMACION",
            "confianza": "BAJA",
            "motivo": (
                "El precio cerró por encima de la banda superior de Bollinger. "
                "Posible sobreextensión alcista, pero requiere confirmación "
                "antes de operar."
            ),
        }
    return {
        "estrategias_detectadas": [],
        "sesgo_inicial": "NEUTRAL",
        "senal": "SIN_SENAL",
        "confianza": "NINGUNA",
        "motivo": "El precio no está expuesto fuera de Bollinger.",
    }


def evaluate_expuesto_bollinger(df: pd.DataFrame) -> StrategyEvaluation:
    """Adapta Expuesto en Bollinger al contrato auditable del pipeline."""
    analysis = analyze_expuesto_bollinger(df)
    detected = analysis["estrategias_detectadas"]

    if not detected:
        exposure_criterion = CriterionEvaluation(
            criterion_id="bollinger_exposure",
            name="Cierre fuera de Bollinger",
            status=EvaluationStatus.NO_CUMPLE,
            required=True,
            detail=analysis["motivo"],
            source="docs/INVESTEP_ENGINE.md",
        )
        return StrategyEvaluation(
            strategy_id="SIN_EXPUESTO_BOLLINGER",
            name="Expuesto en Bollinger",
            bias=DirectionBias.NEUTRAL,
            detected=False,
            criteria=(exposure_criterion,),
        )

    strategy_id = detected[0]
    bias = (
        DirectionBias.CALL
        if strategy_id == "EXPUESTO_BOLLINGER_INFERIOR"
        else DirectionBias.PUT
    )
    exposure_criterion = CriterionEvaluation(
        criterion_id="bollinger_exposure",
        name="Cierre fuera de Bollinger",
        status=EvaluationStatus.CUMPLE,
        required=True,
        detail=analysis["motivo"],
        source="docs/INVESTEP_ENGINE.md",
    )
    confirmation_criterion = CriterionEvaluation(
        criterion_id="required_confirmation",
        name="Confirmación posterior a la exposición",
        status=EvaluationStatus.NO_DISPONIBLE,
        required=True,
        detail=(
            "Expuesto en Bollinger es solo un detector. Requiere una "
            "confirmación independiente antes de operar."
        ),
        source="docs/LESSONS_LEARNED.md#lección-001",
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name=STRATEGY_REGISTRY[strategy_id]["nombre"],
        bias=bias,
        detected=True,
        criteria=(exposure_criterion, confirmation_criterion),
    )


# Registro extensible: los próximos detectores se incorporarán aquí siempre
# que respeten el contrato StrategyAnalysis.
STRATEGY_DETECTORS: tuple[Callable[[pd.DataFrame], StrategyAnalysis], ...] = (
    analyze_expuesto_bollinger,
)


def detect_strategies(df: pd.DataFrame) -> StrategiesDetection:
    """Ejecuta los detectores registrados y acumula sus hallazgos.

    Por ahora el registro contiene únicamente Expuesto en Bollinger. Los
    análisis neutrales no se agregan, de modo que todas las colecciones quedan
    vacías cuando no existe ninguna estrategia detectada.
    """
    result: StrategiesDetection = {
        "estrategias_detectadas": [],
        "sesgos_detectados": [],
        "pendientes_confirmacion": [],
        "analisis": [],
    }

    for detector in STRATEGY_DETECTORS:
        analysis = detector(df)
        detected = analysis["estrategias_detectadas"]
        if not detected:
            continue

        for strategy_id in detected:
            try:
                strategy = STRATEGY_REGISTRY[strategy_id]
            except KeyError as error:
                raise ValueError(
                    f"La estrategia detectada no está registrada: {strategy_id}"
                ) from error

            result["estrategias_detectadas"].append(strategy_id)
            result["sesgos_detectados"].append(strategy["sesgo"])

            if strategy["requiere_confirmacion"]:
                result["pendientes_confirmacion"].append(strategy_id)

        result["analisis"].append(analysis)

    return result
