"""Pruebas de invalidaciones comunes."""

import unittest

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from invalidation_engine import evaluate_common_invalidations


def _confirmed(
    bias: DirectionBias, strategy_id: str = "TEST"
) -> StrategyEvaluation:
    criterion = CriterionEvaluation(
        "required", "Requisito", EvaluationStatus.CUMPLE, True, "ok", "test"
    )
    return StrategyEvaluation(strategy_id, "Test", bias, True, (criterion,))


class InvalidationEngineTests(unittest.TestCase):
    def test_news_and_stale_data_are_active_invalidations(self) -> None:
        result = evaluate_common_invalidations(
            [], relevant_news_present=True, data_current=False
        )

        self.assertIs(result[0].status, EvaluationStatus.CUMPLE)
        self.assertIs(result[1].status, EvaluationStatus.CUMPLE)

    def test_opposite_confirmed_biases_are_invalidated(self) -> None:
        result = evaluate_common_invalidations(
            [_confirmed(DirectionBias.CALL), _confirmed(DirectionBias.PUT)]
        )

        self.assertIs(result[2].status, EvaluationStatus.CUMPLE)

    def test_conflict_depends_on_bias_not_strategy_id(self) -> None:
        result = evaluate_common_invalidations(
            [
                _confirmed(DirectionBias.CALL, "DUPLICATED"),
                _confirmed(DirectionBias.PUT, "DUPLICATED"),
            ]
        )

        self.assertIs(result[2].status, EvaluationStatus.CUMPLE)

    def test_unknown_external_checks_remain_unavailable(self) -> None:
        result = evaluate_common_invalidations([])

        self.assertIs(result[0].status, EvaluationStatus.NO_DISPONIBLE)
        self.assertIs(result[1].status, EvaluationStatus.NO_DISPONIBLE)


if __name__ == "__main__":
    unittest.main()
