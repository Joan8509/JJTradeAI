"""Pruebas del validador por lote de paquetes TC2000."""

from contextlib import redirect_stderr, redirect_stdout
import csv
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from analysis_models import GateStatus
from report_auditor import AUDIT_FIELDS, REVIEW_QUEUE_FIELDS, ReportAudit
from validation_batch import (
    INTAKE_CHECK_FIELDS,
    INTAKE_TEMPLATE_FIELDS,
    OPERATOR_BOARD_FIELDS,
    OUTPUT_INSPECTION_FIELDS,
    PACKAGE_INVENTORY_FIELDS,
    SUMMARY_FIELDS,
    ValidationPackage,
    build_operator_board_rows,
    check_case_intake,
    discover_validation_packages,
    inspect_validation_output,
    main,
    run_input_preflight,
    run_batch_validation,
    write_package_inventory,
    write_operator_board_csv,
    write_case_intake_from_input,
    write_case_intake_template,
    _summarize_report,
)


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "exports" / "sample.txt"


def _run_cli_silently(arguments: list[str]) -> int:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        return main(arguments)


def _copy_sample_bundle(root: Path, symbol: str, session: str) -> None:
    for timeframe in ("15m", "1H", "1D"):
        shutil.copyfile(SAMPLE_PATH, root / f"{symbol}_{session}_{timeframe}.txt")


