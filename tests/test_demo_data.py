"""Pruebas de la demostración sintética."""

import unittest

from data_quality import evaluate_data_quality
from demo_data import generate_demo_datasets
from indicators import add_bollinger_metrics, add_gap_metrics, calculate_bollinger
from analysis_models import GateStatus


class DemoDataTests(unittest.TestCase):
    def test_demo_has_three_aligned_and_calculable_timeframes(self) -> None:
        datasets = {
            timeframe: add_gap_metrics(add_bollinger_metrics(calculate_bollinger(frame)))
            for timeframe, frame in generate_demo_datasets().items()
        }

        self.assertEqual(set(datasets), {"15m", "1H", "1D"})
        self.assertIs(evaluate_data_quality(datasets).status, GateStatus.APROBADO)


if __name__ == "__main__":
    unittest.main()
