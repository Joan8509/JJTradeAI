"""Pruebas de la evidencia objetiva del detector Efecto Imán."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.efecto_iman import evaluate_efecto_iman


def _frames(*, second_candle: bool = True) -> tuple[pd.DataFrame, ...]:
    intraday = pd.DataFrame(
        {
            "date": ["2026-06-24 09:30", "2026-06-24 09:45"],
            "high": [111.0, 110.0],
            "low": [109.0, 108.0],
            "bollinger_upper": [108.0, 108.5],
            "bollinger_lower": [92.0, 92.5],
        }
    )
    if not second_candle:
        intraday = intraday.iloc[:1]
    hourly = pd.DataFrame(
        {
            "date": ["2026-06-24 09:30"],
            "close": [109.0],
            "moving_average_20": [100.0],
            "moving_average_40": [95.0],
        }
    )
    daily = pd.DataFrame(
        {"date": ["2026-06-23", "2026-06-24"], "open": [99.0, 108.0], "close": [100.0, 109.0]}
    )
    return intraday, hourly, daily


def _frames_with_two_hourly_sessions() -> tuple[pd.DataFrame, ...]:
    intraday, hourly, daily = _frames()
    hourly = pd.DataFrame(
        {
            "date": ["2026-06-23 09:30", "2026-06-24 09:30"],
            "close": [101.0, 109.0],
            "moving_average_20": [98.0, 100.0],
            "moving_average_40": [95.0, 96.0],
        }
    )
    return intraday, hourly, daily


def _frames_with_hourly_path() -> tuple[pd.DataFrame, ...]:
    intraday, hourly, daily = _frames_with_two_hourly_sessions()
    hourly["moving_average_100"] = [92.0, 93.0]
    hourly["moving_average_200"] = [88.0, 89.0]
    return intraday, hourly, daily


def _frames_with_distance_history(*, current_close: float) -> tuple[pd.DataFrame, ...]:
    intraday, _, daily = _frames_with_two_hourly_sessions()
    dates = pd.date_range(end="2026-06-23 09:30", periods=60, freq="D")
    historical_distances = [(index % 6) + 1 for index in range(60)]
    hourly = pd.DataFrame(
        {
            "date": list(dates) + [pd.Timestamp("2026-06-24 09:30")],
            "close": [100.0 + value for value in historical_distances]
            + [current_close],
            "moving_average_20": [100.0] * 61,
            "moving_average_40": [95.0] * 61,
        }
    )
    return intraday, hourly, daily


class MagnetEffectTests(unittest.TestCase):
    def test_objective_bullish_trend_setup_has_put_bias(self) -> None:
        result = evaluate_efecto_iman(*_frames())

        self.assertFalse(result.detected)
        self.assertEqual(result.strategy_id, "EFECTO_IMAN_TENDENCIA_ALCISTA")
        self.assertIs(result.bias, DirectionBias.PUT)
        self.assertFalse(result.required_criteria_satisfied)

    def test_touching_upper_band_fails_complete_exposure(self) -> None:
        intraday, hourly, daily = _frames()
        intraday.loc[0, "low"] = intraday.loc[0, "bollinger_upper"]

        result = evaluate_efecto_iman(intraday, hourly, daily)

        self.assertFalse(result.detected)
        self.assertIs(result.criteria[4].status, EvaluationStatus.NO_CUMPLE)

    def test_second_candle_must_have_started(self) -> None:
        result = evaluate_efecto_iman(*_frames(second_candle=False))

        self.assertFalse(result.detected)
        self.assertIs(result.criteria[5].status, EvaluationStatus.REQUIERE_REVISION)

    def test_clear_hourly_trend_is_inferred_from_two_sessions(self) -> None:
        result = evaluate_efecto_iman(*_frames_with_two_hourly_sessions())

        self.assertIs(result.criteria[2].status, EvaluationStatus.CUMPLE)

    def test_hourly_trend_fails_when_price_is_not_aligned(self) -> None:
        intraday, hourly, daily = _frames_with_two_hourly_sessions()
        hourly.loc[0, "close"] = 97.0

        result = evaluate_efecto_iman(intraday, hourly, daily)

        self.assertIs(result.criteria[2].status, EvaluationStatus.NO_CUMPLE)

    def test_path_to_hourly_ma20_is_inferred_when_averages_are_available(self) -> None:
        result = evaluate_efecto_iman(*_frames_with_hourly_path())

        self.assertIs(result.criteria[7].status, EvaluationStatus.CUMPLE)

    def test_path_to_hourly_ma20_fails_when_average_blocks_retrace(self) -> None:
        intraday, hourly, daily = _frames_with_hourly_path()
        hourly.loc[1, "moving_average_100"] = 105.0

        result = evaluate_efecto_iman(intraday, hourly, daily)

        self.assertIs(result.criteria[7].status, EvaluationStatus.NO_CUMPLE)

    def test_abnormal_distance_uses_symbol_specific_ninetieth_percentile(self) -> None:
        result = evaluate_efecto_iman(
            *_frames_with_distance_history(current_close=115.0)
        )

        self.assertIs(result.criteria[3].status, EvaluationStatus.CUMPLE)
        self.assertIn("percentil 90", result.criteria[3].detail)
        self.assertIn("60 sesiones", result.criteria[3].detail)

    def test_normal_distance_fails_adaptive_threshold(self) -> None:
        result = evaluate_efecto_iman(
            *_frames_with_distance_history(current_close=102.0)
        )

        self.assertIs(result.criteria[3].status, EvaluationStatus.NO_CUMPLE)

    def test_adaptive_distance_requires_twenty_prior_sessions(self) -> None:
        result = evaluate_efecto_iman(*_frames_with_two_hourly_sessions())

        self.assertIs(result.criteria[3].status, EvaluationStatus.NO_DISPONIBLE)
        self.assertIn("sesiones minimas", result.criteria[3].detail)

    def test_all_external_reviews_can_complete_requirements(self) -> None:
        result = evaluate_efecto_iman(
            *_frames(),
            clear_hourly_trend=True,
            abnormal_gap=True,
            worden_volume_crossed=True,
            path_to_hourly_ma20_clear=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)


if __name__ == "__main__":
    unittest.main()
