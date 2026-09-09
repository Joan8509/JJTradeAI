"""Pruebas del detector conservador de Primer Salto."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.primer_salto import evaluate_first_jump_setup


class FirstJumpTests(unittest.TestCase):
    def test_bullish_gap_held_without_confirmations_is_only_a_candidate(self) -> None:
        data = pd.DataFrame({"open": [99.0, 102.0], "close": [100.0, 103.0]})

        result = evaluate_first_jump_setup(data, session_closed=True)

        self.assertFalse(result.detected)
        self.assertEqual(result.strategy_id, "PRIMER_SALTO_RESPETADO_ALCISTA")
        self.assertIs(result.bias, DirectionBias.CALL)
        self.assertFalse(result.required_criteria_satisfied)

    def test_bearish_gap_erased_at_close_is_not_detected(self) -> None:
        data = pd.DataFrame({"open": [101.0, 98.0], "close": [100.0, 101.0]})

        result = evaluate_first_jump_setup(data, session_closed=True)

        self.assertFalse(result.detected)
        self.assertIs(result.criteria[1].status, EvaluationStatus.NO_CUMPLE)

    def test_open_session_never_confirms_jump(self) -> None:
        data = pd.DataFrame({"open": [99.0, 102.0], "close": [100.0, 103.0]})

        result = evaluate_first_jump_setup(data)

        self.assertFalse(result.detected)
        self.assertIs(result.criteria[1].status, EvaluationStatus.REQUIERE_REVISION)

    def test_complete_external_checks_can_satisfy_required_criteria(self) -> None:
        data = pd.DataFrame({"open": [99.0, 102.0], "close": [100.0, 103.0]})

        result = evaluate_first_jump_setup(
            data,
            session_closed=True,
            prior_trend_confirmed=True,
            trendline_broken=True,
            hourly_confirmation_closed=True,
            news_clear=True,
            path_clear=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_requires_two_daily_sessions(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_first_jump_setup(pd.DataFrame({"open": [1.0], "close": [1.0]}))

    def test_five_day_trend_line_and_hour_confirm_automatically(self) -> None:
        daily = pd.DataFrame(
            {
                "open": [105.5, 104.5, 103.5, 102.5, 101.5, 103.0],
                "high": [106.0, 105.0, 104.0, 103.0, 102.0, 105.0],
                "low": [104.0, 103.0, 102.0, 101.0, 100.0, 102.0],
                "close": [105.0, 104.0, 103.0, 102.0, 101.0, 104.0],
            }
        )
        hourly = pd.DataFrame({"open": [102.5], "close": [104.0]})

        result = evaluate_first_jump_setup(
            daily,
            hourly=hourly,
            session_closed=True,
            news_clear=True,
            path_clear=True,
        )

        self.assertTrue(result.detected)
        self.assertIs(result.criteria[2].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[3].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[4].status, EvaluationStatus.CUMPLE)
        self.assertTrue(result.required_criteria_satisfied)


if __name__ == "__main__":
    unittest.main()
