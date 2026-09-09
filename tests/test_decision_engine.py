"""Pruebas de seguridad para la compuerta final de decisiones."""

import unittest

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    FinalDecision,
    GateStatus,
    StrategyEvaluation,
)
from decision_engine import build_decision
from investep_engine import evaluate_expuesto_bollinger
import pandas as pd


def confirmed_strategy(
    bias: DirectionBias, strategy_id: str = "TEST_STRATEGY"
) -> StrategyEvaluation:
    """Crea una estrategia mínima cuyos requisitos fueron confirmados."""
    criterion = CriterionEvaluation(
        criterion_id="required",
        name="Requisito obligatorio",
        status=EvaluationStatus.CUMPLE,
        required=True,
        detail="Confirmado para la prueba.",
        source="test",
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name="Estrategia de prueba",
        bias=bias,
        detected=True,
        criteria=(criterion,),
    )


def detected_pending_strategy(
    bias: DirectionBias, strategy_id: str = "TEST_PENDING_STRATEGY"
) -> StrategyEvaluation:
    """Crea una estrategia detectada con requisitos obligatorios pendientes."""
    criterion = CriterionEvaluation(
        criterion_id="required",
        name="Requisito obligatorio",
        status=EvaluationStatus.NO_DISPONIBLE,
        required=True,
        detail="Pendiente para la prueba.",
        source="test",
    )
    return StrategyEvaluation(
        strategy_id=strategy_id,
        name="Estrategia pendiente de prueba",
        bias=bias,
        detected=True,
        criteria=(criterion,),
    )


