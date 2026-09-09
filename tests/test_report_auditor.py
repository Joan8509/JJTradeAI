"""Pruebas del auditor de reportes JJTrade AI."""

from contextlib import redirect_stderr, redirect_stdout
import csv
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analysis_models import EvaluationStatus
from report_auditor import (
    AUDIT_FIELDS,
    REVIEW_QUEUE_FIELDS,
    audit_report,
    audit_report_directory,
    audit_report_file,
    build_review_queue,
    load_report,
    main,
    write_audit_csv,
    write_review_queue_csv,
)
from reporting import report_to_json
from validation_runner import load_tc2000_bundle, run_validation_assessment


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "exports" / "sample.txt"


def _run_cli_silently(arguments: list[str]) -> int:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        return main(arguments)


def _sample_report():
    datasets = load_tc2000_bundle(
        timeframe_15m=SAMPLE_PATH,
        timeframe_1h=SAMPLE_PATH,
        timeframe_1d=SAMPLE_PATH,
    )
    _, report = run_validation_assessment(symbol="SPY", datasets=datasets)
    return report


def _ready_report():
    return {
        "symbol": "SPY",
        "data_as_of": "2026-06-24T09:30:00",
        "app_version": "0.2.1-beta",
        "methodology_version": "investep-draft-0.1",
        "data_quality": {"status": "APROBADO"},
        "panorama": {"status": "APROBADO"},
        "decision": {
            "decision": "NO_OPERAR",
            "risk_status": "APROBADO",
            "governance_status": "APROBADO",
        },
        "invalidations": [
            {"name": "Noticias", "status": "NO_CUMPLE"},
        ],
        "strategies": {
            "errors": {},
            "evaluations": [
                {
                    "strategy_id": "CT15_ALCISTA",
                    "bias": "CALL",
                    "detected": True,
                    "criteria": [
                        {
                            "name": "Tendencia previa",
                            "required": True,
                            "status": "CUMPLE",
                        }
                    ],
                }
            ],
        },
    }


def _error_report_with_package():
    report = _ready_report()
    report["validation_package"] = {
        "package_id": "SPY_2026-06-24",
        "session": "2026-06-24",
        "timeframes": ["15m", "1H"],
    }
    return report


