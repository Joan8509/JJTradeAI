"""Pruebas de persistencia y continuidad del feed de mercado."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from live_market import MarketBar
from market_store import MarketBarStore, MarketContinuityService, find_internal_minute_gaps


START = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)


def frame_at(offsets: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": START + timedelta(minutes=offset),
                "open": 100 + offset,
                "high": 101 + offset,
                "low": 99 + offset,
                "close": 100.5 + offset,
                "volume": 10,
            }
            for offset in offsets
        ]
    )


class FakeProvider:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls = []

    def fetch_minute_bars(self, symbol, *, start, end):
        self.calls.append((symbol, start, end))
        return self.frame


class MarketStoreTests(unittest.TestCase):
    def test_upsert_is_idempotent_and_accepts_correction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "market.db")
            store.upsert_frame(frame_at([0, 1]), symbol="spy", provider="alpaca", feed="iex")
            corrected = frame_at([1])
            corrected.loc[0, "close"] = 777
            corrected.loc[0, "high"] = 777
            store.upsert_frame(corrected, symbol="SPY", provider="ALPACA", feed="iex")

            result = store.load_frame(symbol="SPY", provider="ALPACA", feed="iex")

            self.assertEqual(len(result), 2)
            self.assertEqual(result.iloc[-1]["close"], 777)

    def test_feed_and_provider_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "market.db")
            store.upsert_frame(frame_at([0]), symbol="SPY", provider="ALPACA", feed="iex")

            result = store.load_frame(symbol="SPY", provider="ALPACA", feed="sip")

            self.assertTrue(result.empty)

    def test_upsert_single_stream_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "market.db")
            store.upsert_bar(
                MarketBar("SPY", START, 1, 2, 1, 1.5, 10),
                provider="ALPACA",
                feed="iex",
            )

            self.assertEqual(
                store.latest_timestamp(symbol="SPY", provider="ALPACA", feed="iex"),
                START,
            )

    def test_detects_internal_gap_but_not_overnight(self) -> None:
        first_session = frame_at([0, 2])
        next_session = frame_at([24 * 60, 24 * 60 + 1])

        result = find_internal_minute_gaps(pd.concat([first_session, next_session]))

        self.assertEqual(result, (START + timedelta(minutes=1),))

    def test_recovery_begins_after_latest_persisted_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "market.db")
            store.upsert_frame(frame_at([0]), symbol="SPY", provider="ALPACA", feed="iex")
            provider = FakeProvider(frame_at([1, 2]))
            service = MarketContinuityService(
                store, provider, provider_name="ALPACA", feed="iex"
            )

            inserted = service.recover("SPY", end=START + timedelta(minutes=2))

            self.assertEqual(inserted, 2)
            self.assertEqual(provider.calls[0][1], START + timedelta(minutes=1))
            self.assertEqual(service.gaps("SPY"), ())

    def test_live_ingestion_announces_only_closed_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "market.db")
            service = MarketContinuityService(
                store, FakeProvider(frame_at([0])), provider_name="ALPACA", feed="iex"
            )
            regular = service.ingest_live_bar(
                MarketBar("SPY", START, 1, 2, 1, 1.5, 10)
            )
            closing = service.ingest_live_bar(
                MarketBar("SPY", START + timedelta(minutes=14), 1, 2, 1, 1.5, 10)
            )

            self.assertFalse(regular.closes_15m)
            self.assertTrue(closing.closes_15m)

    def test_live_ingestion_rejects_open_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = MarketContinuityService(
                MarketBarStore(Path(directory) / "market.db"),
                FakeProvider(frame_at([0])),
                provider_name="ALPACA",
                feed="iex",
            )

            with self.assertRaisesRegex(ValueError, "abiertas"):
                service.ingest_live_bar(
                    MarketBar("SPY", START, 1, 2, 1, 1.5, 10, complete=False)
                )


if __name__ == "__main__":
    unittest.main()
