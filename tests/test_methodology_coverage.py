"""Pruebas del contrato de cobertura metodologica."""

from pathlib import Path
import tempfile
import unittest

from analysis_pipeline import DETECTOR_REGISTRY, DetectorDefinition
from methodology_coverage import (
    DETECTOR_TRACEABILITY,
    audit_methodology_coverage,
)
from strategy_registry import STRATEGY_REGISTRY


class MethodologyCoverageTests(unittest.TestCase):
    def test_current_registry_is_fully_traceable_but_methodology_remains_partial(self) -> None:
        payload = audit_methodology_coverage()

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["strategy_count"], 18)
        self.assertEqual(payload["declared_strategy_count"], 18)
        self.assertEqual(payload["detector_count"], 9)
        self.assertEqual(payload["diagnostic_id_count"], 9)
        self.assertEqual(payload["partial_detector_count"], 8)
        self.assertFalse(payload["methodology_complete"])
        self.assertFalse(payload["real_trading_authorized"])

    def test_orphan_strategy_blocks_coverage(self) -> None:
        registry = {
            **STRATEGY_REGISTRY,
            "ORPHAN": {
                "nombre": "Huerfana",
                "categoria": next(iter(STRATEGY_REGISTRY.values()))["categoria"],
                "sesgo": "NEUTRAL",
                "requiere_confirmacion": True,
            },
        }

        payload = audit_methodology_coverage(strategy_registry=registry)

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertTrue(
            any(item["code"] == "ESTRATEGIA_HUERFANA" for item in payload["issues"])
        )

    def test_missing_document_and_unmanifested_source_are_reported(self) -> None:
        traceability = {
            **DETECTOR_TRACEABILITY,
            "CT15": {
                **DETECTOR_TRACEABILITY["CT15"],
                "documentation": "docs/strategies/DOES_NOT_EXIST.md",
                "sources": ("unknown-source.txt",),
            },
        }

        payload = audit_methodology_coverage(traceability=traceability)

        self.assertEqual(payload["status"], "BLOQUEADO")
        ct15 = next(
            item for item in payload["detectors"] if item["detector_id"] == "CT15"
        )
        self.assertTrue(any("Documento inexistente" in item for item in ct15["issues"]))
        self.assertTrue(any("Fuente no incluida" in item for item in ct15["issues"]))

    def test_partial_detector_without_confirmation_is_blocked(self) -> None:
        registry = {
            key: dict(value)
            for key, value in STRATEGY_REGISTRY.items()
        }
        registry["CT15_ALCISTA"]["requiere_confirmacion"] = False

        payload = audit_methodology_coverage(strategy_registry=registry)

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertTrue(
            any("sin confirmacion" in item["detail"] for item in payload["issues"])
        )

    def test_traceability_timeframe_mismatch_is_blocked(self) -> None:
        detector = DetectorDefinition(
            detector_id=DETECTOR_REGISTRY[0].detector_id,
            strategy_ids=DETECTOR_REGISTRY[0].strategy_ids,
            diagnostic_ids=DETECTOR_REGISTRY[0].diagnostic_ids,
            required_timeframes=("15m",),
            minimum_rows=(("15m", 1),),
            evaluate=DETECTOR_REGISTRY[0].evaluate,
        )

        payload = audit_methodology_coverage(
            detectors=(detector, *DETECTOR_REGISTRY[1:])
        )

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertTrue(
            any("Temporalidades distintas" in item["detail"] for item in payload["issues"])
        )


if __name__ == "__main__":
    unittest.main()
