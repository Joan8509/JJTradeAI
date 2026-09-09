"""Pruebas del panorama sin pesos artificiales."""

import unittest

import pandas as pd

from analysis_models import DirectionBias, GateStatus
from panorama_engine import MarketDirection, evaluate_panorama


def _frame(close: float, ma20: float, ma40: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": [close],
            "moving_average_20": [ma20],
            "moving_average_40": [ma40],
            "bollinger_upper": [120.0],
            "bollinger_lower": [80.0],
            "bollinger_both_expanding": [True],
        }
    )


class PanoramaEngineTests(unittest.TestCase):
    def test_complete_review_can_approve_without_assigning_weights(self) -> None:
        datasets = {key: _frame(110, 105, 100) for key in ("15m", "1H", "1D")}

        result = evaluate_panorama(
            datasets,
            intended_bias=DirectionBias.CALL,
            path_clear=True,
            news_clear=True,
            human_approval=True,
        )

        self.assertIs(result.status, GateStatus.APROBADO)
        self.assertIs(result.dominant_direction, MarketDirection.ALCISTA)

    def test_missing_timeframe_requires_review_even_with_manual_yes(self) -> None:
        result = evaluate_panorama(
            {"1D": _frame(110, 105, 100)},
            path_clear=True,
            news_clear=True,
            human_approval=True,
        )

        self.assertIs(result.status, GateStatus.REQUIERE_REVISION)

    def test_blocked_path_rejects_panorama(self) -> None:
        datasets = {key: _frame(110, 105, 100) for key in ("15m", "1H", "1D")}

        result = evaluate_panorama(datasets, path_clear=False)

        self.assertIs(result.status, GateStatus.RECHAZADO)

    def test_conflicting_higher_timeframe_is_reported(self) -> None:
        datasets = {
            "15m": _frame(110, 105, 100),
            "1H": _frame(90, 95, 100),
            "1D": _frame(90, 95, 100),
        }

        result = evaluate_panorama(datasets, intended_bias=DirectionBias.CALL)

        self.assertTrue(any("1D" in item for item in result.conflicts))

    def test_directional_conflicts_prevent_approval(self) -> None:
        datasets = {
            "15m": _frame(110, 105, 100),
            "1H": _frame(90, 95, 100),
            "1D": _frame(90, 95, 100),
        }

        result = evaluate_panorama(
            datasets,
            intended_bias=DirectionBias.CALL,
            path_clear=True,
            news_clear=True,
            human_approval=True,
        )

        self.assertIs(result.status, GateStatus.REQUIERE_REVISION)


if __name__ == "__main__":
    unittest.main()
