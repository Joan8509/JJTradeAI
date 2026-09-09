"""Pruebas del guardia previo a publicar en GitHub privado."""

import csv
from pathlib import Path
import tempfile
import unittest

from prepublish_check import (
    build_manifest_rows,
    find_blocked_candidates,
    write_manifest_csv,
)


class PrepublishCheckTests(unittest.TestCase):
    def test_blocks_sensitive_export_and_secret_candidates(self) -> None:
        findings = find_blocked_candidates(
            [
                "app.py",
                "exports/jjtrade_journal.db",
                "exports/backups/market_20260722.db",
                "exports/live_scanner.lock",
                "exports/live_scanner.stop",
                "exports/live_scanner.log",
                "exports/tc2000_cases/SPY_2026-06-21_15m.txt",
                "exports/release_health.json",
                "exports/github_readiness.json",
                "exports/safety_invariants.json",
                ".env",
                "private_token.txt",
            ]
        )

        self.assertEqual(
            [finding.path for finding in findings],
            [
                "exports/jjtrade_journal.db",
                "exports/backups/market_20260722.db",
                "exports/live_scanner.lock",
                "exports/live_scanner.stop",
                "exports/live_scanner.log",
                "exports/tc2000_cases/SPY_2026-06-21_15m.txt",
                "exports/release_health.json",
                "exports/github_readiness.json",
                "exports/safety_invariants.json",
                ".env",
                "private_token.txt",
            ],
        )

    def test_allows_sample_fixture_export(self) -> None:
        findings = find_blocked_candidates(
            [
                "exports/sample.txt",
                "EXPORTS/SAMPLE.TXT",
                "tests/test_validation_runner.py",
            ]
        )

        self.assertEqual(findings, [])

    def test_blocks_sensitive_candidates_case_insensitively(self) -> None:
        findings = find_blocked_candidates(
            [
                ".ENV",
                "PRIVATE_TOKEN.TXT",
                "exports/JJTRADE_JOURNAL.DB",
                "EXPORTS/TC2000_CASES/SPY_15M.TXT",
            ]
        )

        self.assertEqual(
            [finding.path for finding in findings],
            [
                ".ENV",
                "PRIVATE_TOKEN.TXT",
                "exports/JJTRADE_JOURNAL.DB",
                "EXPORTS/TC2000_CASES/SPY_15M.TXT",
            ],
        )

    def test_blocks_nested_env_and_credentials_candidates(self) -> None:
        findings = find_blocked_candidates(
            [
                "config/.env",
                "config/.env.local",
                "secrets/credentials.json",
                "ops/aws_credentials.csv",
                r"nested\service_credentials.pem",
            ]
        )

        self.assertEqual(
            [finding.path for finding in findings],
            [
                "config/.env",
                "config/.env.local",
                "secrets/credentials.json",
                "ops/aws_credentials.csv",
                "nested/service_credentials.pem",
            ],
        )

    def test_normalizes_windows_paths(self) -> None:
        findings = find_blocked_candidates(
            [r"exports\tc2000_cases\case_intake.csv"]
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "exports/tc2000_cases/case_intake.csv")

    def test_manifest_rows_mark_blocked_and_ok_candidates(self) -> None:
        candidates = ["app.py", ".env"]
        findings = find_blocked_candidates(candidates)

        rows = build_manifest_rows(candidates, findings)

        self.assertEqual(rows[0].path, ".env")
        self.assertEqual(rows[0].status, "BLOQUEADO")
        self.assertEqual(rows[0].matched_pattern, ".env")
        self.assertEqual(rows[1].path, "app.py")
        self.assertEqual(rows[1].status, "OK")

    def test_write_manifest_csv_creates_parent_directories(self) -> None:
        candidates = ["app.py", ".env"]
        findings = find_blocked_candidates(candidates)
        rows = build_manifest_rows(candidates, findings)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit" / "manifest.csv"
            write_manifest_csv(output, rows)

            with output.open(encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))

        self.assertEqual(csv_rows[0]["path"], ".env")
        self.assertEqual(csv_rows[0]["status"], "BLOQUEADO")
        self.assertEqual(csv_rows[1]["path"], "app.py")
        self.assertEqual(csv_rows[1]["status"], "OK")


if __name__ == "__main__":
    unittest.main()
