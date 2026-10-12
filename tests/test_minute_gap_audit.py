from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from market_store import MarketBarStore
from live_market import NoMarketDataError
from minute_gap_audit import audit_session, minute_ranges, recover_session_gaps


START = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)


class GapAuditTests(unittest.TestCase):
    def audit(self, **changes):
        args = dict(symbol="SPY", provider="ALPACA", feed="iex", session_date="2026-10-06",
                    opens_at=START, closes_at=START + timedelta(minutes=3),
                    timestamps=[START, START + timedelta(minutes=2)], as_of=START + timedelta(minutes=3))
        args.update(changes)
        return audit_session(**args)

    def test_open_minute_is_not_classified_missing(self):
        result = self.audit(as_of=START + timedelta(seconds=90), timestamps=[START])
        self.assertEqual(result["expected_minutes"], 1)
        self.assertEqual(result["missing_minutes"], 0)

    def test_early_close_does_not_create_afternoon_gaps(self):
        result = self.audit(closes_at=START + timedelta(minutes=210), as_of=START + timedelta(minutes=390), timestamps=[])
        self.assertEqual(result["expected_minutes"], 210)
        self.assertEqual(result["status"], "SIN_COBERTURA_LOCAL")

    def test_ranges_are_contiguous_and_deduplicated(self):
        result = minute_ranges([START, START, START + timedelta(minutes=1), START + timedelta(minutes=3)])
        self.assertEqual([item["minutes"] for item in result], [2, 1])

    def test_recovery_inserts_missing_and_preserves_existing_prices(self):
        def frame(offsets, price):
            return pd.DataFrame([dict(date=START + timedelta(minutes=minute), open=price, high=price + 1, low=price - 1, close=price, volume=10) for minute in offsets])
        class Provider:
            def fetch_minute_bars(self, symbol, *, start, end):
                return frame([0, 1, 2, 3], 200)
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "test.db")
            store.upsert_frame(frame([0, 2], 100), symbol="SPY", provider="ALPACA", feed="iex")
            result = recover_session_gaps(store, Provider(), audit=self.audit(), provider_name="ALPACA", feed="iex")
            self.assertEqual(result["inserted"], 1)
            self.assertEqual(result["remaining"], 0)
            rows = store.load_frame(symbol="SPY", provider="ALPACA", feed="iex")
            self.assertEqual(rows["close"].tolist(), [100, 200, 100])
            self.assertEqual(len(rows), 3)
            repeat = recover_session_gaps(store, Provider(), audit=self.audit(), provider_name="ALPACA", feed="iex")
            self.assertEqual(repeat["inserted"], 0)

    def test_other_feed_is_rejected(self):
        with self.assertRaises(ValueError):
            recover_session_gaps(None, None, audit=self.audit(), provider_name="ALPACA", feed="sip")

    def test_provider_without_bars_keeps_minutes_unresolved(self):
        class Provider:
            def fetch_minute_bars(self, symbol, *, start, end):
                raise NoMarketDataError("Sin barras")
        with tempfile.TemporaryDirectory() as directory:
            store = MarketBarStore(Path(directory) / "test.db")
            result = recover_session_gaps(store, Provider(), audit=self.audit(), provider_name="ALPACA", feed="iex")
            self.assertEqual(result["inserted"], 0)
            self.assertEqual(result["remaining"], 3)
            self.assertEqual(result["status"], "CONSULTADA_CON_MINUTOS_SIN_BARRA")
            self.assertEqual(result["cause"], "NO_DETERMINADA")


if __name__ == "__main__":
    unittest.main()
