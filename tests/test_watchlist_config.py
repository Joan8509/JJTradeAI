"""Pruebas de la lista de vigilancia compartida."""

import unittest

from live_strategy_service import build_parser
from watchlist_config import DEFAULT_BENCHMARKS_TEXT, DEFAULT_SYMBOLS_TEXT, WATCHLIST


class WatchlistConfigTests(unittest.TestCase):
    def test_requested_symbols_are_normalized_and_unique(self) -> None:
        self.assertEqual(len(WATCHLIST["symbols"]), 16)
        self.assertEqual(len(set(WATCHLIST["symbols"])), 16)
        self.assertEqual(
            set(WATCHLIST["symbols"]),
            {"AAPL", "NVDA", "TSLA", "AMD", "META", "MSFT", "BABA", "SPY", "QQQ", "IWM", "DIA", "MU", "NIO", "GLD", "AMZN", "NFLX"},
        )

    def test_scanner_defaults_use_shared_watchlist_and_benchmarks(self) -> None:
        args = build_parser().parse_args([])

        self.assertEqual(args.symbols, DEFAULT_SYMBOLS_TEXT)
        self.assertEqual(args.benchmarks, DEFAULT_BENCHMARKS_TEXT)
        self.assertEqual(WATCHLIST["benchmarks"], ("SPY", "QQQ", "IWM", "DIA"))


if __name__ == "__main__":
    unittest.main()
