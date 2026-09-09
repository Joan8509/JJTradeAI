"""Pruebas del contexto objetivo de benchmarks."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from market_context import build_market_context
from market_calendar import MarketSession, MarketSessionRepository
from market_store import MarketBarStore


START = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)


def minutes(rising: bool) -> pd.DataFrame:
    rows = []
    for index in range(30):
        price = 100 + index if rising else 100 - index / 10
        rows.append({"date": START + timedelta(minutes=index), "open": price, "high": price + 1, "low": price - 1, "close": price + 0.5, "volume": 10})
    return pd.DataFrame(rows)


class MarketContextTests(unittest.TestCase):
    def test_official_session_repository_preserves_early_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = MarketSessionRepository(Path(directory) / "market.db")
            session_date = START.date()
            session = MarketSession(session_date, START, START + timedelta(hours=3, minutes=30))
            self.assertEqual(repository.upsert((session,)), 1)
            saved = repository.session(session_date)
            self.assertEqual(saved.closes_at, session.closes_at)

    def test_reports_direction_and_missing_benchmark_without_approving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "market.db")
            store.upsert_frame(minutes(True), symbol="SPY", provider="ALPACA", feed="iex")

            result = build_market_context(
                store,
                ("SPY", "QQQ"),
                provider="ALPACA",
                feed="iex",
                trigger_timestamp=START + timedelta(minutes=29),
            )

            self.assertEqual(result["status"], "REQUIERE_REVISION")
            self.assertEqual(result["bullish_count"], 1)
            self.assertEqual(result["benchmarks"][0]["direction"], "ALCISTA")
            self.assertEqual(result["benchmarks"][1]["direction"], "NO_DISPONIBLE")


if __name__ == "__main__":
    unittest.main()
