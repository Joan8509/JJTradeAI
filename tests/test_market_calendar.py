"""Pruebas del calendario oficial."""

from datetime import date
import unittest

from alpaca_market_data import AlpacaMarketConfig
from market_calendar import AlpacaMarketCalendarProvider, session_close_map


class MarketCalendarTests(unittest.TestCase):
    def test_parses_early_close(self) -> None:
        requests = []
        def transport(request):
            requests.append(request)
            return [{"date": "2026-11-27", "open": "09:30", "close": "13:00"}]
        sessions = AlpacaMarketCalendarProvider(
            AlpacaMarketConfig("key", "secret"), transport=transport
        ).fetch_sessions(date(2026, 11, 27), date(2026, 11, 27))
        self.assertEqual(session_close_map(sessions)[date(2026, 11, 27)].hour, 13)
        self.assertNotIn("secret", requests[0].full_url)

    def test_rejects_inverted_range(self) -> None:
        provider = AlpacaMarketCalendarProvider(
            AlpacaMarketConfig("key", "secret"), transport=lambda request: []
        )
        with self.assertRaisesRegex(ValueError, "invertido"):
            provider.fetch_sessions(date(2026, 2, 1), date(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
