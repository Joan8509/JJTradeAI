"""Pruebas de etiquetas reproducibles para aprendizaje contextual."""

from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from learning_context import build_learning_context, context_from_report


class LearningContextTests(unittest.TestCase):
    def test_builds_trend_volatility_session_and_alignment(self) -> None:
        start = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
        rows = []
        for index in range(25):
            close = 100 + index
            width = 1 if index < 20 else 2
            rows.append({"date": start + timedelta(minutes=15 * index), "close": close, "high": close + width, "low": close - width})
        context = build_learning_context(
            pd.DataFrame(rows), decision="CALL", trigger_timestamp=start,
            market_context={"benchmarks": [
                {"direction": "ALCISTA", "synchronized": True},
                {"direction": "ALCISTA", "synchronized": True},
                {"direction": "BAJISTA", "synchronized": True},
            ]},
        )
        self.assertEqual(context["trend_15m"], "ALCISTA")
        self.assertEqual(context["relative_volatility_15m"], "ALTA")
        self.assertEqual(context["session_segment"], "APERTURA")
        self.assertEqual(context["benchmark_alignment"], "ALINEADO")
        self.assertEqual(context["benchmark_synchronization"], "COMPLETA")

    def test_missing_price_history_is_explicit(self) -> None:
        context = build_learning_context(
            pd.DataFrame(), decision="PUT", market_context={},
            trigger_timestamp=datetime(2026, 7, 21, 13, 30),
        )
        self.assertEqual(context["trend_15m"], "NO_DISPONIBLE")
        self.assertEqual(context["session_segment"], "NO_DISPONIBLE")

    def test_reevaluation_direction_recomputes_stored_alignment(self) -> None:
        report = {"learning_context": {"benchmark_regime": "BAJISTA", "benchmark_alignment": "NO_DISPONIBLE"}}
        self.assertEqual(context_from_report(report, "PUT")["benchmark_alignment"], "ALINEADO")


if __name__ == "__main__":
    unittest.main()
