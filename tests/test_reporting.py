"""Pruebas del reporte auditable."""

import json
import unittest

from analysis_models import (
    DecisionAssessment,
    DirectionBias,
    EvaluationStatus,
    FinalDecision,
    GateStatus,
)
from reporting import build_analysis_report, report_to_json


class ReportingTests(unittest.TestCase):
    def test_enums_and_nested_values_are_json_serializable(self) -> None:
        report = build_analysis_report(
            symbol="spy",
            data_as_of="2026-06-24",
            methodology_version="test",
            app_version="test-app",
            strategies=[],
            panorama={"status": GateStatus.APROBADO},
            invalidations=[],
            levels=[],
            data_quality={"status": GateStatus.APROBADO},
            risk={"status": GateStatus.APROBADO},
            governance={"status": GateStatus.APROBADO},
            decision={"decision": FinalDecision.NO_OPERAR},
            data_source={"provider": "TC2000_TXT"},
        )

        encoded = report_to_json(report)
        decoded = json.loads(encoded)

        self.assertEqual(decoded["symbol"], "SPY")
        self.assertEqual(decoded["app_version"], "test-app")
        self.assertEqual(decoded["data_source"]["provider"], "TC2000_TXT")
        self.assertEqual(decoded["decision"]["decision"], "NO_OPERAR")
        self.assertEqual(decoded["strategy_summary"]["evaluated"], 0)
        self.assertEqual(decoded["strategy_summary"]["detected"], 0)
        self.assertEqual(decoded["strategies"]["evaluations"], [])
        self.assertEqual(decoded["strategies"]["skipped"], {})
        self.assertEqual(decoded["strategies"]["errors"], {})

    def test_strategy_summary_supports_dict_evaluations(self) -> None:
        report = build_analysis_report(
            symbol="SPY",
            data_as_of="2026-06-24",
            methodology_version="test",
            app_version="test-app",
            strategies={
                "evaluations": [
                    {
                        "strategy_id": "TEST_CONFIRMADA",
                        "detected": True,
                        "criteria": [
                            {"required": True, "status": EvaluationStatus.CUMPLE},
                            {"required": False, "status": "NO_CUMPLE"},
                        ],
                    },
                    {
                        "strategy_id": "TEST_PENDIENTE",
                        "detected": True,
                        "criteria": [{"required": True, "status": "NO_DISPONIBLE"}],
                    },
                    {"strategy_id": "TEST_NO_DETECTADA", "detected": False},
                ],
                "skipped": {"X": "faltan datos"},
                "errors": {"Y": "error"},
            },
            panorama={},
            invalidations=[],
            levels=[],
            data_quality={},
            risk={},
            governance={},
            decision={},
        )

        self.assertEqual(report["strategy_summary"]["evaluated"], 3)
        self.assertEqual(report["strategy_summary"]["detected"], 2)
        self.assertEqual(report["strategy_summary"]["confirmed"], 1)
        self.assertEqual(report["strategy_summary"]["skipped"], 1)
        self.assertEqual(report["strategy_summary"]["errors"], 1)

    def test_strategy_summary_does_not_confirm_without_required_criteria(self) -> None:
        report = build_analysis_report(
            symbol="SPY",
            data_as_of="2026-06-24",
            methodology_version="test",
            app_version="test-app",
            strategies={
                "evaluations": [
                    {
                        "strategy_id": "LEGACY_DETECTED",
                        "detected": True,
                        "criteria": [],
                    }
                ],
                "skipped": {},
                "errors": {},
            },
            panorama={},
            invalidations=[],
            levels=[],
            data_quality={},
            risk={},
            governance={},
            decision={},
        )

        self.assertEqual(report["strategy_summary"]["detected"], 1)
        self.assertEqual(report["strategy_summary"]["confirmed"], 0)

    def test_strategy_summary_does_not_confirm_non_detected_evaluation(self) -> None:
        report = build_analysis_report(
            symbol="SPY", data_as_of="2026-08-19", methodology_version="test",
            app_version="test-app",
            strategies={"evaluations": [{
                "strategy_id": "SIN_SETUP", "detected": False,
                "criteria": [{"required": True, "status": "CUMPLE"}],
            }], "skipped": {}, "errors": {}},
            panorama={}, invalidations=[], levels=[], data_quality={}, risk={},
            governance={}, decision={},
        )
        self.assertEqual(report["strategy_summary"]["confirmed"], 0)

    def test_list_strategies_are_normalized_to_auditable_object(self) -> None:
        report = build_analysis_report(
            symbol="SPY",
            data_as_of="2026-06-24",
            methodology_version="test",
            app_version="test-app",
            strategies=[
                {
                    "strategy_id": "TEST",
                    "detected": True,
                    "criteria": [{"required": True, "status": "CUMPLE"}],
                }
            ],
            panorama={},
            invalidations=[],
            levels=[],
            data_quality={},
            risk={},
            governance={},
            decision={},
        )

        self.assertEqual(len(report["strategies"]["evaluations"]), 1)
        self.assertEqual(report["strategies"]["skipped"], {})
        self.assertEqual(report["strategies"]["errors"], {})
        self.assertEqual(report["strategy_summary"]["confirmed"], 1)

    def test_decision_tentative_bias_is_serialized(self) -> None:
        decision = DecisionAssessment(
            decision=FinalDecision.NO_OPERAR,
            confidence="NO_CALIBRADA",
            reasons=("Sesgo tentativo detectado.",),
            supporting_strategies=(),
            data_quality_status=GateStatus.APROBADO,
            panorama_status=GateStatus.APROBADO,
            risk_status=GateStatus.NO_DISPONIBLE,
            governance_status=GateStatus.APROBADO,
            active_invalidations=(),
            pending_invalidations=("Noticias pendientes",),
            tentative_bias=DirectionBias.CALL,
            tentative_strategies=("TEST_PENDING_STRATEGY",),
        )
        report = build_analysis_report(
            symbol="SPY",
            data_as_of="2026-06-24",
            methodology_version="test",
            app_version="test-app",
            strategies=[],
            panorama={},
            invalidations=[],
            levels=[],
            data_quality={},
            risk={},
            governance={},
            decision=decision,
        )

        self.assertEqual(report["decision"]["tentative_bias"], "CALL")
        self.assertEqual(
            report["decision"]["pending_invalidations"],
            ["Noticias pendientes"],
        )
        self.assertEqual(
            report["decision"]["tentative_strategies"],
            ["TEST_PENDING_STRATEGY"],
        )

    def test_required_report_metadata_is_validated(self) -> None:
        required_args = {
            "symbol": "SPY",
            "data_as_of": "2026-06-24",
            "methodology_version": "test",
            "app_version": "test-app",
            "strategies": [],
            "panorama": {},
            "invalidations": [],
            "levels": [],
            "data_quality": {},
            "risk": {},
            "governance": {},
            "decision": {},
        }

        for field in ("symbol", "data_as_of", "methodology_version"):
            with self.subTest(field=field):
                args = dict(required_args)
                args[field] = ""
                with self.assertRaises(ValueError):
                    build_analysis_report(**args)

        args = dict(required_args)
        args["app_version"] = ""
        with self.assertRaises(ValueError):
            build_analysis_report(**args)

    def test_report_to_json_rejects_non_object_report(self) -> None:
        with self.assertRaises(ValueError):
            report_to_json([])


if __name__ == "__main__":
    unittest.main()
