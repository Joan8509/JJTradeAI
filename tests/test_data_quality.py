"""Pruebas de integridad multitemporal."""

import unittest

import pandas as pd

from analysis_models import GateStatus
from data_quality import evaluate_data_quality


def _frame(day: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [f"{day} 09:30"],
            "open": [99.0],
            "high": [101.0],
            "low": [98.0],
            "close": [100.0],
            "bollinger_mid": [100.0],
            "bollinger_upper": [102.0],
            "bollinger_lower": [98.0],
        }
    )


class DataQualityTests(unittest.TestCase):
    def test_aligned_complete_frames_are_approved(self) -> None:
        result = evaluate_data_quality({"15m": _frame("2026-06-24"), "1H": _frame("2026-06-24")})
        self.assertIs(result.status, GateStatus.APROBADO)
        self.assertEqual(result.candle_counts, {"15m": 1, "1H": 1})

    def test_different_latest_sessions_are_rejected(self) -> None:
        result = evaluate_data_quality({"15m": _frame("2026-06-24"), "1D": _frame("2026-06-23")})
        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertTrue(any("misma sesión" in issue for issue in result.issues))

    def test_live_opening_accepts_previous_closed_hour_and_day(self) -> None:
        intraday = _frame("2026-08-19")
        intraday.loc[0, "date"] = "2026-08-19T13:30:00+00:00"
        result = evaluate_data_quality(
            {"15m": intraday, "1H": _frame("2026-08-18"), "1D": _frame("2026-08-18")},
            live_market_data=True,
            session_closed=False,
        )
        self.assertIs(result.status, GateStatus.APROBADO)

    def test_live_after_first_hour_rejects_stale_hour(self) -> None:
        intraday = _frame("2026-08-19")
        intraday.loc[0, "date"] = "2026-08-19T14:30:00+00:00"
        result = evaluate_data_quality(
            {"15m": intraday, "1H": _frame("2026-08-18"), "1D": _frame("2026-08-18")},
            live_market_data=True,
            session_closed=False,
        )
        self.assertIs(result.status, GateStatus.RECHAZADO)

    def test_duplicate_dates_are_rejected(self) -> None:
        frame = pd.concat([_frame("2026-06-24"), _frame("2026-06-24")], ignore_index=True)
        result = evaluate_data_quality({"15m": frame})
        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertEqual(result.candle_counts["15m"], 2)

    def test_invalid_dates_are_rejected_without_crashing(self) -> None:
        frame = _frame("2026-06-24")
        frame.loc[0, "date"] = "NOT-A-DATE"

        result = evaluate_data_quality({"15m": frame})

        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertIn("15m: fechas inválidas.", result.issues)

    def test_incoherent_high_is_rejected(self) -> None:
        frame = _frame("2026-06-24")
        frame.loc[0, "high"] = 97.0

        result = evaluate_data_quality({"15m": frame})

        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertIn("15m: high no respeta coherencia OHLC.", result.issues)

    def test_incoherent_low_is_rejected(self) -> None:
        frame = _frame("2026-06-24")
        frame.loc[0, "low"] = 102.0

        result = evaluate_data_quality({"15m": frame})

        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertIn("15m: low no respeta coherencia OHLC.", result.issues)

    def test_non_numeric_ohlc_is_rejected(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2026-06-24 09:30"],
                "open": ["BAD"],
                "high": [101.0],
                "low": [98.0],
                "close": [100.0],
                "bollinger_mid": [100.0],
                "bollinger_upper": [102.0],
                "bollinger_lower": [98.0],
            }
        )

        result = evaluate_data_quality({"15m": frame})

        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertIn("15m: OHLC contiene valores no numericos.", result.issues)

    def test_empty_dataset_result_has_no_candle_counts(self) -> None:
        result = evaluate_data_quality({})

        self.assertIs(result.status, GateStatus.NO_DISPONIBLE)
        self.assertEqual(result.candle_counts, {})


if __name__ == "__main__":
    unittest.main()
