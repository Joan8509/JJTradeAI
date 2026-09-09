"""Pruebas de las mediciones técnicas sin lógica estratégica."""

import unittest

import pandas as pd

from indicators import add_bollinger_metrics, add_gap_metrics, calculate_bollinger


class IndicatorTests(unittest.TestCase):
    def test_bollinger_uses_explicit_population_deviation(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        result = calculate_bollinger(df, period=3, std_dev=2, ddof=0)
        self.assertAlmostEqual(result.iloc[-1]["bollinger_mid"], 2.0)
        self.assertAlmostEqual(result.iloc[-1]["bollinger_upper"], 3.632993, places=6)

    def test_bollinger_metrics_detect_simultaneous_expansion(self) -> None:
        df = pd.DataFrame(
            {
                "bollinger_mid": [10.0, 10.0],
                "bollinger_upper": [11.0, 12.0],
                "bollinger_lower": [9.0, 8.0],
            }
        )
        result = add_bollinger_metrics(df)
        self.assertTrue(result.iloc[-1]["bollinger_both_expanding"])
        self.assertEqual(result.iloc[-1]["bollinger_width_pct"], 40.0)

    def test_gap_metrics_compare_open_with_previous_close(self) -> None:
        df = pd.DataFrame({"open": [10.0, 12.0], "close": [10.0, 11.0]})
        result = add_gap_metrics(df)
        self.assertEqual(result.iloc[-1]["gap"], 2.0)
        self.assertEqual(result.iloc[-1]["gap_pct"], 20.0)

    def test_percentage_metrics_use_nan_for_zero_denominator(self) -> None:
        bollinger = pd.DataFrame(
            {
                "bollinger_mid": [0.0],
                "bollinger_upper": [1.0],
                "bollinger_lower": [-1.0],
            }
        )
        gaps = pd.DataFrame({"open": [10.0, 12.0], "close": [0.0, 11.0]})

        bollinger_result = add_bollinger_metrics(bollinger)
        gap_result = add_gap_metrics(gaps)

        self.assertTrue(pd.isna(bollinger_result.iloc[0]["bollinger_width_pct"]))
        self.assertTrue(pd.isna(gap_result.iloc[-1]["gap_pct"]))


if __name__ == "__main__":
    unittest.main()
