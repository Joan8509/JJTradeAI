"""Pruebas de normalización y agregación del mercado en vivo."""

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from live_market import (
    aggregate_minute_bars,
    closes_timeframe,
    normalize_minute_bars,
    retain_closed_aggregates,
)


def minute_frame(periods: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2026-07-20 13:30:00Z", periods=periods, freq="min")
    values = pd.Series(range(periods), dtype=float) + 100
    return pd.DataFrame(
        {
            "date": dates,
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values + 0.5,
            "volume": 10,
        }
    )


class LiveMarketTests(unittest.TestCase):
    def test_normalize_rejects_duplicate_timestamps(self) -> None:
        frame = minute_frame(2)
        frame.loc[1, "date"] = frame.loc[0, "date"]

        with self.assertRaisesRegex(ValueError, "duplicadas"):
            normalize_minute_bars(frame)

    def test_aggregates_fifteen_minutes_from_market_open(self) -> None:
        result = aggregate_minute_bars(minute_frame(30), "15m")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["open"], 100)
        self.assertEqual(result.iloc[0]["close"], 114.5)
        self.assertEqual(result.iloc[0]["volume"], 150)
        self.assertEqual(str(result.iloc[0]["date"]), "2026-07-20 13:30:00+00:00")

    def test_aggregates_hour_from_930_not_clock_hour(self) -> None:
        result = aggregate_minute_bars(minute_frame(60), "1H")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["close"], 159.5)

    def test_rejects_unknown_timeframe(self) -> None:
        with self.assertRaisesRegex(ValueError, "Temporalidad"):
            aggregate_minute_bars(minute_frame(), "5m")

    def test_detects_closed_fifteen_minute_block(self) -> None:
        self.assertTrue(closes_timeframe(pd.Timestamp("2026-07-20 13:44:00Z").to_pydatetime(), "15m"))
        self.assertFalse(closes_timeframe(pd.Timestamp("2026-07-20 13:43:00Z").to_pydatetime(), "15m"))

    def test_does_not_trigger_outside_regular_session(self) -> None:
        self.assertFalse(closes_timeframe(pd.Timestamp("2026-07-20 13:29:00Z").to_pydatetime(), "15m"))

    def test_market_close_finishes_partial_hour(self) -> None:
        self.assertTrue(closes_timeframe(pd.Timestamp("2026-07-20 19:59:00Z").to_pydatetime(), "1H"))

    def test_fifteen_minute_close_does_not_close_hour_or_day(self) -> None:
        source = minute_frame(15)

        closed_15m = retain_closed_aggregates(
            aggregate_minute_bars(source, "15m"),
            "15m",
            latest_source_timestamp=source.iloc[-1]["date"].to_pydatetime(),
        )
        closed_hour = retain_closed_aggregates(
            aggregate_minute_bars(source, "1H"),
            "1H",
            latest_source_timestamp=source.iloc[-1]["date"].to_pydatetime(),
        )
        closed_day = retain_closed_aggregates(
            aggregate_minute_bars(source, "1D"),
            "1D",
            latest_source_timestamp=source.iloc[-1]["date"].to_pydatetime(),
        )

        self.assertEqual(len(closed_15m), 1)
        self.assertTrue(closed_hour.empty)
        self.assertTrue(closed_day.empty)

    def test_hour_closes_at_1029_new_york(self) -> None:
        source = minute_frame(60)
        result = retain_closed_aggregates(
            aggregate_minute_bars(source, "1H"),
            "1H",
            latest_source_timestamp=source.iloc[-1]["date"].to_pydatetime(),
        )

        self.assertEqual(len(result), 1)

    def test_market_close_keeps_partial_final_hour_and_daily_bar(self) -> None:
        source = minute_frame(390)
        latest = source.iloc[-1]["date"].to_pydatetime()

        hours = retain_closed_aggregates(
            aggregate_minute_bars(source, "1H"), "1H", latest_source_timestamp=latest
        )
        days = retain_closed_aggregates(
            aggregate_minute_bars(source, "1D"), "1D", latest_source_timestamp=latest
        )

        self.assertEqual(len(hours), 7)
        self.assertEqual(len(days), 1)

    def test_early_close_finishes_hour_and_day_at_1300(self) -> None:
        source = minute_frame(210)
        latest = source.iloc[-1]["date"].to_pydatetime()
        closes = {
            date(2026, 7, 20): datetime(
                2026, 7, 20, 13, 0, tzinfo=ZoneInfo("America/New_York")
            )
        }
        hours = retain_closed_aggregates(
            aggregate_minute_bars(source, "1H"), "1H",
            latest_source_timestamp=latest, session_closes=closes,
        )
        days = retain_closed_aggregates(
            aggregate_minute_bars(source, "1D"), "1D",
            latest_source_timestamp=latest, session_closes=closes,
        )
        self.assertEqual(len(hours), 4)
        self.assertEqual(len(days), 1)


if __name__ == "__main__":
    unittest.main()