class ReportAuditorTests(unittest.TestCase):
    def test_conservative_validation_report_is_incomplete(self) -> None:
        audit = audit_report(_sample_report())

        self.assertEqual(audit.symbol, "SPY")
        self.assertEqual(audit.readiness, "INCOMPLETO")
        self.assertFalse(audit.learning_ready)
        self.assertTrue(audit.missing_evidence)
        self.assertGreater(audit.missing_gate_count, 0)
        self.assertGreater(audit.missing_strategy_count, 0)

    def test_ready_report_is_learning_ready(self) -> None:
        audit = audit_report(_ready_report())

        self.assertEqual(audit.readiness, "LISTO_REVISION")
        self.assertTrue(audit.learning_ready)
        self.assertEqual(audit.detected_strategies, ("CT15_ALCISTA",))
        self.assertEqual(audit.data_quality_status, "APROBADO")
        self.assertEqual(audit.panorama_status, "APROBADO")
        self.assertEqual(audit.risk_status, "APROBADO")
        self.assertEqual(audit.governance_status, "APROBADO")
        self.assertEqual(audit.app_version, "0.2.1-beta")
        self.assertEqual(audit.methodology_version, "investep-draft-0.1")
        self.assertEqual(audit.evaluated_count, 1)
        self.assertEqual(audit.detected_count, 1)
        self.assertEqual(audit.confirmed_count, 1)

    def test_pending_invalidation_summary_must_match_detailed_evidence(self) -> None:
        report = _ready_report()
        report["invalidations"][0]["status"] = "NO_DISPONIBLE"
        report["decision"]["pending_invalidations"] = ["Noticias"]

        audit = audit_report(report)

        self.assertEqual(audit.readiness, "INCOMPLETO")
        self.assertEqual(audit.missing_invalidation_count, 1)

        report["decision"]["pending_invalidations"] = []
        with self.assertRaisesRegex(ValueError, "no coincide"):
            audit_report(report)

    def test_active_invalidation_summary_must_match_detailed_evidence(self) -> None:
        report = _ready_report()
        report["invalidations"][0]["status"] = "CUMPLE"
        report["decision"]["active_invalidations"] = ["Noticias"]

        audit = audit_report(report)

        self.assertEqual(audit.readiness, "BLOQUEADO")
        self.assertEqual(audit.blocker_invalidation_count, 1)

        report["decision"]["active_invalidations"] = []
        with self.assertRaisesRegex(ValueError, "no coincide"):
            audit_report(report)

    def test_directional_decision_rejects_nonapproved_gate(self) -> None:
        report = _ready_report()
        report["decision"]["decision"] = "CALL"
        report["decision"]["risk_status"] = "NO_DISPONIBLE"

        with self.assertRaisesRegex(ValueError, "compuertas no aprobadas"):
            audit_report(report)

    def test_directional_decision_rejects_open_invalidation(self) -> None:
        for status in ("CUMPLE", "REQUIERE_REVISION"):
            with self.subTest(status=status):
                report = _ready_report()
                report["decision"]["decision"] = "PUT"
                report["invalidations"][0]["status"] = status

                with self.assertRaisesRegex(ValueError, "invalidaciones"):
                    audit_report(report)

    def test_directional_decision_requires_matching_confirmed_strategy(self) -> None:
        report = _ready_report()
        report["decision"]["decision"] = "CALL"

        audit = audit_report(report)
        self.assertEqual(audit.decision, "CALL")

        report["strategies"]["evaluations"][0]["bias"] = "PUT"
        with self.assertRaisesRegex(ValueError, "respaldo direccional"):
            audit_report(report)

    def test_directional_decision_rejects_confirmed_bias_conflict(self) -> None:
        report = _ready_report()
        report["decision"]["decision"] = "CALL"
        opposing = dict(report["strategies"]["evaluations"][0])
        opposing["strategy_id"] = "TEST_PUT"
        opposing["bias"] = "PUT"
        opposing["criteria"] = [dict(opposing["criteria"][0])]
        report["strategies"]["evaluations"].append(opposing)

        with self.assertRaisesRegex(ValueError, "respaldo direccional"):
            audit_report(report)

    def test_supporting_strategies_must_match_confirmed_evidence(self) -> None:
        report = _ready_report()
        report["decision"]["supporting_strategies"] = ["CT15_ALCISTA"]

        audit = audit_report(report)
        self.assertEqual(audit.detected_strategies, ("CT15_ALCISTA",))

        report["decision"]["supporting_strategies"] = ["ESTRATEGIA_INVENTADA"]
        with self.assertRaisesRegex(ValueError, "supporting_strategies"):
            audit_report(report)

    def test_legacy_report_without_versions_is_supported(self) -> None:
        report = _ready_report()
        report.pop("app_version")
        report.pop("methodology_version")

        audit = audit_report(report)

        self.assertEqual(audit.app_version, "")
        self.assertEqual(audit.methodology_version, "")

    def test_report_rejects_unsupported_schema_version(self) -> None:
        report = _ready_report()
        report["schema_version"] = "2.0"

        with self.assertRaisesRegex(ValueError, "no soportada"):
            audit_report(report)

    def test_present_versions_must_be_nonempty_text(self) -> None:
        empty_app_version = _ready_report()
        empty_app_version["app_version"] = ""

        invalid_methodology_version = _ready_report()
        invalid_methodology_version["methodology_version"] = ["draft"]

        for report in (empty_app_version, invalid_methodology_version):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_confidence_must_remain_uncalibrated(self) -> None:
        report = _ready_report()
        report["decision"]["confidence"] = "85%"

        with self.assertRaisesRegex(ValueError, "NO_CALIBRADA"):
            audit_report(report)

        report["decision"]["confidence"] = "NO_CALIBRADA"
        self.assertEqual(audit_report(report).decision, "NO_OPERAR")

    def test_decision_reasons_must_be_explanatory_text(self) -> None:
        malformed_reports = []
        for reasons in ("texto", [""], [123]):
            report = _ready_report()
            report["decision"]["reasons"] = reasons
            malformed_reports.append(report)

        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_legacy_top_level_gate_statuses_are_supported(self) -> None:
        report = _ready_report()
        report["decision"].pop("risk_status")
        report["decision"].pop("governance_status")
        report["risk"] = {"status": "RECHAZADO"}
        report["governance"] = {"status": "APROBADO"}

        audit = audit_report(report)

        self.assertEqual(audit.readiness, "BLOQUEADO")
        self.assertEqual(audit.risk_status, "RECHAZADO")
        self.assertEqual(audit.governance_status, "APROBADO")
        self.assertIn("riesgo: RECHAZADO", audit.blockers)

    def test_rejected_data_quality_issues_are_preserved_as_blockers(self) -> None:
        report = _ready_report()
        report["data_quality"] = {
            "status": "RECHAZADO",
            "issues": ["15m: high no respeta coherencia OHLC."],
        }
        report["decision"]["data_quality_status"] = "RECHAZADO"

        audit = audit_report(report)

        self.assertEqual(audit.readiness, "BLOQUEADO")
        self.assertIn("calidad_datos: RECHAZADO", audit.blockers)
        self.assertIn(
            "calidad_datos_issue: 15m: high no respeta coherencia OHLC.",
            audit.blockers,
        )

    def test_data_quality_details_require_valid_types(self) -> None:
        bad_issues = _ready_report()
        bad_issues["data_quality"]["issues"] = [""]

        bad_counts = _ready_report()
        bad_counts["data_quality"]["candle_counts"] = {"15m": -1}

        noninteger_counts = _ready_report()
        noninteger_counts["data_quality"]["candle_counts"] = {"15m": 10.5}

        for report in (bad_issues, bad_counts, noninteger_counts):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_data_quality_candle_counts_are_accepted(self) -> None:
        report = _ready_report()
        report["data_quality"]["candle_counts"] = {"15m": 120, "1H": 40}

        self.assertEqual(audit_report(report).readiness, "LISTO_REVISION")

    def test_candle_counts_must_match_source_timeframes(self) -> None:
        report = _ready_report()
        report["data_source"] = {
            "timeframes": ["15m", "1H"],
            "files": {},
        }
        report["data_quality"]["candle_counts"] = {"15m": 120, "1D": 10}

        with self.assertRaisesRegex(ValueError, "candle_counts no coincide"):
            audit_report(report)

        report["data_quality"]["candle_counts"] = {"15M": 120, "1h": 40}
        self.assertEqual(audit_report(report).readiness, "LISTO_REVISION")

    def test_contradictory_gate_summary_is_rejected(self) -> None:
        report = _ready_report()
        report["panorama"] = {"status": "APROBADO"}
        report["decision"]["panorama_status"] = "REQUIERE_REVISION"

        with self.assertRaisesRegex(ValueError, "no coincide"):
            audit_report(report)

    def test_matching_gate_summary_is_accepted(self) -> None:
        report = _ready_report()
        report["decision"]["data_quality_status"] = "APROBADO"
        report["decision"]["panorama_status"] = "APROBADO"

        audit = audit_report(report)

        self.assertEqual(audit.data_quality_status, "APROBADO")
        self.assertEqual(audit.panorama_status, "APROBADO")

    def test_report_strategy_summary_is_preserved(self) -> None:
        report = _ready_report()
        report["strategy_summary"] = {
            "evaluated": 8,
            "detected": 2,
            "confirmed": 1,
            "skipped": 0,
            "errors": 0,
        }

        audit = audit_report(report)

        self.assertEqual(audit.evaluated_count, 8)
        self.assertEqual(audit.detected_count, 2)
        self.assertEqual(audit.confirmed_count, 1)

    def test_schema_1_strategy_summary_must_match_evidence(self) -> None:
        report = _ready_report()
        report["schema_version"] = "1.0"
        report["strategy_summary"] = {
            "evaluated": 1,
            "detected": 1,
            "confirmed": 1,
            "skipped": 0,
            "errors": 0,
        }

        self.assertEqual(audit_report(report).confirmed_count, 1)

        report["strategy_summary"]["detected"] = 2
        with self.assertRaisesRegex(ValueError, "no coincide"):
            audit_report(report)

    def test_schema_1_strategy_summary_requires_integer_counts(self) -> None:
        report = _ready_report()
        report["schema_version"] = "1.0"
        report["strategy_summary"] = {
            "evaluated": "1",
            "detected": 1,
            "confirmed": 1,
            "skipped": 0,
            "errors": 0,
        }

        with self.assertRaisesRegex(ValueError, "enteros no negativos"):
            audit_report(report)

    def test_strategy_summary_derivation_supports_enum_statuses(self) -> None:
        report = _ready_report()
        report.pop("strategy_summary", None)
        report["strategies"]["evaluations"][0]["criteria"][0][
            "status"
        ] = EvaluationStatus.CUMPLE

        audit = audit_report(report)

        self.assertEqual(audit.evaluated_count, 1)
        self.assertEqual(audit.detected_count, 1)
        self.assertEqual(audit.confirmed_count, 1)

    def test_strategy_without_required_criteria_is_not_confirmed(self) -> None:
        report = _ready_report()
        report.pop("strategy_summary", None)
        report["strategies"]["evaluations"] = [
            {
                "strategy_id": "LEGACY_DETECTED",
                "detected": True,
                "criteria": [],
            }
        ]

        audit = audit_report(report)

        self.assertEqual(audit.detected_count, 1)
        self.assertEqual(audit.confirmed_count, 0)

    def test_invalid_strategy_summary_counts_use_zeroes(self) -> None:
        report = _ready_report()
        report["strategy_summary"] = {
            "evaluated": "n/a",
            "detected": None,
            "confirmed": [],
            "skipped": "dos",
            "errors": {},
        }

        audit = audit_report(report)

        self.assertEqual(audit.evaluated_count, 0)
        self.assertEqual(audit.detected_count, 0)
        self.assertEqual(audit.confirmed_count, 0)
        self.assertEqual(audit.skipped_count, 0)
        self.assertEqual(audit.error_count, 0)

    def test_validation_package_metadata_is_preserved(self) -> None:
        audit = audit_report(_error_report_with_package())

        self.assertEqual(audit.package_id, "SPY_2026-06-24")
        self.assertEqual(audit.package_session, "2026-06-24")
        self.assertEqual(audit.package_timeframes, "15m|1H")

    def test_validation_package_identity_must_match_report(self) -> None:
        symbol_mismatch = _error_report_with_package()
        symbol_mismatch["validation_package"]["symbol"] = "AAPL"

        empty_session = _error_report_with_package()
        empty_session["validation_package"]["session"] = ""

        bad_package_id = _error_report_with_package()
        bad_package_id["validation_package"]["package_id"] = "AAPL_2026-06-24"

        for report in (symbol_mismatch, empty_session, bad_package_id):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_data_source_metadata_is_preserved(self) -> None:
        report = _ready_report()
        report["data_source"] = {
            "provider": "TC2000_TXT",
            "timeframes": ["15m", "1H"],
            "files": {"15m": "SPY_15m.txt", "1H": "SPY_1H.txt"},
        }

        audit = audit_report(report)

        self.assertEqual(audit.data_provider, "TC2000_TXT")
        self.assertEqual(audit.data_source_timeframes, "15m|1H")
        self.assertEqual(
            audit.data_source_files,
            "15m:SPY_15m.txt|1H:SPY_1H.txt",
        )

    def test_package_and_data_source_timeframes_must_match(self) -> None:
        report = _error_report_with_package()
        report["data_source"] = {
            "provider": "TC2000_TXT",
            "timeframes": ["15m", "1D"],
            "files": {},
        }

        with self.assertRaisesRegex(ValueError, "timeframes no coincide"):
            audit_report(report)

        report["data_source"]["timeframes"] = ["15M", "1h"]
        audit = audit_report(report)
        self.assertEqual(audit.package_timeframes, "15m|1H")

    def test_timeframe_lists_reject_invalid_or_duplicate_values(self) -> None:
        malformed = _error_report_with_package()
        malformed["validation_package"]["timeframes"] = ["15m", "15M"]

        with self.assertRaises(ValueError):
            audit_report(malformed)

    def test_timeframe_files_must_match_declared_timeframes(self) -> None:
        report = _ready_report()
        report["data_source"] = {
            "provider": "TC2000_TXT",
            "timeframes": ["15m", "1H"],
            "files": {"15m": "SPY_15m.txt"},
        }

        with self.assertRaisesRegex(ValueError, "files no coincide"):
            audit_report(report)

        report["data_source"]["files"]["1H"] = "SPY_1H.txt"
        audit = audit_report(report)
        self.assertEqual(
            audit.data_source_files,
            "15m:SPY_15m.txt|1H:SPY_1H.txt",
        )

    def test_timeframe_files_reject_nontext_values(self) -> None:
        report = _ready_report()
        report["data_source"] = {"files": {"15m": None}}

        with self.assertRaises(ValueError):
            audit_report(report)

    def test_tentative_decision_metadata_is_preserved(self) -> None:
        report = _ready_report()
        report["strategies"]["evaluations"] = [
            {
                "strategy_id": strategy_id,
                "bias": "CALL",
                "detected": True,
                "criteria": [
                    {
                        "name": "Confirmación pendiente",
                        "required": True,
                        "status": "NO_DISPONIBLE",
                    }
                ],
            }
            for strategy_id in ("TEST_PENDING_ONE", "TEST_PENDING_TWO")
        ]
        report["decision"]["tentative_bias"] = "CALL"
        report["decision"]["tentative_strategies"] = [
            "TEST_PENDING_ONE",
            "TEST_PENDING_TWO",
        ]

        audit = audit_report(report)

        self.assertEqual(audit.tentative_bias, "CALL")
        self.assertEqual(
            audit.tentative_strategies,
            "TEST_PENDING_ONE|TEST_PENDING_TWO",
        )

        report["decision"]["tentative_bias"] = "PUT"
        with self.assertRaisesRegex(ValueError, "resumen tentativo"):
            audit_report(report)

    def test_legacy_tentative_strategy_string_is_preserved(self) -> None:
        report = _ready_report()
        report["decision"]["tentative_strategies"] = "TEST_PENDING"

        audit = audit_report(report)

        self.assertEqual(audit.tentative_strategies, "TEST_PENDING")

    def test_active_invalidation_blocks_report(self) -> None:
        report = _ready_report()
        report["invalidations"] = [{"name": "Noticia", "status": "CUMPLE"}]

        audit = audit_report(report)

        self.assertEqual(audit.readiness, "BLOQUEADO")
        self.assertIn("invalidacion_activa: Noticia", audit.blockers)
        self.assertEqual(audit.first_blocker, "invalidacion_activa: Noticia")
        self.assertEqual(audit.blocker_invalidation_count, 1)

    def test_review_queue_expands_blockers_and_missing_evidence(self) -> None:
        blocked_report = _ready_report()
        blocked_report["invalidations"] = [
            {"name": "Noticia", "status": "CUMPLE"}
        ]
        blocked = audit_report(blocked_report, report_path="blocked.json")
        incomplete = audit_report(_sample_report(), report_path="sample.json")

        queue = build_review_queue((blocked, incomplete))

        self.assertGreater(len(queue), 1)
        self.assertEqual(queue[0].priority, "1_BLOQUEO")
        self.assertEqual(queue[0].review_type, "INVALIDACION")
        self.assertEqual(queue[0].source, "invalidacion_activa")
        self.assertEqual(queue[0].report_path, "blocked.json")
        self.assertTrue(
            any(
                item.priority == "2_FALTANTE"
                and item.review_type == "COMPUERTA"
                and item.source == "panorama"
                for item in queue
            )
        )

    def test_review_queue_csv_keeps_header_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            csv_path = Path(raw_dir) / "review_queue.csv"
            audit = audit_report(_sample_report(), report_path="sample.json")

            write_review_queue_csv((audit,), csv_path)

            with csv_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, list(REVIEW_QUEUE_FIELDS))
            self.assertTrue(rows)
            self.assertEqual(rows[0]["priority"], "2_FALTANTE")
            self.assertIn("evidence", rows[0])

    def test_directory_and_csv_audit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            report_path = root / "report.json"
            csv_path = root / "audit.csv"
            report_path.write_text(report_to_json(_ready_report()), encoding="utf-8")

            audits = audit_report_directory(root)
            write_audit_csv(audits, csv_path)

            self.assertEqual(len(audits), 1)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, list(AUDIT_FIELDS))
            self.assertEqual(rows[0]["learning_ready"], "SI")
            self.assertEqual(rows[0]["data_quality_status"], "APROBADO")
            self.assertEqual(rows[0]["panorama_status"], "APROBADO")
            self.assertEqual(rows[0]["risk_status"], "APROBADO")
            self.assertEqual(rows[0]["governance_status"], "APROBADO")
            self.assertEqual(rows[0]["app_version"], "0.2.1-beta")
            self.assertEqual(rows[0]["methodology_version"], "investep-draft-0.1")
            self.assertEqual(rows[0]["package_id"], "")
            self.assertIn("data_provider", rows[0])
            self.assertIn("data_source_files", rows[0])
            self.assertEqual(rows[0]["evaluated_count"], "1")
            self.assertEqual(rows[0]["detected_count"], "1")
            self.assertIn("first_missing_evidence", rows[0])
            self.assertIn("first_blocker", rows[0])
            self.assertIn("tentative_bias", rows[0])
            self.assertIn("tentative_strategies", rows[0])

    def test_empty_csv_audit_keeps_header(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            csv_path = Path(raw_dir) / "audit.csv"

            write_audit_csv((), csv_path)

            with csv_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, list(AUDIT_FIELDS))
                self.assertEqual(list(reader), [])

    def test_missing_report_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            missing_report = Path(raw_dir) / "missing.json"
            missing_directory = Path(raw_dir) / "missing"

            with self.assertRaises(ValueError):
                audit_report_file(missing_report)
            with self.assertRaises(ValueError):
                audit_report_directory(missing_directory)

    def test_invalid_report_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            invalid_json = Path(raw_dir) / "invalid.json"
            list_json = Path(raw_dir) / "list.json"
            invalid_json.write_text("{nope", encoding="utf-8")
            list_json.write_text("[]", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_report(invalid_json)
            with self.assertRaises(ValueError):
                load_report(list_json)

    def test_directory_can_skip_invalid_reports(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            valid_json = root / "valid.json"
            invalid_json = root / "invalid.json"
            valid_json.write_text(report_to_json(_ready_report()), encoding="utf-8")
            invalid_json.write_text("{nope", encoding="utf-8")

            with self.assertRaises(ValueError):
                audit_report_directory(root)

            with redirect_stderr(StringIO()):
                audits = audit_report_directory(root, skip_invalid=True)

            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].symbol, "SPY")

    def test_audit_report_rejects_non_object_payload(self) -> None:
        with self.assertRaises(ValueError):
            audit_report([])

    def test_audit_report_requires_case_identity(self) -> None:
        missing_symbol = _ready_report()
        missing_symbol["symbol"] = ""

        missing_data_as_of = _ready_report()
        missing_data_as_of.pop("data_as_of")

        invalid_symbol_type = _ready_report()
        invalid_symbol_type["symbol"] = ["SPY"]

        for report in (missing_symbol, missing_data_as_of, invalid_symbol_type):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_audit_report_requires_iso_dates(self) -> None:
        bad_data_as_of = _ready_report()
        bad_data_as_of["data_as_of"] = "06/24/2026"

        bad_session = _error_report_with_package()
        bad_session["validation_package"]["session"] = "24-06-2026"

        for report in (bad_data_as_of, bad_session):
            with self.subTest(report=report):
                with self.assertRaisesRegex(ValueError, "formato ISO"):
                    audit_report(report)

        report = _ready_report()
        report["data_as_of"] = "2026-06-24T09:30:00Z"
        self.assertEqual(audit_report(report).data_as_of, report["data_as_of"])

    def test_symbol_is_normalized_for_audit_identity(self) -> None:
        report = _ready_report()
        report["symbol"] = " spy "

        self.assertEqual(audit_report(report).symbol, "SPY")

    def test_audit_report_rejects_malformed_sections(self) -> None:
        malformed_reports = [
            {"decision": []},
            {"strategy_summary": []},
            {"strategies": []},
            {"strategies": {"evaluations": [{}], "errors": []}},
            {"strategies": {"evaluations": [{"detected": True, "criteria": {}}]}},
            {"invalidations": {}},
        ]

        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_audit_report_rejects_unknown_status_values(self) -> None:
        malformed_reports = []

        gate_report = _ready_report()
        gate_report["decision"]["risk_status"] = "LISTO"
        malformed_reports.append(gate_report)

        decision_report = _ready_report()
        decision_report["decision"]["decision"] = "ESPERAR"
        malformed_reports.append(decision_report)

        strategy_report = _ready_report()
        strategy_report["strategies"]["evaluations"][0]["criteria"][0][
            "status"
        ] = "TAL_VEZ"
        malformed_reports.append(strategy_report)

        invalidation_report = _ready_report()
        invalidation_report["invalidations"][0]["status"] = "ABIERTA"
        malformed_reports.append(invalidation_report)

        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_audit_report_rejects_invalid_strategy_metadata(self) -> None:
        malformed_reports = []

        bias_report = _ready_report()
        bias_report["strategies"]["evaluations"][0]["bias"] = "ALCISTA"
        malformed_reports.append(bias_report)

        detected_report = _ready_report()
        detected_report["strategies"]["evaluations"][0]["detected"] = "SI"
        malformed_reports.append(detected_report)

        id_report = _ready_report()
        id_report["strategies"]["evaluations"][0]["strategy_id"] = ""
        malformed_reports.append(id_report)

        for report in malformed_reports:
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_strategy_skipped_and_errors_require_text_details(self) -> None:
        bad_skipped = _ready_report()
        bad_skipped["strategies"]["skipped"] = {"MOMENTUM": ""}

        bad_errors = _ready_report()
        bad_errors["strategies"]["errors"] = {"CT15": ["falló"]}

        empty_detector = _ready_report()
        empty_detector["strategies"]["errors"] = {"": "Error"}

        for report in (bad_skipped, bad_errors, empty_detector):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_audit_report_rejects_duplicate_strategy_ids(self) -> None:
        report = _ready_report()
        duplicate = dict(report["strategies"]["evaluations"][0])
        duplicate["criteria"] = [dict(duplicate["criteria"][0])]
        report["strategies"]["evaluations"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "Evaluación de estrategia duplicada"):
            audit_report(report)

    def test_repeated_strategy_ids_are_disambiguated_by_timeframe(self) -> None:
        report = _ready_report()
        first = report["strategies"]["evaluations"][0]
        first["timeframe"] = "15m"
        second = dict(first)
        second["timeframe"] = "1H"
        second["criteria"] = [dict(first["criteria"][0])]
        report["strategies"]["evaluations"].append(second)

        audit = audit_report(report)

        self.assertEqual(
            audit.detected_strategies,
            ("CT15_ALCISTA@15m", "CT15_ALCISTA@1H"),
        )

        second.pop("timeframe")
        with self.assertRaisesRegex(ValueError, "deben declarar timeframe"):
            audit_report(report)

    def test_strategy_gaps_include_timeframe(self) -> None:
        report = _ready_report()
        strategy = report["strategies"]["evaluations"][0]
        strategy["timeframe"] = "15m"
        strategy["criteria"][0]["status"] = "REQUIERE_REVISION"

        audit = audit_report(report)

        self.assertIn(
            "CT15_ALCISTA@15m: Tendencia previa (REQUIERE_REVISION)",
            audit.missing_evidence,
        )

    def test_audit_report_validates_all_strategy_criteria(self) -> None:
        bad_status = _ready_report()
        bad_status["strategies"]["evaluations"][0]["detected"] = False
        bad_status["strategies"]["evaluations"][0]["criteria"][0][
            "status"
        ] = "DESCONOCIDO"

        bad_required = _ready_report()
        bad_required["strategies"]["evaluations"][0]["criteria"][0][
            "required"
        ] = "SI"

        for report in (bad_status, bad_required):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_audit_report_rejects_duplicate_criterion_ids(self) -> None:
        strategy_report = _ready_report()
        criterion = strategy_report["strategies"]["evaluations"][0]["criteria"][0]
        criterion["criterion_id"] = "required"
        duplicate = dict(criterion)
        strategy_report["strategies"]["evaluations"][0]["criteria"].append(
            duplicate
        )

        invalidation_report = _ready_report()
        invalidation_report["invalidations"] = [
            {
                "criterion_id": "news",
                "name": "Noticias",
                "status": "NO_CUMPLE",
            },
            {
                "criterion_id": "news",
                "name": "Noticias duplicadas",
                "status": "NO_CUMPLE",
            },
        ]

        for report in (strategy_report, invalidation_report):
            with self.subTest(report=report):
                with self.assertRaisesRegex(ValueError, "criterion_id"):
                    audit_report(report)

    def test_present_traceability_fields_must_be_nonempty_text(self) -> None:
        bad_criterion = _ready_report()
        bad_criterion["strategies"]["evaluations"][0]["criteria"][0][
            "criterion_id"
        ] = 123

        bad_invalidation = _ready_report()
        bad_invalidation["invalidations"][0]["criterion_id"] = ""

        bad_timeframe = _ready_report()
        bad_timeframe["strategies"]["evaluations"][0]["timeframe"] = None

        for report in (bad_criterion, bad_invalidation, bad_timeframe):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_audit_report_rejects_invalid_invalidation_metadata(self) -> None:
        empty_name = _ready_report()
        empty_name["invalidations"][0]["name"] = ""

        bad_required = _ready_report()
        bad_required["invalidations"][0]["required"] = "SI"

        missing_status = _ready_report()
        missing_status["invalidations"][0].pop("status")

        for report in (empty_name, bad_required, missing_status):
            with self.subTest(report=report):
                with self.assertRaises(ValueError):
                    audit_report(report)

    def test_cli_writes_audit_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            report_path = root / "report.json"
            csv_path = root / "audit.csv"
            report_path.write_text(report_to_json(_ready_report()), encoding="utf-8")

            exit_code = main(
                [
                    "--report",
                    str(report_path),
                    "--output-csv",
                    str(csv_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(csv_path.exists())

    def test_cli_writes_review_queue_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            report_path = root / "report.json"
            csv_path = root / "review_queue.csv"
            report_path.write_text(report_to_json(_sample_report()), encoding="utf-8")

            exit_code = main(
                [
                    "--report",
                    str(report_path),
                    "--output-review-csv",
                    str(csv_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(rows)

    def test_cli_prints_version(self) -> None:
        with self.assertRaises(SystemExit) as context:
            _run_cli_silently(["--version"])

        self.assertEqual(context.exception.code, 0)

    def test_cli_rejects_missing_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            with self.assertRaises(SystemExit) as context:
                _run_cli_silently(
                    ["--report", str(Path(raw_dir) / "missing.json")]
                )

            self.assertEqual(context.exception.code, 2)

    def test_cli_rejects_invalid_report_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            invalid_json = Path(raw_dir) / "invalid.json"
            invalid_json.write_text("{nope", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                _run_cli_silently(["--report", str(invalid_json)])

            self.assertEqual(context.exception.code, 2)

    def test_cli_prints_strategy_counts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "report.json"
            report_path.write_text(report_to_json(_ready_report()), encoding="utf-8")

            output = StringIO()
            with patch("sys.stdout", output):
                exit_code = main(["--report", str(report_path)])

            self.assertEqual(exit_code, 0)
            self.assertIn("evaluated=1", output.getvalue())
            self.assertIn("detected=1", output.getvalue())
            self.assertIn("risk=APROBADO", output.getvalue())
            self.assertIn("governance=APROBADO", output.getvalue())
            self.assertIn("missing_gates=0", output.getvalue())
            self.assertIn("missing_strategies=0", output.getvalue())

    def test_cli_prints_package_metadata_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            report_path = Path(raw_dir) / "report.json"
            report_path.write_text(
                report_to_json(_error_report_with_package()),
                encoding="utf-8",
            )

            output = StringIO()
            with patch("sys.stdout", output):
                exit_code = main(["--report", str(report_path)])

            self.assertEqual(exit_code, 0)
            self.assertIn("package_id=SPY_2026-06-24", output.getvalue())
            self.assertIn("package_session=2026-06-24", output.getvalue())
            self.assertIn("package_timeframes=15m|1H", output.getvalue())

    def test_cli_directory_can_skip_invalid_reports(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            valid_json = root / "valid.json"
            invalid_json = root / "invalid.json"
            csv_path = root / "audit.csv"
            valid_json.write_text(report_to_json(_ready_report()), encoding="utf-8")
            invalid_json.write_text("{nope", encoding="utf-8")

            exit_code = _run_cli_silently(
                [
                    "--reports-dir",
                    str(root),
                    "--skip-invalid",
                    "--output-csv",
                    str(csv_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "SPY")

    def test_cli_skip_invalid_can_write_empty_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            invalid_json = root / "invalid.json"
            csv_path = root / "audit.csv"
            invalid_json.write_text("{nope", encoding="utf-8")

            exit_code = _run_cli_silently(
                [
                    "--reports-dir",
                    str(root),
                    "--skip-invalid",
                    "--output-csv",
                    str(csv_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            with csv_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, list(AUDIT_FIELDS))
                self.assertEqual(list(reader), [])


if __name__ == "__main__":
    unittest.main()
