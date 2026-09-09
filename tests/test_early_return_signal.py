"""Pruebas de seguridad de la prealerta aislada de cinco minutos."""

from datetime import datetime, timezone
import unittest

import pandas as pd

from early_return_signal import build_early_return_report, is_opening_five_minute_close


class EarlyReturnSignalTests(unittest.TestCase):
    def test_only_new_york_0934_closes_early_window(self) -> None:
        self.assertTrue(is_opening_five_minute_close(datetime(2026, 7, 20, 13, 34, tzinfo=timezone.utc)))
        self.assertFalse(is_opening_five_minute_close(datetime(2026, 7, 20, 13, 35, tzinfo=timezone.utc)))

    def test_naive_timestamp_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            is_opening_five_minute_close(datetime(2026, 7, 20, 9, 34))

    def test_short_history_cannot_create_prealert(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2026-07-20 13:30", periods=5, freq="min", tz="UTC"),
                "open": [100.0] * 5,
                "high": [100.1] * 5,
                "low": [99.9] * 5,
                "close": [100.0] * 5,
                "volume": [10] * 5,
            }
        )

        with self.assertRaisesRegex(ValueError, "dos sesiones"):
            build_early_return_report(frame, symbol="SPY")


if __name__ == "__main__":
    unittest.main()
