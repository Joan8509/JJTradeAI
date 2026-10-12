import tempfile
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

import pandas as pd

from live_strategy_service import AlertRepository
from market_store import MarketBarStore
from paper_signal_evaluator import (
    PaperSignalEvaluationRepository,
    build_paper_directional_learning_signal,
    build_paper_signal_advisory,
    evaluate_available_signals,
)


START = datetime(2026, 9, 4, 14, 59, tzinfo=timezone.utc)


def report(*, bias="CALL", status="CUMPLE"):
    return {
        "data_as_of": START.isoformat(),
        "methodology_version": "test-1",
        "decision": {"decision": bias},
        "strategy_summary": {"evaluated": 1, "detected": 1, "confirmed": 1},
        "strategies": {"evaluations": [{
            "strategy_id": "TEST_STRATEGY", "name": "Test", "bias": bias,
            "detected": True, "timeframe": "15m",
            "criteria": [{"criterion_id": "required", "name": "Required",
                          "required": True, "status": status}],
        }]},
    }


class PaperSignalEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "market.db"
        self.store = MarketBarStore(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def add_bars(self, closes):
        frame = pd.DataFrame([
            {"date": START + timedelta(minutes=minute), "open": close,
             "high": close + 0.5, "low": close - 0.5, "close": close,
             "volume": 100}
            for minute, close in closes
        ])
        self.store.upsert_frame(frame, symbol="SPY", provider="ALPACA", feed="iex")

    def add_alert(self, payload=None):
        return AlertRepository(self.database).record(
            provider="ALPACA", feed="iex", symbol="SPY",
            trigger_timestamp=START, report=payload or report(),
        )

    def test_evaluates_confirmed_call_without_future_leakage(self):
        self.add_bars([(0, 100), (15, 102), (30, 99)])
        self.add_alert()
        result = evaluate_available_signals(self.database, horizons=(15, 30))
        self.assertEqual(result["inserted"], 2)
        rows = PaperSignalEvaluationRepository(self.database).summary()
        by_horizon = {row["horizon_minutes"]: row for row in rows}
        self.assertEqual(by_horizon[15]["correct_count"], 1)
        self.assertEqual(by_horizon[30]["incorrect_count"], 1)

    def test_put_inverts_direction(self):
        self.add_bars([(0, 100), (15, 98)])
        self.add_alert(report(bias="PUT"))
        result = evaluate_available_signals(self.database, horizons=(15,))
        self.assertEqual(result["summary"][0]["correct_count"], 1)
        self.assertGreater(result["summary"][0]["average_directional_return_pct"], 0)

    def test_automatic_learning_signal_rejects_small_sample(self):
        self.add_bars([(0, 100), (60, 102)])
        self.add_alert()
        evaluate_available_signals(self.database, horizons=(60,))

        signal = build_paper_directional_learning_signal(
            self.database, strategy_ids=("TEST_STRATEGY",), current_direction="CALL",
            as_of=START + timedelta(minutes=61), methodology_version="test-1",
            horizon_minutes=60, minimum_sample_size=1,
        )

        self.assertEqual(signal["status"], "MUESTRA_INSUFICIENTE")
        self.assertIsNone(signal["recommended_direction"])

    def test_directional_learning_only_uses_evidence_known_at_alert_time(self):
        self.add_bars([(0, 100), (60, 102)])
        self.add_alert()
        evaluate_available_signals(self.database, horizons=(60,))
        known_at = START + timedelta(minutes=90)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE paper_signal_evaluations SET evaluated_at=?",
                (known_at.isoformat(),),
            )
            connection.commit()

        for as_of, expected_size in (
            (START + timedelta(minutes=59), 0),
            (START + timedelta(minutes=61), 0),
            (known_at, 1),
        ):
            with self.subTest(as_of=as_of):
                signal = build_paper_directional_learning_signal(
                    self.database, strategy_ids=("TEST_STRATEGY",),
                    current_direction="CALL", as_of=as_of,
                    methodology_version="test-1", horizon_minutes=60,
                    minimum_sample_size=1,
                )
                self.assertEqual(
                    signal["rows"][0]["call"]["sample_size"],
                    expected_size,
                )

    def test_pending_horizon_is_not_fabricated(self):
        self.add_bars([(0, 100), (10, 102)])
        self.add_alert()
        result = evaluate_available_signals(self.database, horizons=(15,))
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["pending"], 1)

    def test_is_idempotent(self):
        self.add_bars([(0, 100), (15, 101)])
        self.add_alert()
        first = evaluate_available_signals(self.database, horizons=(15,))
        second = evaluate_available_signals(self.database, horizons=(15,))
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)

    def test_unconfirmed_strategy_is_ignored(self):
        self.add_bars([(0, 100), (15, 101)])
        payload = report(status="REQUIERE_REVISION")
        payload["strategy_summary"]["confirmed"] = 0
        self.add_alert(payload)
        result = evaluate_available_signals(self.database, horizons=(15,))
        self.assertEqual(result["eligible_evaluations"], 0)

    def test_symbol_filter_limits_incremental_evaluation(self):
        self.add_bars([(0, 100), (15, 101)])
        self.add_alert()
        result = evaluate_available_signals(
            self.database, horizons=(15,), symbols=("QQQ",)
        )
        self.assertEqual(result["eligible_evaluations"], 0)
        self.assertEqual(result["symbols"], ["QQQ"])

    def test_advisory_excludes_evidence_not_known_at_alert_time(self):
        self.add_bars([(0, 100), (15, 101)])
        self.add_alert()
        evaluate_available_signals(self.database, horizons=(15,))
        early = build_paper_signal_advisory(
            self.database, strategy_ids=("TEST_STRATEGY",),
            as_of=START, methodology_version="test-1", horizon_minutes=15,
            minimum_sample_size=1,
        )
        later = build_paper_signal_advisory(
            self.database, strategy_ids=("TEST_STRATEGY",),
            as_of=datetime.now(timezone.utc) + timedelta(seconds=1),
            methodology_version="test-1", horizon_minutes=15,
            minimum_sample_size=1,
        )
        self.assertEqual(early["rows"][0]["sample_size"], 0)
        self.assertEqual(later["rows"][0]["sample_size"], 1)
        self.assertEqual(later["rows"][0]["status"], "EVIDENCIA_NO_CONCLUYENTE")


if __name__ == "__main__":
    unittest.main()