class ValidationBatchTests(unittest.TestCase):
    def test_write_case_intake_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            output_path = Path(raw_output) / "case_intake.csv"

            result = write_case_intake_template(output_path)

            self.assertEqual(result, output_path)
            with output_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, list(INTAKE_TEMPLATE_FIELDS))
            self.assertEqual(rows[0]["symbol"], "SPY")
            self.assertEqual(rows[0]["risk_review_status"], "NO_DISPONIBLE")
            self.assertEqual(rows[0]["paper_trade_taken"], "NO")

    def test_write_package_inventory_marks_missing_timeframes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_path = Path(raw_output) / "package_inventory.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")
                shutil.copyfile(SAMPLE_PATH, input_root / "AAPL_2026-06-24_15m.txt")

                rows = write_package_inventory(
                    input_dir=input_root,
                    output_csv=output_path,
                )

                self.assertEqual(rows[0]["package_id"], "AAPL_2026-06-24")
                self.assertEqual(rows[0]["status"], "INCOMPLETO")
                self.assertEqual(rows[0]["missing_timeframes"], "1H|1D")
                self.assertEqual(rows[1]["status"], "LISTO")
                with output_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    csv_rows = list(reader)
                self.assertEqual(reader.fieldnames, list(PACKAGE_INVENTORY_FIELDS))
                self.assertEqual(csv_rows[1]["available_timeframes"], "15m|1H|1D")

    def test_run_input_preflight_writes_all_control_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                result = run_input_preflight(
                    input_dir=input_root,
                    output_dir=output_root,
                )

                self.assertEqual(result["package_count"], 1)
                self.assertEqual(result["inventory_incomplete"], 0)
                self.assertEqual(result["intake_incomplete"], 0)
                self.assertTrue((output_root / "package_inventory.csv").exists())
                self.assertTrue((output_root / "case_intake.csv").exists())
                self.assertTrue((output_root / "case_intake_check.csv").exists())

    def test_run_input_preflight_counts_incomplete_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                shutil.copyfile(SAMPLE_PATH, input_root / "AAPL_2026-06-24_15m.txt")

                result = run_input_preflight(
                    input_dir=input_root,
                    output_dir=output_root,
                )

                self.assertEqual(result["package_count"], 1)
                self.assertEqual(result["inventory_incomplete"], 1)
                self.assertEqual(result["intake_incomplete"], 1)

    def test_write_case_intake_from_input_uses_discovered_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_path = Path(raw_output) / "case_intake.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")
                shutil.copyfile(SAMPLE_PATH, input_root / "AAPL_2026-06-24_15m.txt")

                result = write_case_intake_from_input(
                    input_dir=input_root,
                    output_csv=output_path,
                )

                self.assertEqual(result, output_path)
                with output_path.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(rows[0]["symbol"], "AAPL")
                self.assertEqual(rows[0]["timeframe_15m_file"], "AAPL_2026-06-24_15m.txt")
                self.assertEqual(rows[0]["timeframe_1h_file"], "")
                self.assertEqual(rows[1]["symbol"], "SPY")
                self.assertEqual(rows[1]["timeframe_1d_file"], "SPY_2026-06-24_1D.txt")

                check_rows = check_case_intake(
                    intake_csv=output_path,
                    input_dir=input_root,
                )
                self.assertEqual(check_rows[0]["status"], "INCOMPLETO")
                self.assertIn(
                    "timeframe_1h_file:NO_DECLARADO",
                    check_rows[0]["missing_files"],
                )

    def test_check_case_intake_marks_ready_and_incomplete_rows(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                intake_path = Path(raw_output) / "intake.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")
                with intake_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=INTAKE_TEMPLATE_FIELDS)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "symbol": "SPY",
                            "session": "2026-06-24",
                            "timeframe_15m_file": "SPY_2026-06-24_15m.txt",
                            "timeframe_1h_file": "SPY_2026-06-24_1H.txt",
                            "timeframe_1d_file": "SPY_2026-06-24_1D.txt",
                        }
                    )
                    writer.writerow(
                        {
                            "symbol": "AAPL",
                            "session": "2026-06-24",
                            "timeframe_15m_file": "AAPL_2026-06-24_15m.txt",
                            "timeframe_1h_file": "AAPL_2026-06-24_1H.txt",
                            "timeframe_1d_file": "AAPL_2026-06-24_1D.txt",
                        }
                    )

                rows = check_case_intake(intake_csv=intake_path, input_dir=input_root)

                self.assertEqual(rows[0]["status"], "LISTO")
                self.assertEqual(rows[1]["status"], "INCOMPLETO")
                self.assertIn("AAPL_2026-06-24_1H.txt", rows[1]["missing_files"])

    def test_check_case_intake_requires_all_timeframe_columns_to_be_filled(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                intake_path = Path(raw_output) / "intake.csv"
                shutil.copyfile(SAMPLE_PATH, input_root / "SPY_2026-06-24_15m.txt")
                with intake_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=INTAKE_TEMPLATE_FIELDS)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "symbol": "SPY",
                            "session": "2026-06-24",
                            "timeframe_15m_file": "SPY_2026-06-24_15m.txt",
                            "timeframe_1h_file": "",
                            "timeframe_1d_file": "",
                        }
                    )

                rows = check_case_intake(intake_csv=intake_path, input_dir=input_root)

                self.assertEqual(rows[0]["status"], "INCOMPLETO")
                self.assertEqual(rows[0]["available_files"], "SPY_2026-06-24_15m.txt")
                self.assertIn(
                    "timeframe_1h_file:NO_DECLARADO",
                    rows[0]["missing_files"],
                )
                self.assertIn(
                    "timeframe_1d_file:NO_DECLARADO",
                    rows[0]["missing_files"],
                )

    def test_check_case_intake_can_write_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                intake_path = Path(raw_output) / "intake.csv"
                output_path = Path(raw_output) / "intake_check.csv"
                write_case_intake_template(intake_path)

                rows = check_case_intake(
                    intake_csv=intake_path,
                    input_dir=input_root,
                    output_csv=output_path,
                )

                self.assertEqual(rows[0]["status"], "INCOMPLETO")
                with output_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    csv_rows = list(reader)
                self.assertEqual(reader.fieldnames, list(INTAKE_CHECK_FIELDS))
                self.assertEqual(csv_rows[0]["status"], "INCOMPLETO")

    def test_discover_packages_groups_by_symbol_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            _copy_sample_bundle(root, "SPY", "2026-06-24")
            shutil.copyfile(SAMPLE_PATH, root / "AAPL_2026-06-24_15m.csv")
            (root / "ignored.txt").write_text("no cumple patrón", encoding="utf-8")

            packages = discover_validation_packages(root)

            self.assertEqual(len(packages), 2)
            self.assertEqual(packages[0].package_id, "AAPL_2026-06-24")
            self.assertEqual(set(packages[1].files), {"15m", "1H", "1D"})

    def test_run_batch_writes_reports_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                rows = run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                )

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["decision"], "NO_OPERAR")
                summary_path = output_root / "summary.csv"
                report_path = output_root / "reports" / "SPY_2026-06-24.json"
                self.assertTrue(summary_path.exists())
                self.assertTrue(report_path.exists())
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["symbol"], "SPY")
                self.assertEqual(payload["data_source"]["provider"], "TC2000_TXT")
                self.assertIn("15m", payload["data_source"]["files"])
                self.assertEqual(
                    payload["validation_package"]["package_id"],
                    "SPY_2026-06-24",
                )
                self.assertEqual(
                    payload["validation_package"]["timeframes"],
                    ["15m", "1D", "1H"],
                )

                with summary_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    summary_rows = list(reader)
                self.assertEqual(summary_rows[0]["package_id"], "SPY_2026-06-24")
                self.assertEqual(reader.fieldnames, list(SUMMARY_FIELDS))
                self.assertGreater(int(summary_rows[0]["evaluated_count"]), 0)
                self.assertEqual(
                    summary_rows[0]["evaluated_count"],
                    str(payload["strategy_summary"]["evaluated"]),
                )
                self.assertEqual(
                    summary_rows[0]["detected_count"],
                    str(payload["strategy_summary"]["detected"]),
                )
                self.assertEqual(
                    summary_rows[0]["confirmed_count"],
                    str(payload["strategy_summary"]["confirmed"]),
                )
                self.assertEqual(
                    summary_rows[0]["skipped_count"],
                    str(payload["strategy_summary"]["skipped"]),
                )
                self.assertEqual(
                    summary_rows[0]["error_count"],
                    str(payload["strategy_summary"]["errors"]),
                )
                self.assertIn("15m:", summary_rows[0]["candle_counts"])
                self.assertIn("decision_data_quality", summary_rows[0])
                self.assertIn("decision_panorama", summary_rows[0])
                self.assertIn("confirmed_count", summary_rows[0])
                self.assertIn("skipped_count", summary_rows[0])
                self.assertIn("tentative_bias", summary_rows[0])
                self.assertIn("tentative_strategies", summary_rows[0])
                self.assertIn("readiness", summary_rows[0])
                self.assertIn("learning_ready", summary_rows[0])
                self.assertIn("missing_gate_count", summary_rows[0])
                self.assertIn("blocker_detector_count", summary_rows[0])
                self.assertEqual(summary_rows[0]["readiness"], "INCOMPLETO")
                self.assertEqual(summary_rows[0]["learning_ready"], "NO")

    def test_run_batch_writes_empty_summary_when_no_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                output_root = Path(raw_output)
                audit_path = output_root / "audit.csv"

                rows = run_batch_validation(
                    input_dir=raw_input,
                    output_dir=output_root,
                    audit_output_csv=audit_path,
                )

                self.assertEqual(rows, ())
                summary_path = output_root / "summary.csv"
                self.assertTrue(summary_path.exists())
                with summary_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(SUMMARY_FIELDS))
                    self.assertEqual(list(reader), [])
                with audit_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(AUDIT_FIELDS))
                    self.assertEqual(list(reader), [])

    def test_summary_normalizes_invalid_strategy_summary_counts(self) -> None:
        package = ValidationPackage(
            symbol="SPY",
            session="2026-06-24",
            files={"15m": Path("SPY_2026-06-24_15m.txt")},
        )
        row = _summarize_report(
            package,
            {
                "data_as_of": "2026-06-24",
                "data_quality": {"status": "APROBADO", "candle_counts": {}},
                "panorama": {"status": "REQUIERE_REVISION"},
                "decision": {
                    "risk_status": "NO_DISPONIBLE",
                    "governance_status": "NO_DISPONIBLE",
                    "decision": "NO_OPERAR",
                    "tentative_bias": "CALL",
                    "tentative_strategies": ["TEST"],
                },
                "strategy_summary": {
                    "evaluated": "n/a",
                    "detected": None,
                    "confirmed": [],
                    "skipped": "dos",
                    "errors": {},
                },
                "strategies": {
                    "evaluations": [
                        {
                            "strategy_id": "TEST",
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
                    ],
                    "skipped": {"X": "faltan datos"},
                    "errors": {"Y": "error"},
                },
            },
            Path("report.json"),
        )

        self.assertEqual(row["evaluated_count"], "1")
        self.assertEqual(row["detected_count"], "1")
        self.assertEqual(row["confirmed_count"], "0")
        self.assertEqual(row["skipped_count"], "1")
        self.assertEqual(row["error_count"], "1")
        self.assertEqual(row["tentative_bias"], "CALL")
        self.assertEqual(row["tentative_strategies"], "TEST")
        self.assertEqual(row["readiness"], "BLOQUEADO")
        self.assertEqual(row["blocker_detector_count"], "1")

    def test_summary_keeps_legacy_tentative_strategy_string(self) -> None:
        package = ValidationPackage(
            symbol="SPY",
            session="2026-06-24",
            files={"15m": Path("SPY_2026-06-24_15m.txt")},
        )
        row = _summarize_report(
            package,
            {
                "data_as_of": "2026-06-24",
                "data_quality": {"status": "APROBADO", "candle_counts": {}},
                "panorama": {"status": "APROBADO"},
                "decision": {
                    "risk_status": "NO_DISPONIBLE",
                    "governance_status": "NO_DISPONIBLE",
                    "decision": "NO_OPERAR",
                    "tentative_strategies": "TEST_PENDING",
                },
                "strategies": {
                    "evaluations": [],
                    "skipped": {},
                    "errors": {},
                },
            },
            Path("report.json"),
        )

        self.assertEqual(row["tentative_strategies"], "TEST_PENDING")

    def test_summary_supports_legacy_top_level_risk_and_governance(self) -> None:
        package = ValidationPackage(
            symbol="SPY",
            session="2026-06-24",
            files={"15m": Path("SPY_2026-06-24_15m.txt")},
        )
        row = _summarize_report(
            package,
            {
                "data_as_of": "2026-06-24",
                "data_quality": {"status": "APROBADO", "candle_counts": {}},
                "panorama": {"status": "APROBADO"},
                "risk": {"status": "RECHAZADO"},
                "governance": {"status": "APROBADO"},
                "decision": {"decision": "NO_OPERAR"},
                "strategies": {
                    "evaluations": [],
                    "skipped": {},
                    "errors": {},
                },
            },
            Path("report.json"),
        )

        self.assertEqual(row["risk"], "RECHAZADO")
        self.assertEqual(row["governance"], "APROBADO")

    def test_run_batch_rejects_missing_input_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            missing_input = Path(raw_output) / "missing"

            with self.assertRaises(ValueError):
                run_batch_validation(
                    input_dir=missing_input,
                    output_dir=Path(raw_output) / "out",
                )

    def test_run_batch_can_require_complete_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                shutil.copyfile(SAMPLE_PATH, input_root / "SPY_2026-06-24_15m.txt")

                with self.assertRaises(ValueError) as context:
                    run_batch_validation(
                        input_dir=input_root,
                        output_dir=Path(raw_output),
                        require_complete_packages=True,
                    )

                self.assertIn("SPY_2026-06-24", str(context.exception))
                self.assertIn("1H", str(context.exception))
                self.assertIn("1D", str(context.exception))

    def test_run_batch_accepts_explicit_gate_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                rows = run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    risk_status=GateStatus.RECHAZADO,
                    governance_status=GateStatus.APROBADO,
                )

                report_path = output_root / "reports" / "SPY_2026-06-24.json"
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(rows[0]["risk"], "RECHAZADO")
                self.assertEqual(rows[0]["governance"], "APROBADO")
                self.assertEqual(payload["decision"]["risk_status"], "RECHAZADO")
                self.assertEqual(
                    payload["decision"]["governance_status"], "APROBADO"
                )

    def test_run_batch_can_write_audit_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                audit_path = output_root / "audit.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                rows = run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    audit_output_csv=audit_path,
                )

                self.assertEqual(len(rows), 1)
                self.assertTrue(audit_path.exists())
                with audit_path.open(encoding="utf-8", newline="") as handle:
                    audit_rows = list(csv.DictReader(handle))
                self.assertEqual(audit_rows[0]["symbol"], "SPY")
                self.assertIn("readiness", audit_rows[0])
                self.assertEqual(audit_rows[0]["package_id"], "SPY_2026-06-24")
                self.assertEqual(audit_rows[0]["package_session"], "2026-06-24")
                self.assertEqual(audit_rows[0]["package_timeframes"], "15m|1D|1H")

    def test_run_batch_can_write_review_queue_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                review_path = output_root / "review_queue.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                rows = run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    review_output_csv=review_path,
                )

                self.assertEqual(len(rows), 1)
                self.assertTrue(review_path.exists())
                with review_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    review_rows = list(reader)
                self.assertEqual(reader.fieldnames, list(REVIEW_QUEUE_FIELDS))
                self.assertTrue(review_rows)
                self.assertEqual(review_rows[0]["symbol"], "SPY")
                self.assertEqual(review_rows[0]["package_id"], "SPY_2026-06-24")

    def test_build_operator_board_rows_combines_summary_and_audit(self) -> None:
        summary = {
            "package_id": "SPY_2026-06-24",
            "symbol": "SPY",
            "session": "2026-06-24",
            "decision": "NO_OPERAR",
            "readiness": "INCOMPLETO",
            "learning_ready": "NO",
            "tentative_bias": "CALL",
            "detected_count": "2",
            "confirmed_count": "0",
            "missing_gate_count": "1",
            "missing_strategy_count": "2",
            "missing_invalidation_count": "1",
            "blocker_gate_count": "0",
            "blocker_invalidation_count": "0",
            "blocker_detector_count": "0",
            "decision_data_quality": "APROBADO",
            "decision_panorama": "REQUIERE_REVISION",
            "risk": "NO_DISPONIBLE",
            "governance": "NO_DISPONIBLE",
            "timeframes": "15m,1H,1D",
            "report_path": "report.json",
        }
        audit = ReportAudit(
            symbol="SPY",
            data_as_of="2026-06-24",
            decision="NO_OPERAR",
            data_quality_status="APROBADO",
            panorama_status="REQUIERE_REVISION",
            risk_status="NO_DISPONIBLE",
            governance_status="NO_DISPONIBLE",
            readiness="INCOMPLETO",
            learning_ready=False,
            missing_evidence=("panorama: REQUIERE_REVISION",),
            blockers=(),
            detected_strategies=("EXPUESTO",),
            first_missing_evidence="panorama: REQUIERE_REVISION",
            package_id="SPY_2026-06-24",
        )

        rows = build_operator_board_rows((summary,), (audit,))

        self.assertEqual(rows[0]["missing_total"], "4")
        self.assertEqual(rows[0]["blocker_total"], "0")
        self.assertEqual(
            rows[0]["first_missing_evidence"],
            "panorama: REQUIERE_REVISION",
        )

    def test_write_operator_board_csv_keeps_header(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            output_path = Path(raw_output) / "operator_board.csv"
            write_operator_board_csv((), (), output_path)

            with output_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, list(OPERATOR_BOARD_FIELDS))
            self.assertEqual(rows, [])

    def test_run_batch_can_write_operator_board_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                board_path = output_root / "operator_board.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                rows = run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    operator_board_output_csv=board_path,
                )

                self.assertEqual(len(rows), 1)
                self.assertTrue(board_path.exists())
                with board_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    board_rows = list(reader)
                self.assertEqual(reader.fieldnames, list(OPERATOR_BOARD_FIELDS))
                self.assertEqual(board_rows[0]["package_id"], "SPY_2026-06-24")
                self.assertEqual(board_rows[0]["decision"], "NO_OPERAR")

    def test_failed_package_writes_auditable_error_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                audit_path = output_root / "audit.csv"
                (input_root / "SPY_2026-06-24_15m.txt").write_text(
                    "",
                    encoding="utf-8",
                )

                rows = run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    audit_output_csv=audit_path,
                )

                report_path = output_root / "reports" / "SPY_2026-06-24.json"
                self.assertEqual(rows[0]["data_quality"], "ERROR")
                self.assertTrue(report_path.exists())
                payload = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["data_quality"]["status"], "ERROR")
                self.assertEqual(
                    payload["validation_package"]["package_id"],
                    "SPY_2026-06-24",
                )
                self.assertEqual(payload["validation_package"]["timeframes"], ["15m"])
                self.assertNotIn("data_source", payload)
                self.assertIn("package", payload["strategies"]["errors"])
                self.assertEqual(payload["decision"]["tentative_bias"], "")
                self.assertEqual(payload["decision"]["tentative_strategies"], [])
                self.assertEqual(rows[0]["readiness"], "BLOQUEADO")
                self.assertEqual(rows[0]["learning_ready"], "NO")
                self.assertEqual(rows[0]["blocker_detector_count"], "1")
                with audit_path.open(encoding="utf-8", newline="") as handle:
                    audit_rows = list(csv.DictReader(handle))
                self.assertEqual(audit_rows[0]["readiness"], "BLOQUEADO")
                self.assertEqual(audit_rows[0]["blocker_detector_count"], "1")

    def test_cli_runs_batch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--output-dir",
                        str(output_root),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue((output_root / "summary.csv").exists())

    def test_cli_can_write_batch_audit_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                audit_path = output_root / "audit.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--output-dir",
                        str(output_root),
                        "--audit-output-csv",
                        str(audit_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue(audit_path.exists())

    def test_cli_can_write_batch_review_queue_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                review_path = output_root / "review_queue.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--output-dir",
                        str(output_root),
                        "--review-output-csv",
                        str(review_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue(review_path.exists())

    def test_cli_can_write_operator_board_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                board_path = output_root / "operator_board.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--output-dir",
                        str(output_root),
                        "--operator-board-output-csv",
                        str(board_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue(board_path.exists())

    def test_cli_standard_output_dir_writes_operational_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--preflight-output-dir",
                        str(output_root),
                        "--run-after-preflight",
                        "--output-dir",
                        str(output_root),
                        "--standard-output-dir",
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue((output_root / "summary.csv").exists())
                self.assertTrue((output_root / "audit.csv").exists())
                self.assertTrue((output_root / "review_queue.csv").exists())
                self.assertTrue((output_root / "operator_board.csv").exists())

    def test_cli_standard_output_dir_requires_output_dir(self) -> None:
        with self.assertRaises(SystemExit) as context:
            _run_cli_silently(["--standard-output-dir"])

        self.assertEqual(context.exception.code, 2)

    def test_inspect_validation_output_accepts_complete_standard_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")
                run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    audit_output_csv=output_root / "audit.csv",
                    review_output_csv=output_root / "review_queue.csv",
                    operator_board_output_csv=output_root / "operator_board.csv",
                )

                rows = inspect_validation_output(output_dir=output_root)

                self.assertTrue(rows)
                self.assertTrue(all(row["status"] in {"LISTO", "REVISION"} for row in rows))
                self.assertTrue(
                    any(row["check"] == "package_ids_operator_board" for row in rows)
                )

    def test_inspect_validation_output_reports_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            output_root = Path(raw_output)

            rows = inspect_validation_output(output_dir=output_root)

            self.assertTrue(any(row["status"] == "FALTA" for row in rows))

    def test_cli_can_write_inspection_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                inspection_path = output_root / "inspection.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")
                run_batch_validation(
                    input_dir=input_root,
                    output_dir=output_root,
                    audit_output_csv=output_root / "audit.csv",
                    review_output_csv=output_root / "review_queue.csv",
                    operator_board_output_csv=output_root / "operator_board.csv",
                )

                exit_code = _run_cli_silently(
                    [
                        "--inspect-output-dir",
                        str(output_root),
                        "--inspection-output-csv",
                        str(inspection_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                with inspection_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    rows = list(reader)
                self.assertEqual(reader.fieldnames, list(OUTPUT_INSPECTION_FIELDS))
                self.assertTrue(rows)

    def test_cli_require_complete_packages_rejects_partial_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                shutil.copyfile(SAMPLE_PATH, input_root / "SPY_2026-06-24_15m.txt")

                with self.assertRaises(SystemExit) as context:
                    _run_cli_silently(
                        [
                            "--input-dir",
                            str(input_root),
                            "--output-dir",
                            str(raw_output),
                            "--require-complete-packages",
                        ]
                    )

                self.assertEqual(context.exception.code, 2)

    def test_cli_can_write_intake_template_without_batch_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            output_path = Path(raw_output) / "case_intake.csv"

            exit_code = _run_cli_silently(
                ["--write-intake-template", str(output_path)]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())

    def test_cli_can_write_intake_from_input_without_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_path = Path(raw_output) / "case_intake.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--write-intake-from-input",
                        str(output_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue(output_path.exists())

    def test_cli_can_write_package_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_path = Path(raw_output) / "package_inventory.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--write-package-inventory",
                        str(output_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue(output_path.exists())

    def test_cli_can_run_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--preflight-output-dir",
                        str(output_root),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue((output_root / "package_inventory.csv").exists())
                self.assertTrue((output_root / "case_intake.csv").exists())
                self.assertTrue((output_root / "case_intake_check.csv").exists())

    def test_cli_can_run_batch_after_clean_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                preflight_root = output_root / "preflight"
                batch_root = output_root / "batch"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--preflight-output-dir",
                        str(preflight_root),
                        "--run-after-preflight",
                        "--output-dir",
                        str(batch_root),
                        "--audit-output-csv",
                        str(batch_root / "audit.csv"),
                        "--review-output-csv",
                        str(batch_root / "review_queue.csv"),
                        "--operator-board-output-csv",
                        str(batch_root / "operator_board.csv"),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue((preflight_root / "package_inventory.csv").exists())
                self.assertTrue((batch_root / "summary.csv").exists())
                self.assertTrue((batch_root / "audit.csv").exists())
                self.assertTrue((batch_root / "review_queue.csv").exists())
                self.assertTrue((batch_root / "operator_board.csv").exists())

    def test_cli_preflight_returns_error_for_incomplete_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                shutil.copyfile(SAMPLE_PATH, input_root / "SPY_2026-06-24_15m.txt")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--preflight-output-dir",
                        str(output_root),
                    ]
                )

                self.assertEqual(exit_code, 1)

    def test_cli_run_after_preflight_stops_before_batch_when_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                output_root = Path(raw_output)
                preflight_root = output_root / "preflight"
                batch_root = output_root / "batch"
                shutil.copyfile(SAMPLE_PATH, input_root / "SPY_2026-06-24_15m.txt")

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--preflight-output-dir",
                        str(preflight_root),
                        "--run-after-preflight",
                        "--output-dir",
                        str(batch_root),
                    ]
                )

                self.assertEqual(exit_code, 1)
                self.assertTrue((preflight_root / "package_inventory.csv").exists())
                self.assertFalse((batch_root / "summary.csv").exists())

    def test_cli_can_check_intake_csv(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                intake_path = Path(raw_output) / "intake.csv"
                output_path = Path(raw_output) / "intake_check.csv"
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")
                write_case_intake_template(intake_path)

                exit_code = _run_cli_silently(
                    [
                        "--input-dir",
                        str(input_root),
                        "--check-intake-csv",
                        str(intake_path),
                        "--intake-check-output-csv",
                        str(output_path),
                    ]
                )

                self.assertEqual(exit_code, 0)
                self.assertTrue(output_path.exists())

    def test_cli_prints_version(self) -> None:
        with self.assertRaises(SystemExit) as context:
            _run_cli_silently(["--version"])

        self.assertEqual(context.exception.code, 0)

    def test_cli_rejects_invalid_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                with self.assertRaises(SystemExit):
                    _run_cli_silently(
                        [
                            "--input-dir",
                            str(input_root),
                            "--output-dir",
                            raw_output,
                            "--risk-status",
                            "LISTO",
                        ]
                    )

    def test_cli_rejects_risk_option_type_without_approved_risk(self) -> None:
        with tempfile.TemporaryDirectory() as raw_input:
            with tempfile.TemporaryDirectory() as raw_output:
                input_root = Path(raw_input)
                _copy_sample_bundle(input_root, "SPY", "2026-06-24")

                with self.assertRaises(SystemExit):
                    _run_cli_silently(
                        [
                            "--input-dir",
                            str(input_root),
                            "--output-dir",
                            raw_output,
                            "--risk-status",
                            "RECHAZADO",
                            "--risk-option-type",
                            "CALL",
                        ]
                    )

    def test_cli_rejects_missing_input_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_output:
            with self.assertRaises(SystemExit) as context:
                _run_cli_silently(
                    [
                        "--input-dir",
                        str(Path(raw_output) / "missing"),
                        "--output-dir",
                        str(Path(raw_output) / "out"),
                    ]
                )

            self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
