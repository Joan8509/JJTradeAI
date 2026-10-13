"""Pruebas de la lista de vigilancia compartida."""

import unittest

from live_strategy_service import build_parser
from watchlist_config import DEFAULT_BENCHMARKS_TEXT, DEFAULT_SYMBOLS_TEXT, WATCHLIST
from price_ranges import load_option_price_ranges


class WatchlistConfigTests(unittest.TestCase):
    def test_requested_symbols_are_normalized_and_unique(self) -> None:
        self.assertEqual(len(WATCHLIST["symbols"]), 52)
        self.assertEqual(len(set(WATCHLIST["symbols"])), 52)
        self.assertEqual(
            set(WATCHLIST["symbols"]),
            set(load_option_price_ranges()) - {"SPX"},
        )

    def test_scanner_defaults_use_shared_watchlist_and_benchmarks(self) -> None:
        args = build_parser().parse_args([])

        self.assertEqual(args.symbols, DEFAULT_SYMBOLS_TEXT)
        self.assertEqual(args.benchmarks, DEFAULT_BENCHMARKS_TEXT)
        self.assertEqual(WATCHLIST["benchmarks"], ("SPY", "QQQ", "IWM", "DIA"))


if __name__ == "__main__":
    unittest.main()
