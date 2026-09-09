"""Pruebas del health check local de release."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from release_health_check import (
    HealthCheck,
    build_checks,
    health_payload,
    run_check,
    run_health_checks,
    write_json_output,
)


class ReleaseHealthCheckTests(unittest.TestCase):
    def test_build_checks_uses_current_python_for_project_commands(self) -> None:
        checks = build_checks("python-test")

        self.assertEqual(checks[0].command, ("python-test", "-m", "unittest", "discover", "tests"))
        self.assertIn(HealthCheck("prepublish", ("python-test", "prepublish_check.py")), checks)
        self.assertIn(
            HealthCheck(
                "validation_runner_version",
                ("python-test", "validation_runner.py", "--version"),
            ),
            checks,
        )
        self.assertIn(
            HealthCheck(
                "live_strategy_service_cli",
                ("python-test", "live_strategy_service.py", "--help"),
            ),
            checks,
        )
        self.assertIn(
            HealthCheck(
                "database_backup_cli",
                ("python-test", "database_backup.py", "--help"),
            ),
            checks,
        )
        self.assertIn(
            HealthCheck("beta_status_cli", ("python-test", "beta_status.py", "--help")),
            checks,
        )
        self.assertIn(
            HealthCheck("paper_rehearsal", ("python-test", "paper_rehearsal.py")),
            checks,
        )
        self.assertIn(
            HealthCheck(
                "paper_session_evidence_cli",
                ("python-test", "paper_session_evidence.py", "--help"),
            ),
            checks,
        )
        self.assertIn(
            HealthCheck(
                "visual_evidence_backup_cli",
                ("python-test", "visual_evidence_backup.py", "--help"),
            ),
            checks,
        )
        self.assertIn(
            HealthCheck(
                "methodology_coverage",
                ("python-test", "methodology_coverage.py"),
            ),
            checks,
        )
        self.assertIn(
            HealthCheck(
                "safety_invariants",
                ("python-test", "safety_invariants.py"),
            ),
            checks,
        )

    def test_run_check_combines_stdout_and_stderr(self) -> None:
        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="ok\n",
                stderr="warning\n",
            )

        result = run_check(HealthCheck("demo", ("cmd",)), runner=runner)

        self.assertTrue(result.passed)
        self.assertEqual(result.output, "ok\nwarning")

    def test_run_health_checks_preserves_failed_result(self) -> None:
        def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom")

        results = run_health_checks(
            [HealthCheck("failing", ("cmd",))],
            runner=runner,
        )

        self.assertFalse(results[0].passed)
        self.assertEqual(results[0].returncode, 1)
        self.assertEqual(results[0].output, "boom")

    def test_health_payload_counts_failed_checks(self) -> None:
        results = [
            run_check(
                HealthCheck("ok", ("cmd",)),
                runner=lambda command: subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="fine",
                    stderr="",
                ),
            ),
            run_check(
                HealthCheck("bad", ("cmd",)),
                runner=lambda command: subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr="nope",
                ),
            ),
        ]

        payload = health_payload(results)

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertEqual(payload["check_count"], 2)
        self.assertEqual(payload["failed_count"], 1)
        self.assertEqual(payload["checks"][0]["status"], "OK")
        self.assertEqual(payload["checks"][1]["status"], "ERROR")

    def test_write_json_output_creates_parent_directory(self) -> None:
        payload = {"status": "OK", "check_count": 0}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "release.json"
            write_json_output(output, payload)
            loaded = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
