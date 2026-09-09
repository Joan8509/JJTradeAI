"""Pruebas de reconciliación entre WebSocket persistido y REST."""

from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from market_reconciliation import MarketDataReconciler, MarketReconciliationRepository, compare_minute_frames
from pathlib import Path
import tempfile


START = datetime(2026, 7, 22, 13, 30, tzinfo=timezone.utc)


def bars() -> pd.DataFrame:
    return pd.DataFrame([
        {"date": START + timedelta(minutes=index), "open": 100 + index, "high": 101 + index, "low": 99 + index, "close": 100.5 + index, "volume": 1000 + index}
        for index in range(15)
    ])


class MarketReconciliationTests(unittest.TestCase):
    def test_equal_frames_are_approved(self) -> None:
        result = compare_minute_frames(bars(), bars(), start=START, end=START + timedelta(minutes=14))
        self.assertEqual(result["status"], "APROBADO")
        self.assertEqual(result["compared_bar_count"], 15)

    def test_price_difference_is_rejected_and_explained(self) -> None:
        remote = bars()
        remote.loc[14, "close"] += 0.01
        result = compare_minute_frames(bars(), remote, start=START, end=START + timedelta(minutes=14))
        self.assertEqual(result["status"], "RECHAZADO")
        self.assertEqual(result["difference_count"], 1)
        self.assertEqual(result["differences"][0]["field"], "close")

    def test_missing_rest_bar_is_rejected(self) -> None:
        result = compare_minute_frames(bars(), bars().iloc[:-1], start=START, end=START + timedelta(minutes=14))
        self.assertEqual(result["status"], "RECHAZADO")
        self.assertEqual(result["differences"][0]["field"], "bar")

    def test_same_missing_minute_in_both_sources_is_agreement(self) -> None:
        local = bars().iloc[[0, 2]].copy()
        remote = bars().iloc[[0, 2]].copy()

        result = compare_minute_frames(
            local, remote, start=START, end=START + timedelta(minutes=2)
        )

        self.assertEqual(result["status"], "APROBADO")
        self.assertEqual(result["difference_count"], 0)

    def test_rest_failure_is_unavailable_not_approved(self) -> None:
        class FailedProvider:
            def fetch_minute_bars(self, symbol, *, start, end):
                raise RuntimeError("sin conexión")

        result = MarketDataReconciler(FailedProvider()).reconcile(
            "SPY", start=START, end=START + timedelta(minutes=14), local=bars()
        )
        self.assertEqual(result["status"], "NO_DISPONIBLE")

    def test_rest_failure_detail_is_sanitized(self) -> None:
        class FailedProvider:
            def fetch_minute_bars(self, symbol, *, start, end):
                raise RuntimeError(
                    "token=must-not-persist Bearer-abcdefghijklmnopqrstuvwxyz"
                )

        result = MarketDataReconciler(FailedProvider()).reconcile(
            "SPY",
            start=START,
            end=START + timedelta(minutes=14),
            local=bars(),
        )

        self.assertEqual(result["status"], "NO_DISPONIBLE")
        self.assertNotIn("must-not-persist", result["detail"])
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", result["detail"])

    def test_retries_until_rest_publishes_complete_block(self) -> None:
        class DelayedProvider:
            def __init__(self):
                self.calls = 0

            def fetch_minute_bars(self, symbol, *, start, end):
                self.calls += 1
                return bars().iloc[:-1] if self.calls == 1 else bars()

        provider = DelayedProvider()
        waits = []
        result = MarketDataReconciler(
            provider, attempts=2, retry_delay=0.25, sleeper=waits.append
        ).reconcile("SPY", start=START, end=START + timedelta(minutes=14), local=bars())
        self.assertEqual(result["status"], "APROBADO")
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(waits, [0.25])

    def test_repository_upserts_same_trigger_and_preserves_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = MarketReconciliationRepository(Path(directory) / "market.db")
            first = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START,
                payload={"status": "RECHAZADO", "difference_count": 1},
            )
            second = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START,
                payload={"status": "APROBADO", "difference_count": 0},
            )
            self.assertEqual(first, second)
            history = repository.recent()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "APROBADO")

    def test_repository_returns_latest_record_per_requested_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = MarketReconciliationRepository(Path(directory) / "market.db")
            for symbol, status, minute in (
                ("SPY", "RECHAZADO", 0), ("QQQ", "RECHAZADO", 1), ("SPY", "APROBADO", 2)
            ):
                repository.record(
                    provider="ALPACA", feed="iex", symbol=symbol,
                    trigger_timestamp=START + timedelta(minutes=minute),
                    payload={"status": status, "difference_count": int(status != "APROBADO")},
                )
            latest = repository.latest_by_symbol(("SPY", "QQQ"))
            self.assertEqual(latest["SPY"]["status"], "APROBADO")
            self.assertEqual(latest["QQQ"]["status"], "RECHAZADO")


if __name__ == "__main__":
    unittest.main()
