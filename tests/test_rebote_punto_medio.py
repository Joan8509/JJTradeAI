"""Pruebas de Rebote en Punto Medio Diario."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.rebote_punto_medio import evaluate_rebote_punto_medio


def _frames() -> tuple[pd.DataFrame, ...]:
    intraday = pd.DataFrame(
        {"open": [100.4], "high": [101.0], "low": [99.8], "close": [100.6]}
    )
    hourly = pd.DataFrame(
        {
            "open": [100.2],
            "close": [101.2],
            "bollinger_mid_slope": [-0.3],
        }
    )
    daily = pd.DataFrame(
        {"bollinger_mid": [100.0], "bollinger_mid_slope": [0.5]}
    )
    return intraday, hourly, daily


def _frames_with_approach() -> tuple[pd.DataFrame, ...]:
    intraday, hourly, _ = _frames()
    daily = pd.DataFrame(
        {
            "close": [106.0, 103.0, 101.0],
            "bollinger_mid": [100.0, 100.0, 100.0],
            "bollinger_mid_slope": [0.5, 0.5, 0.5],
        }
    )
    return intraday, hourly, daily


class MidpointBounceTests(unittest.TestCase):
    def test_level_contact_without_confirmation_is_only_a_candidate(self) -> None:
        result = evaluate_rebote_punto_medio(*_frames())

        self.assertFalse(result.detected)
        self.assertEqual(result.strategy_id, "REBOTE_PUNTO_MEDIO_ALCISTA")
        self.assertIs(result.bias, DirectionBias.CALL)
        self.assertFalse(result.required_criteria_satisfied)

    def test_closed_hour_and_manual_reviews_can_confirm(self) -> None:
        result = evaluate_rebote_punto_medio(
            *_frames(),
            multi_day_approach_confirmed=True,
            hourly_candle_closed=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_15m_close_can_infer_midpoint_respect(self) -> None:
        result = evaluate_rebote_punto_medio(*_frames())

        self.assertIs(result.criteria[4].status, EvaluationStatus.CUMPLE)

    def test_15m_close_crossing_midpoint_fails_respect(self) -> None:
        intraday, hourly, daily = _frames()
        intraday.loc[0, "close"] = 99.7

        result = evaluate_rebote_punto_medio(intraday, hourly, daily)

        self.assertIs(result.criteria[4].status, EvaluationStatus.NO_CUMPLE)

    def test_price_far_from_daily_midpoint_is_not_detected(self) -> None:
        intraday, hourly, daily = _frames()
        intraday.loc[0, ["low", "high"]] = [105.0, 106.0]

        result = evaluate_rebote_punto_medio(intraday, hourly, daily)

        self.assertFalse(result.detected)

    def test_three_daily_closes_confirm_objective_approach(self) -> None:
        result = evaluate_rebote_punto_medio(
            *_frames_with_approach(),
            hourly_candle_closed=True,
        )

        self.assertIs(result.criteria[2].status, EvaluationStatus.CUMPLE)
        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_non_decreasing_distance_rejects_approach(self) -> None:
        intraday, hourly, daily = _frames_with_approach()
        daily["close"] = [103.0, 106.0, 101.0]

        result = evaluate_rebote_punto_medio(
            intraday, hourly, daily, hourly_candle_closed=True
        )

        self.assertIs(result.criteria[2].status, EvaluationStatus.NO_CUMPLE)
        self.assertFalse(result.required_criteria_satisfied)


if __name__ == "__main__":
    unittest.main()
