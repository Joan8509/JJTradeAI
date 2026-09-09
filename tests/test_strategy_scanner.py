"""Pruebas del scanner multi-activo por estrategia."""

import unittest

from strategy_scanner import build_strategy_scan_rows


def _report(symbol: str, status: str, *, detected: bool = True) -> dict:
    return {
        "symbol": symbol,
        "data_as_of": "2026-07-20T09:30:00",
        "data_quality": {"status": "APROBADO"},
        "panorama": {"status": "APROBADO"},
        "decision": {
            "decision": "NO_OPERAR",
            "risk_status": "NO_DISPONIBLE",
            "governance_status": "NO_DISPONIBLE",
        },
        "invalidations": [{"name": "Noticias", "status": "NO_CUMPLE"}],
        "strategies": {
            "evaluations": [
                {
                    "strategy_id": "CT15_ALCISTA",
                    "name": "Cambio de Tendencia en 15 Alcista",
                    "timeframe": "15m",
                    "bias": "CALL",
                    "detected": detected,
                    "criteria": [
                        {
                            "name": "Ruptura confirmada",
                            "required": True,
                            "status": status,
                        }
                    ],
                }
            ],
            "skipped": {},
            "errors": {},
        },
    }


class StrategyScannerTests(unittest.TestCase):
    def test_scanner_compares_symbols_without_emitting_entry(self) -> None:
        rows = build_strategy_scan_rows(
            (
                _report("SPY", "CUMPLE"),
                _report("QQQ", "REQUIERE_REVISION"),
                _report("TSLA", "NO_CUMPLE"),
            )
        )

        self.assertEqual([row["state"] for row in rows], [
            "CONFIRMADA", "CANDIDATA", "FALLIDA"
        ])
        self.assertTrue(all(row["final_decision"] == "NO_OPERAR" for row in rows))
        self.assertEqual(rows[1]["next_required"], "Ruptura confirmada")

    def test_detected_only_excludes_absent_geometry(self) -> None:
        rows = build_strategy_scan_rows(
            (_report("SPY", "NO_CUMPLE", detected=False),),
            detected_only=True,
        )

        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
