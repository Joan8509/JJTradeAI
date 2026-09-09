"""Pruebas de la compuerta de frescura del mercado en vivo."""

from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from analysis_models import GateStatus
from live_freshness import evaluate_live_freshness
from live_market import MarketBar


BAR_TIME = datetime(2026, 7, 21, 14, 14, tzinfo=timezone.utc)


def frame(latest: datetime = BAR_TIME) -> pd.DataFrame:
    dates = pd.date_range(latest - timedelta(minutes=14), latest, freq="min")
    return pd.DataFrame(
        {
            "date": dates,
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100.5,
            "volume": 10,
        }
    )


def bar(timestamp: datetime = BAR_TIME, *, complete: bool = True) -> MarketBar:
    return MarketBar("SPY", timestamp, 100, 101, 99, 100.5, 10, complete)


class LiveFreshnessTests(unittest.TestCase):
    def test_recent_persisted_live_bar_is_approved(self) -> None:
        result = evaluate_live_freshness(
            bar(), frame(), feed="sip", checked_at=BAR_TIME + timedelta(seconds=65)
        )

        self.assertEqual(result.status, GateStatus.APROBADO)
        self.assertTrue(result.latest_persisted_matches)
        self.assertEqual(result.recent_gap_count, 0)

    def test_delayed_feed_is_rejected_even_if_recent(self) -> None:
        result = evaluate_live_freshness(
            bar(), frame(), feed="delayed_sip", checked_at=BAR_TIME + timedelta(seconds=65)
        )

        self.assertEqual(result.status, GateStatus.RECHAZADO)
        self.assertTrue(any("retraso" in issue for issue in result.issues))

    def test_old_bar_is_rejected(self) -> None:
        result = evaluate_live_freshness(
            bar(), frame(), feed="sip", checked_at=BAR_TIME + timedelta(minutes=10)
        )

        self.assertEqual(result.status, GateStatus.RECHAZADO)
        self.assertTrue(any("antigüedad" in issue for issue in result.issues))

    def test_unpersisted_event_is_rejected(self) -> None:
        result = evaluate_live_freshness(
            bar(),
            frame(BAR_TIME - timedelta(minutes=1)),
            feed="iex",
            checked_at=BAR_TIME + timedelta(seconds=65),
        )

        self.assertEqual(result.status, GateStatus.RECHAZADO)
        self.assertFalse(result.latest_persisted_matches)

    def test_open_or_future_bar_is_rejected(self) -> None:
        result = evaluate_live_freshness(
            bar(BAR_TIME + timedelta(minutes=1), complete=False),
            frame(BAR_TIME + timedelta(minutes=1)),
            feed="sip",
            checked_at=BAR_TIME,
        )

        self.assertEqual(result.status, GateStatus.RECHAZADO)
        self.assertGreaterEqual(len(result.issues), 2)


if __name__ == "__main__":
    unittest.main()
