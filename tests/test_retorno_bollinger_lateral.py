"""Pruebas de Retorno a Bollinger desde lateralidad."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, EvaluationStatus
from strategies.retorno_bollinger_lateral import (
    evaluate_retorno_bollinger_lateral,
)


def _data(*, closing: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-06-23 15:45", "2026-06-24 09:30"],
            "open": [100.0, 94.0],
            "close": [100.0, 96.0],
            "bollinger_upper": [102.0, 101.5],
            "bollinger_lower": [98.0, 98.5],
            "bollinger_upper_change": [0.0, -0.5 if closing else 0.5],
            "bollinger_lower_change": [0.0, 0.5 if closing else -0.5],
        }
    )


def _data_with_history() -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2026-05-01")
    for index in range(21):
        day = start + pd.Timedelta(days=index)
        rows.append(
            {
                "date": day.replace(hour=15, minute=45), "open": 100.0,
                "close": 100.0, "bollinger_mid": 100.0,
                "bollinger_upper": 102.0, "bollinger_lower": 98.0,
                "bollinger_upper_change": 0.0, "bollinger_lower_change": 0.0,
            }
        )
    previous_day = start + pd.Timedelta(days=21)
    for index in range(8):
        rows.append(
            {
                "date": previous_day.replace(hour=10 + index), "open": 100.0,
                "close": 100.0, "bollinger_mid": 100.0,
                "bollinger_upper": 100.5, "bollinger_lower": 99.5,
                "bollinger_upper_change": 0.0, "bollinger_lower_change": 0.0,
            }
        )
    rows.append(
        {
            "date": (start + pd.Timedelta(days=22)).replace(hour=9, minute=30),
            "open": 94.0, "close": 96.0, "bollinger_mid": 100.0,
            "bollinger_upper": 100.2, "bollinger_lower": 99.8,
            "bollinger_upper_change": -0.3, "bollinger_lower_change": 0.3,
        }
    )
    return pd.DataFrame(rows)


def _first_five_minutes() -> pd.DataFrame:
    start = pd.Timestamp("2026-05-23 09:30")
    closes = [94.1, 94.3, 94.6, 94.8, 95.0]
    return pd.DataFrame(
        {
            "date": [start + pd.Timedelta(minutes=index) for index in range(5)],
            "open": [94.0] + closes[:-1],
            "close": closes,
        }
    )


class LateralBollingerReturnTests(unittest.TestCase):
    def test_gap_below_band_without_context_is_only_a_candidate(self) -> None:
        result = evaluate_retorno_bollinger_lateral(_data())

        self.assertFalse(result.detected)
        self.assertIs(result.bias, DirectionBias.CALL)
        self.assertFalse(result.required_criteria_satisfied)

    def test_all_reviews_and_closing_bands_can_confirm(self) -> None:
        result = evaluate_retorno_bollinger_lateral(
            _data(),
            prior_midpoint_lateral=True,
            prior_volatility_closed=True,
            gap_exceptional_for_symbol=True,
            reversal_within_first_minutes=True,
        )

        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)

    def test_bands_continuing_to_open_do_not_confirm(self) -> None:
        result = evaluate_retorno_bollinger_lateral(
            _data(closing=False),
            prior_midpoint_lateral=True,
            prior_volatility_closed=True,
            gap_exceptional_for_symbol=True,
            reversal_within_first_minutes=True,
        )

        self.assertFalse(result.required_criteria_satisfied)

    def test_history_confirms_lateral_compressed_exceptional_setup(self) -> None:
        result = evaluate_retorno_bollinger_lateral(
            _data_with_history(), minute_1m=_first_five_minutes()
        )

        self.assertIs(result.criteria[0].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[1].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[3].status, EvaluationStatus.CUMPLE)
        self.assertIs(result.criteria[4].status, EvaluationStatus.CUMPLE)
        self.assertTrue(result.detected)
        self.assertTrue(result.required_criteria_satisfied)


if __name__ == "__main__":
    unittest.main()
