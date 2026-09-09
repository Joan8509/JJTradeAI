"""Pruebas de Cambio de Tendencia en Hora."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.cambio_tendencia_hora import evaluate_cambio_tendencia_hora


class HourlyTrendChangeTests(unittest.TestCase):
    def test_midpoint_cross_with_only_line_break_is_not_detected(self) -> None:
        frame = pd.DataFrame({"close": [95.0, 102.0], "bollinger_mid": [100.0, 100.0]})
        result = evaluate_cambio_tendencia_hora(frame, trendline_broken=True)

        self.assertFalse(result.detected)
        self.assertIs(result.bias, DirectionBias.CALL)
        self.assertFalse(result.required_criteria_satisfied)

    def test_gap_confirmation_can_replace_closed_hour(self) -> None:
        frame = pd.DataFrame({"close": [95.0, 102.0], "bollinger_mid": [100.0, 100.0]})
        result = evaluate_cambio_tendencia_hora(
            frame,
            prior_trend_two_days=True,
            trendline_drawn_correctly=True,
            trendline_broken=True,
            gap_broke_both_levels=True,
            intraday_15m_aligned=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_cross_without_trendline_break_is_not_detected(self) -> None:
        frame = pd.DataFrame({"close": [95.0, 102.0], "bollinger_mid": [100.0, 100.0]})
        result = evaluate_cambio_tendencia_hora(frame, trendline_broken=False)

        self.assertFalse(result.detected)

    def test_two_day_history_and_15m_confirm_objective_change(self) -> None:
        hourly = pd.DataFrame(
            {
                "open": [100.3 - index * 0.5 for index in range(13)] + [102.0],
                "high": [100.8 - index * 0.5 for index in range(13)] + [104.0],
                "low": [99.2 - index * 0.5 for index in range(13)] + [101.5],
                "close": [100.0 - index * 0.5 for index in range(13)] + [103.0],
                "bollinger_mid": [101.0 - index * 0.2 for index in range(13)] + [98.0],
            }
        )
        intraday = pd.DataFrame(
            {"close": [103.0], "bollinger_mid": [101.0], "bollinger_mid_slope": [0.4]}
        )

        result = evaluate_cambio_tendencia_hora(
            hourly, intraday_15m=intraday, hourly_candle_closed=True
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)
        self.assertTrue(all(item.status is EvaluationStatus.CUMPLE for item in result.criteria))


if __name__ == "__main__":
    unittest.main()
