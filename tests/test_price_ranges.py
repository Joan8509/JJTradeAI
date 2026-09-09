from datetime import date
import unittest

import pandas as pd

from price_ranges import calculate_price_range, load_option_price_ranges


class PriceRangeTests(unittest.TestCase):
    def test_loads_complete_option_reference_list(self) -> None:
        ranges = load_option_price_ranges()
        self.assertEqual(len(ranges), 53)
        self.assertEqual(ranges["SPY"]["optimal_low"], 30.0)
        self.assertEqual(ranges["SPY"]["optimal_high"], 45.0)
        self.assertEqual(ranges["MU"]["maximum"], 650.0)

    def test_calculates_dynamic_levels_from_daily_sessions(self) -> None:
        rows = []
        sessions = pd.bdate_range("2026-07-20", periods=21, tz="America/New_York")
        for index, session in enumerate(sessions):
            base = 100.0 + index
            rows.append({
                "date": session.replace(hour=9, minute=30).tz_convert("UTC"),
                "open": base,
                "high": base + 2.0,
                "low": base - 1.0,
                "close": base + 1.0,
                "volume": 1000,
            })
        result = calculate_price_range(
            pd.DataFrame(rows), current_market_date=date(2026, 8, 17)
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["current"], 121.0)
        self.assertEqual(result["support"], 100.0)
        self.assertEqual(result["resistance"], 122.0)
        self.assertEqual(result["position"], "Cerca de la resistencia")
        self.assertGreater(result["expected_high"], result["expected_low"])


if __name__ == "__main__":
    unittest.main()
