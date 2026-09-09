"""Pruebas de Momentum multitemporal."""

import unittest

import pandas as pd

from analysis_models import DirectionBias
from strategies.momentum import evaluate_momentum


def _frames(*, volatility: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly = pd.DataFrame(
        {
            "close": [120.0],
            "moving_average_20": [110.0],
            "moving_average_40": [105.0],
            "moving_average_100": [100.0],
            "moving_average_200": [95.0],
        }
    )
    daily = pd.DataFrame(
        {
            "close": [120.0],
            "moving_average_20": [110.0],
            "moving_average_40": [105.0],
            "bollinger_mid_slope": [1.0],
            "bollinger_upper_change": [1.0 if volatility else -1.0],
            "bollinger_lower_change": [-1.0 if volatility else 1.0],
        }
    )
    return hourly, daily


def _transition_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    hourly = pd.DataFrame(
        {
            "close": [80.0 - index for index in range(12)] + [120.0, 122.0],
            "moving_average_20": [90.0] * 12 + [110.0, 112.0],
            "moving_average_40": [95.0] * 12 + [105.0, 106.0],
            "moving_average_100": [90.0] * 12 + [100.0, 101.0],
            "moving_average_200": [100.0] * 12 + [95.0, 96.0],
        }
    )
    daily_ma20 = [110.0 - index for index in range(12)] + [100.0, 102.0]
    daily = pd.DataFrame(
        {
            "close": [90.0 - index for index in range(12)] + [120.0, 122.0],
            "moving_average_20": daily_ma20,
            "moving_average_40": [115.0 - index for index in range(12)] + [105.0, 106.0],
            "bollinger_mid_slope": [-1.0] * 12 + [1.0, 1.0],
            "bollinger_upper_change": [0.0] * 12 + [1.0, 1.0],
            "bollinger_lower_change": [0.0] * 12 + [-1.0, -1.0],
        }
    )
    return hourly, daily


class MomentumTests(unittest.TestCase):
    def test_aligned_ma_state_without_history_is_only_a_candidate(self) -> None:
        result = evaluate_momentum(*_frames())

        self.assertFalse(result.detected)
        self.assertIs(result.bias, DirectionBias.CALL)
        self.assertFalse(result.required_criteria_satisfied)

    def test_no_daily_volatility_is_false_momentum(self) -> None:
        result = evaluate_momentum(*_frames(volatility=False))

        self.assertFalse(result.detected)

    def test_manual_history_and_closed_breakouts_can_confirm(self) -> None:
        result = evaluate_momentum(
            *_frames(),
            prolonged_prior_trend=True,
            prior_long_term_structure=True,
            breakouts_confirmed_closed=True,
            path_clear=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_closed_transition_confirms_objective_history(self) -> None:
        result = evaluate_momentum(*_transition_frames(), path_clear=True)
        criteria = {item.criterion_id: item.status.value for item in result.criteria}

        self.assertTrue(result.detected)
        self.assertEqual(criteria["prolonged_prior_trend"], "CUMPLE")
        self.assertEqual(criteria["prior_long_term_structure"], "CUMPLE")
        self.assertEqual(criteria["closed_breakouts"], "CUMPLE")
        self.assertTrue(result.required_criteria_satisfied)

    def test_path_remains_manual_even_with_objective_transition(self) -> None:
        result = evaluate_momentum(*_transition_frames())
        criteria = {item.criterion_id: item.status.value for item in result.criteria}

        self.assertEqual(criteria["clear_path"], "NO_DISPONIBLE")
        self.assertFalse(result.required_criteria_satisfied)


if __name__ == "__main__":
    unittest.main()
