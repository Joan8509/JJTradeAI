"""Pruebas del detector de Salto de Lateralidad en Hora."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.salto_lateralidad_hora import evaluate_salto_lateralidad_hora


def _hourly_frame(
    closes: list[float],
    *,
    ma20: float,
    ma40: float,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": closes,
            "moving_average_20": [ma20] * len(closes),
            "moving_average_40": [ma40] * len(closes),
        }
    )


class SaltoLateralidadHoraTests(unittest.TestCase):
    def test_bullish_lateral_jump_can_be_fully_confirmed(self) -> None:
        closes = [95, 96, 97, 98, 99] + [100, 101] * 5 + [103]
        result = evaluate_salto_lateralidad_hora(
            _hourly_frame(closes, ma20=99.0, ma40=98.0),
            lateral_channel_confirmed=True,
            breakout_or_gap_confirmed=True,
            near_hourly_ma20=True,
            directional_volatility_confirmed=True,
            news_clear=True,
            path_clear=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)
        self.assertEqual(result.strategy_id, "SALTO_LATERALIDAD_HORA_ALCISTA")
        self.assertIs(result.bias, DirectionBias.CALL)

    def test_bearish_lateral_jump_keeps_required_external_reviews(self) -> None:
        closes = [105, 104, 103, 102, 101] + [100, 99] * 5 + [97]
        result = evaluate_salto_lateralidad_hora(
            _hourly_frame(closes, ma20=99.0, ma40=100.0),
            lateral_channel_confirmed=True,
            breakout_or_gap_confirmed=True,
        )

        self.assertFalse(result.detected)
        self.assertFalse(result.required_criteria_satisfied)
        self.assertEqual(result.strategy_id, "SALTO_LATERALIDAD_HORA_BAJISTA")
        self.assertIs(result.bias, DirectionBias.PUT)
        self.assertIs(result.criteria[4].status, EvaluationStatus.NO_DISPONIBLE)

    def test_missing_lateral_review_does_not_detect_setup(self) -> None:
        closes = [95, 96, 97, 98, 99] + [100, 101] * 5 + [103]

        result = evaluate_salto_lateralidad_hora(
            _hourly_frame(closes, ma20=99.0, ma40=98.0),
            breakout_or_gap_confirmed=True,
        )

        self.assertFalse(result.detected)
        self.assertIs(result.criteria[1].status, EvaluationStatus.NO_DISPONIBLE)

    def test_requires_enough_hourly_records(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_salto_lateralidad_hora(
                _hourly_frame([1.0] * 15, ma20=1.0, ma40=1.0)
            )

    def test_channel_break_distance_and_volatility_are_objective(self) -> None:
        closes = [95, 96, 97, 98, 99] + [100.0, 100.2] * 5 + [103.0]
        count = len(closes)
        frame = pd.DataFrame(
            {
                "open": closes[:-1] + [102.5],
                "high": [value + 0.5 for value in closes[:-1]] + [104.0],
                "low": [value - 0.5 for value in closes[:-1]] + [102.0],
                "close": closes,
                "moving_average_20": [100.0] * (count - 1) + [99.0],
                "moving_average_40": [98.0] * count,
                "bollinger_upper_change": [0.0] * (count - 1) + [0.5],
                "bollinger_lower_change": [0.0] * (count - 1) + [-0.5],
            }
        )

        result = evaluate_salto_lateralidad_hora(
            frame, news_clear=True, path_clear=True
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)
        for index in (1, 3, 4, 5):
            self.assertIs(result.criteria[index].status, EvaluationStatus.CUMPLE)


if __name__ == "__main__":
    unittest.main()