class DecisionEngineTests(unittest.TestCase):
    def test_expuesto_alone_never_becomes_final_decision(self) -> None:
        df = pd.DataFrame(
            {
                "close": [80.0],
                "bollinger_lower": [90.0],
                "bollinger_upper": [110.0],
            }
        )
        exposed = evaluate_expuesto_bollinger(df)
        result = build_decision(
            [exposed],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )
        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)

    def test_missing_gates_produce_no_operar(self) -> None:
        result = build_decision([confirmed_strategy(DirectionBias.CALL)])
        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertIn(
            "Compuertas no aprobadas: panorama=NO_DISPONIBLE, "
            "riesgo=NO_DISPONIBLE, gobierno_operativo=NO_DISPONIBLE.",
            result.reasons,
        )

    def test_approved_call_passes(self) -> None:
        result = build_decision(
            [confirmed_strategy(DirectionBias.CALL)],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )
        self.assertEqual(result.decision, FinalDecision.CALL)
        self.assertIn(
            "Sesgo direccional confirmado: CALL por TEST_STRATEGY.",
            result.reasons,
        )

    def test_confirmed_direction_is_explained_even_when_gate_is_missing(self) -> None:
        result = build_decision(
            [confirmed_strategy(DirectionBias.PUT)],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.NO_DISPONIBLE,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertIn(
            "Sesgo direccional confirmado: PUT por TEST_STRATEGY.",
            result.reasons,
        )
        self.assertIn("La evaluación de riesgo no está aprobada.", result.reasons)
        self.assertIn(
            "Compuertas no aprobadas: riesgo=NO_DISPONIBLE.",
            result.reasons,
        )

    def test_tentative_direction_is_explained_without_final_entry(self) -> None:
        result = build_decision(
            [detected_pending_strategy(DirectionBias.CALL)],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertIn(
            "Sesgo tentativo detectado: CALL por TEST_PENDING_STRATEGY; "
            "faltan confirmaciones obligatorias.",
            result.reasons,
        )
        self.assertEqual(result.supporting_strategies, ())
        self.assertIs(result.tentative_bias, DirectionBias.CALL)
        self.assertEqual(result.tentative_strategies, ("TEST_PENDING_STRATEGY",))

    def test_multitimeframe_tentative_strategies_are_disambiguated(self) -> None:
        pending_15m = detected_pending_strategy(
            DirectionBias.CALL, "TEST_PENDING"
        )
        pending_1h = StrategyEvaluation(
            strategy_id=pending_15m.strategy_id,
            name=pending_15m.name,
            bias=pending_15m.bias,
            detected=pending_15m.detected,
            criteria=pending_15m.criteria,
            timeframe="1H",
        )
        pending_15m = StrategyEvaluation(
            strategy_id=pending_15m.strategy_id,
            name=pending_15m.name,
            bias=pending_15m.bias,
            detected=pending_15m.detected,
            criteria=pending_15m.criteria,
            timeframe="15m",
        )

        result = build_decision([pending_15m, pending_1h])

        self.assertEqual(
            result.tentative_strategies,
            ("TEST_PENDING@15m", "TEST_PENDING@1H"),
        )

    def test_duplicate_strategy_evaluation_is_rejected(self) -> None:
        strategy = confirmed_strategy(DirectionBias.CALL)

        with self.assertRaisesRegex(ValueError, "duplicada"):
            build_decision([strategy, strategy])

    def test_repeated_strategy_requires_timeframe(self) -> None:
        first = detected_pending_strategy(DirectionBias.CALL, "TEST_REPEAT")
        second = detected_pending_strategy(DirectionBias.CALL, "TEST_REPEAT")
        second = StrategyEvaluation(
            strategy_id=second.strategy_id,
            name=second.name,
            bias=second.bias,
            detected=second.detected,
            criteria=second.criteria,
            timeframe="1H",
        )

        with self.assertRaisesRegex(ValueError, "declarar timeframe"):
            build_decision([first, second])

    def test_strategy_identity_is_required(self) -> None:
        strategy = confirmed_strategy(DirectionBias.CALL, "")

        with self.assertRaisesRegex(ValueError, "strategy_id"):
            build_decision([strategy])

    def test_duplicate_invalidations_are_rejected(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="news",
            name="Noticias",
            status=EvaluationStatus.NO_CUMPLE,
            required=True,
            detail="Sin noticias.",
            source="test",
        )

        with self.assertRaisesRegex(ValueError, "duplicada"):
            build_decision([], invalidations=[invalidation, invalidation])

    def test_invalidation_identity_is_required(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="",
            name="",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="Pendiente.",
            source="test",
        )

        with self.assertRaisesRegex(ValueError, "criterion_id"):
            build_decision([], invalidations=[invalidation])

    def test_gate_status_text_is_rejected_at_boundary(self) -> None:
        with self.assertRaisesRegex(TypeError, "risk_status"):
            build_decision(
                [confirmed_strategy(DirectionBias.CALL)],
                risk_status="APROBADO",  # type: ignore[arg-type]
            )

    def test_strategy_metadata_types_are_validated(self) -> None:
        strategy = StrategyEvaluation(
            strategy_id="BAD_BIAS",
            name="Sesgo inválido",
            bias="CALL",  # type: ignore[arg-type]
            detected=True,
            criteria=(),
        )

        with self.assertRaisesRegex(TypeError, "DirectionBias"):
            build_decision([strategy])

    def test_invalidation_status_type_is_validated(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="news",
            name="Noticias",
            status="NO_DISPONIBLE",  # type: ignore[arg-type]
            required=True,
            detail="Pendiente.",
            source="test",
        )

        with self.assertRaisesRegex(TypeError, "EvaluationStatus"):
            build_decision([], invalidations=[invalidation])

    def test_duplicate_strategy_criterion_ids_are_rejected(self) -> None:
        criterion = CriterionEvaluation(
            criterion_id="required",
            name="Confirmación",
            status=EvaluationStatus.CUMPLE,
            required=True,
            detail="Confirmada.",
            source="test",
        )
        strategy = StrategyEvaluation(
            strategy_id="DUPLICATE_CRITERIA",
            name="Criterios duplicados",
            bias=DirectionBias.CALL,
            detected=True,
            criteria=(criterion, criterion),
        )

        with self.assertRaisesRegex(ValueError, "criterion_id duplicado"):
            build_decision([strategy])

    def test_strategy_criterion_identity_is_required(self) -> None:
        criterion = CriterionEvaluation(
            criterion_id="",
            name="",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="Pendiente.",
            source="test",
        )
        strategy = StrategyEvaluation(
            strategy_id="BAD_CRITERION",
            name="Criterio inválido",
            bias=DirectionBias.CALL,
            detected=True,
            criteria=(criterion,),
        )

        with self.assertRaisesRegex(ValueError, "criterion_id"):
            build_decision([strategy])

    def test_strategy_criterion_traceability_is_required(self) -> None:
        for field, message in (("detail", "detalle"), ("source", "fuente")):
            values = {
                "criterion_id": "required",
                "name": "Confirmación",
                "status": EvaluationStatus.CUMPLE,
                "required": True,
                "detail": "Confirmada.",
                "source": "test",
            }
            values[field] = ""
            criterion = CriterionEvaluation(**values)
            strategy = StrategyEvaluation(
                strategy_id="BAD_TRACE",
                name="Trazabilidad inválida",
                bias=DirectionBias.CALL,
                detected=True,
                criteria=(criterion,),
            )

            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, message):
                    build_decision([strategy])

    def test_invalidation_traceability_is_required(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="news",
            name="Noticias",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="",
            source="test",
        )

        with self.assertRaisesRegex(ValueError, "detalle"):
            build_decision([], invalidations=[invalidation])

    def test_conflicting_tentative_biases_are_explained(self) -> None:
        result = build_decision(
            [
                detected_pending_strategy(DirectionBias.CALL, "TEST_PENDING_CALL"),
                detected_pending_strategy(DirectionBias.PUT, "TEST_PENDING_PUT"),
            ],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertIn(
            "Las estrategias detectadas tienen sesgos tentativos en conflicto.",
            result.reasons,
        )
        self.assertIsNone(result.tentative_bias)
        self.assertEqual(result.tentative_strategies, ())

    def test_conflicting_biases_produce_no_operar(self) -> None:
        result = build_decision(
            [
                confirmed_strategy(DirectionBias.CALL, "TEST_CALL"),
                confirmed_strategy(DirectionBias.PUT, "TEST_PUT"),
            ],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )
        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)

    def test_neutral_confirmed_strategy_does_not_support_directional_decision(self) -> None:
        result = build_decision(
            [
                confirmed_strategy(DirectionBias.CALL, "TEST_CALL"),
                confirmed_strategy(DirectionBias.NEUTRAL, "TEST_NEUTRAL"),
            ],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.CALL)
        self.assertEqual(result.supporting_strategies, ("TEST_CALL",))
        self.assertIn(
            "Sesgo direccional confirmado: CALL por TEST_CALL.",
            result.reasons,
        )
        self.assertNotIn("TEST_NEUTRAL", " ".join(result.reasons))

    def test_only_neutral_confirmed_strategy_is_not_operable(self) -> None:
        result = build_decision(
            [confirmed_strategy(DirectionBias.NEUTRAL, "TEST_NEUTRAL")],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertEqual(result.supporting_strategies, ())
        self.assertIn("No existe un sesgo direccional confirmado.", result.reasons)

    def test_confirmed_neutral_does_not_hide_pending_directional_bias(self) -> None:
        result = build_decision(
            [
                confirmed_strategy(DirectionBias.NEUTRAL, "TEST_NEUTRAL"),
                detected_pending_strategy(DirectionBias.CALL, "TEST_PENDING_CALL"),
            ],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertEqual(result.supporting_strategies, ())
        self.assertIs(result.tentative_bias, DirectionBias.CALL)
        self.assertEqual(result.tentative_strategies, ("TEST_PENDING_CALL",))
        self.assertIn(
            "Las estrategias direccionales detectadas todavía tienen "
            "requisitos pendientes o incumplidos.",
            result.reasons,
        )
        self.assertIn(
            "Sesgo tentativo detectado: CALL por TEST_PENDING_CALL; "
            "faltan confirmaciones obligatorias.",
            result.reasons,
        )

    def test_confirmed_neutral_keeps_pending_directional_conflict_visible(self) -> None:
        result = build_decision(
            [
                confirmed_strategy(DirectionBias.NEUTRAL, "TEST_NEUTRAL"),
                detected_pending_strategy(DirectionBias.CALL, "TEST_PENDING_CALL"),
                detected_pending_strategy(DirectionBias.PUT, "TEST_PENDING_PUT"),
            ],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertIsNone(result.tentative_bias)
        self.assertEqual(result.tentative_strategies, ())
        self.assertIn(
            "Las estrategias detectadas tienen sesgos tentativos en conflicto.",
            result.reasons,
        )

    def test_active_invalidation_produces_no_operar(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="invalid",
            name="Invalidación activa",
            status=EvaluationStatus.CUMPLE,
            required=True,
            detail="Activa para la prueba.",
            source="test",
        )
        result = build_decision(
            [confirmed_strategy(DirectionBias.PUT)],
            invalidations=(item for item in [invalidation]),
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )
        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertEqual(result.active_invalidations, ("Invalidación activa",))
        self.assertIn(
            "Invalidaciones activas: Invalidación activa.",
            result.reasons,
        )

    def test_pending_required_invalidation_produces_no_operar(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="pending_invalid",
            name="Invalidación pendiente",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=True,
            detail="Falta revisión para la prueba.",
            source="test",
        )
        result = build_decision(
            [confirmed_strategy(DirectionBias.CALL)],
            invalidations=[invalidation],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertEqual(result.active_invalidations, ())
        self.assertEqual(
            result.pending_invalidations,
            ("Invalidación pendiente",),
        )
        self.assertIn(
            "Hay invalidaciones pendientes de revisión: "
            "Invalidación pendiente.",
            result.reasons,
        )

    def test_optional_pending_invalidation_also_blocks_decision(self) -> None:
        invalidation = CriterionEvaluation(
            criterion_id="optional_pending",
            name="Evidencia opcional pendiente",
            status=EvaluationStatus.NO_DISPONIBLE,
            required=False,
            detail="No es obligatoria para la prueba.",
            source="test",
        )
        result = build_decision(
            [confirmed_strategy(DirectionBias.PUT)],
            invalidations=[invalidation],
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertEqual(
            result.pending_invalidations,
            ("Evidencia opcional pendiente",),
        )

    def test_rejected_data_quality_produces_no_operar(self) -> None:
        result = build_decision(
            [confirmed_strategy(DirectionBias.CALL)],
            data_quality_status=GateStatus.RECHAZADO,
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertEqual(result.decision, FinalDecision.NO_OPERAR)
        self.assertIs(result.data_quality_status, GateStatus.RECHAZADO)
        self.assertIn("La calidad de datos no está aprobada.", result.reasons)


if __name__ == "__main__":
    unittest.main()
