"""Verifica la seguridad del lanzador de la primera sesion PAPER."""

from pathlib import Path
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "run_first_paper_trial.ps1"
)


class FirstPaperTrialLauncherTests(unittest.TestCase):
    def test_credentials_are_masked_and_removed(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("Read-Host $Prompt -AsSecureString", text)
        self.assertIn("ZeroFreeBSTR", text)
        self.assertIn("Remove-Item Env:ALPACA_API_KEY", text)
        self.assertIn("Remove-Item Env:ALPACA_API_SECRET", text)
        self.assertNotIn("Set-Content", text)
        self.assertNotIn(".env", text)

    def test_runs_preflight_scanner_and_evidence_in_foreground(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("--preflight-only", text)
        self.assertGreaterEqual(text.count('"live_strategy_service.py"'), 2)
        self.assertIn('"paper_session_evidence.py"', text)
        self.assertIn("--max-runtime-minutes $DurationMinutes", text)
        self.assertIn("scanner_control.py stop", text)
        self.assertIn("finally {", text)
        self.assertNotIn("Start-Process", text)

    def test_does_not_pass_credentials_as_command_arguments(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        command_lines = [
            line
            for line in text.splitlines()
            if "& $python" in line or line.strip().startswith("--")
        ]

        self.assertNotIn("ALPACA_API_KEY", "\n".join(command_lines))
        self.assertNotIn("ALPACA_API_SECRET", "\n".join(command_lines))


if __name__ == "__main__":
    unittest.main()
