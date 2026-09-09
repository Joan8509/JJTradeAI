"""Pruebas de las reglas objetivas oficiales de CT15."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.ct15 import evaluate_ct15


def _bullish_data(*, volatility: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-06-23 15:45", "2026-06-24 09:30"],
            "open": [96.0, 99.0],
            "close": [97.0, 100.0],
            "bollinger_mid": [98.0, 98.5],
            "bollinger_upper": [101.0, 102.0],
            "bollinger_lower": [95.0, 94.5],
            "bollinger_mid_slope": [-0.2, 0.5],
            "bollinger_both_expanding": [False, volatility],
        }
    )


def _bullish_data_with_trendline() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": [f"2026-06-23 {hour:02d}:30" for hour in range(10, 18)] + ["2026-06-24 09:30"],
            "open": [100.4 - index * 0.5 for index in range(8)] + [99.0],
            "high": [100.8 - index * 0.5 for index in range(8)] + [100.5],
            "low": [99.5 - index * 0.5 for index in range(8)] + [98.7],
            "close": [100.0 - index * 0.5 for index in range(8)] + [100.0],
            "bollinger_mid": [101.0 - index * 0.3 for index in range(8)] + [98.5],
            "bollinger_upper": [103.0 - index * 0.3 for index in range(8)] + [102.0],
            "bollinger_lower": [97.0 - index * 0.3 for index in range(8)] + [94.5],
            "bollinger_mid_slope": [-0.3] * 8 + [0.5],
            "bollinger_both_expanding": [False] * 8 + [True],
        }
    )
    return frame


class CT15Tests(unittest.TestCase):
    def test_partial_bullish_candidate_is_not_detected_without_trendline(self) -> None:
        result = evaluate_ct15(_bullish_data())

        self.assertFalse(result.detected)
        self.assertEqual(result.strategy_id, "CT15_ALCISTA")
        self.assertIs(result.bias, DirectionBias.CALL)
        self.assertFalse(result.required_criteria_satisfied)

    def test_no_volatility_is_false_ct15(self) -> None:
        result = evaluate_ct15(_bullish_data(volatility=False))

        self.assertFalse(result.detected)
        self.assertIs(result.criteria[6].status, EvaluationStatus.NO_CUMPLE)

    def test_all_required_manual_checks_can_confirm(self) -> None:
        result = evaluate_ct15(
            _bullish_data(),
            prior_trend_valid=True,
            trendline_drawn_correctly=True,
            trendline_broken=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_requires_two_sessions(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_ct15(_bullish_data().iloc[:1])

    def test_previous_highs_create_and_confirm_objective_trendline(self) -> None:
        result = evaluate_ct15(_bullish_data_with_trendline())

        self.assertTrue(result.detected)
        self.assertIs(result.criteria[0].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[1].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[5].status, EvaluationStatus.CUMPLE)
        self.assertTrue(result.required_criteria_satisfied)

    def test_short_history_does_not_invent_trendline(self) -> None:
        result = evaluate_ct15(_bullish_data())

        self.assertIs(result.criteria[1].status, EvaluationStatus.NO_DISPONIBLE)
        self.assertIs(result.criteria[5].status, EvaluationStatus.NO_DISPONIBLE)


if __name__ == "__main__":
    unittest.main()
