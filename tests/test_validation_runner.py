"""Pruebas del validador reproducible de paquetes TC2000."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from analysis_models import FinalDecision
from data_providers import DataBundle, DataProviderKind
from validation_runner import (
    load_tc2000_bundle,
    main,
    run_validation_bundle_assessment,
    run_validation_assessment,
)


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "exports" / "sample.txt"


def _run_cli_silently(arguments: list[str]) -> int:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        return main(arguments)


class ValidationRunnerTests(unittest.TestCase):
    def test_load_bundle_accepts_available_timeframes(self) -> None:
        datasets = load_tc2000_bundle(
            timeframe_15m=SAMPLE_PATH,
            timeframe_1h=SAMPLE_PATH,
            timeframe_1d=SAMPLE_PATH,
        )

        self.assertEqual(set(datasets), {"15m", "1H", "1D"})
        self.assertIn("bollinger_upper", datasets["15m"].columns)
        self.assertIn("gap_pct", datasets["15m"].columns)

    def test_validation_report_uses_conservative_default_decision(self) -> None:
        datasets = load_tc2000_bundle(
            timeframe_15m=SAMPLE_PATH,
            timeframe_1h=SAMPLE_PATH,
            timeframe_1d=SAMPLE_PATH,
        )
        assessment, report = run_validation_assessment(
            symbol="spy",
            datasets=datasets,
        )

        self.assertEqual(report["symbol"], "SPY")
        self.assertIn("app_version", report)
        self.assertIn("strategies", report)
        self.assertIn("data_quality_status", report["decision"])
        self.assertGreater(report["strategy_summary"]["evaluated"], 0)
        self.assertIs(assessment.decision.decision, FinalDecision.NO_OPERAR)
        self.assertEqual(report["decision"]["decision"], "NO_OPERAR")

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output_path = Path(raw_dir) / "report.json"

            exit_code = main(
                [
                    "--symbol",
                    "SPY",
                    "--tf15",
                    str(SAMPLE_PATH),
                    "--tf1h",
                    str(SAMPLE_PATH),
                    "--tf1d",
                    str(SAMPLE_PATH),
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["symbol"], "SPY")
            self.assertEqual(payload["data_source"]["provider"], "TC2000_TXT")
            self.assertIn("15m", payload["data_source"]["files"])
            self.assertEqual(payload["decision"]["decision"], "NO_OPERAR")

    def test_bundle_report_sanitizes_data_source_metadata(self) -> None:
        datasets = load_tc2000_bundle(timeframe_15m=SAMPLE_PATH)
        bundle = DataBundle(
            provider=DataProviderKind.MARKET_DATA_API,
            datasets=datasets,
            metadata={
                "timeframes": ["BAD", "15m"],
                "files": {"15m": "SPY_15m.txt", "BAD": "ignored.txt"},
                "api_key": "SECRET",
                "authorization": "Bearer SECRET",
            },
        )

        _, report = run_validation_bundle_assessment(symbol="SPY", bundle=bundle)

        self.assertEqual(report["data_source"]["provider"], "MARKET_DATA_API")
        self.assertEqual(report["data_source"]["timeframes"], ["15m"])
        self.assertEqual(report["data_source"]["files"], {"15m": "SPY_15m.txt"})
        self.assertNotIn("api_key", report["data_source"])
        self.assertNotIn("authorization", report["data_source"])

    def test_news_clear_flag_feeds_common_strategy_review(self) -> None:
        datasets = load_tc2000_bundle(
            timeframe_15m=SAMPLE_PATH,
            timeframe_1h=SAMPLE_PATH,
            timeframe_1d=SAMPLE_PATH,
        )

        _, report = run_validation_assessment(
            symbol="SPY",
            datasets=datasets,
            reviews={
                "lateral_jump.lateral_channel": True,
                "lateral_jump.breakout_or_gap": True,
            },
            news_clear=True,
        )
        lateral = next(
            item
            for item in report["strategies"]["evaluations"]
            if item["strategy_id"] == "SIN_SALTO_LATERALIDAD_HORA"
        )
        news_criterion = next(
            item for item in lateral["criteria"] if item["criterion_id"] == "news_clear"
        )

        self.assertEqual(news_criterion["status"], "CUMPLE")

    def test_common_news_review_feeds_panorama_and_invalidations(self) -> None:
        datasets = load_tc2000_bundle(
            timeframe_15m=SAMPLE_PATH,
            timeframe_1h=SAMPLE_PATH,
            timeframe_1d=SAMPLE_PATH,
        )

        _, report = run_validation_assessment(
            symbol="SPY",
            datasets=datasets,
            reviews={"common.news_clear": True},
            panorama_path_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
        )
        news_invalidation = next(
            item
            for item in report["invalidations"]
            if item["criterion_id"] == "relevant_news"
        )

        self.assertEqual(news_invalidation["status"], "NO_CUMPLE")
        self.assertNotIn(
            "No se revisó el calendario de noticias.",
            report["panorama"]["reasons"],
        )

    def test_empty_bundle_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_tc2000_bundle()

    def test_cli_rejects_unreadable_tc2000_file_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            empty_file = Path(raw_dir) / "empty.txt"
            empty_file.write_text("", encoding="utf-8")

            with self.assertRaises(SystemExit) as context:
                _run_cli_silently(
                    ["--symbol", "SPY", "--tf15", str(empty_file)]
                )

            self.assertEqual(context.exception.code, 2)

    def test_cli_lists_review_keys(self) -> None:
        self.assertEqual(_run_cli_silently(["--list-reviews"]), 0)

    def test_cli_prints_version(self) -> None:
        with self.assertRaises(SystemExit) as context:
            _run_cli_silently(["--version"])

        self.assertEqual(context.exception.code, 0)

    def test_cli_rejects_unknown_review_key(self) -> None:
        with self.assertRaises(SystemExit):
            _run_cli_silently(
                [
                    "--symbol",
                    "SPY",
                    "--tf15",
                    str(SAMPLE_PATH),
                    "--review",
                    "ct15.trendline_brokem=si",
                ]
            )

    def test_cli_records_explicit_risk_and_governance_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            output_path = Path(raw_dir) / "report.json"

            exit_code = main(
                [
                    "--symbol",
                    "SPY",
                    "--tf15",
                    str(SAMPLE_PATH),
                    "--tf1h",
                    str(SAMPLE_PATH),
                    "--tf1d",
                    str(SAMPLE_PATH),
                    "--risk-status",
                    "RECHAZADO",
                    "--governance-status",
                    "APROBADO",
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["risk"]["status"], "RECHAZADO")
            self.assertEqual(payload["governance"]["status"], "APROBADO")
            self.assertEqual(payload["decision"]["risk_status"], "RECHAZADO")
            self.assertEqual(payload["decision"]["governance_status"], "APROBADO")

    def test_cli_rejects_invalid_gate_status(self) -> None:
        with self.assertRaises(SystemExit):
            _run_cli_silently(
                [
                    "--symbol",
                    "SPY",
                    "--tf15",
                    str(SAMPLE_PATH),
                    "--risk-status",
                    "LISTO",
                ]
            )

    def test_cli_rejects_invalid_risk_option_type(self) -> None:
        with self.assertRaises(SystemExit):
            _run_cli_silently(
                [
                    "--symbol",
                    "SPY",
                    "--tf15",
                    str(SAMPLE_PATH),
                    "--risk-option-type",
                    "LONG",
                ]
            )

    def test_cli_rejects_risk_option_type_without_approved_risk(self) -> None:
        with self.assertRaises(SystemExit):
            _run_cli_silently(
                [
                    "--symbol",
                    "SPY",
                    "--tf15",
                    str(SAMPLE_PATH),
                    "--risk-status",
                    "RECHAZADO",
                    "--risk-option-type",
                    "CALL",
                ]
            )


if __name__ == "__main__":
    unittest.main()
