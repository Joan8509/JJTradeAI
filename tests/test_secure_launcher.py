"""Verifica que el lanzador no convierta credenciales en archivos persistentes."""

from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "start_jjtrade_secure.ps1"


class SecureLauncherTests(unittest.TestCase):
    def test_prompts_masked_values_clears_memory_and_removes_environment(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Read-Host $Prompt -AsSecureString", text)
        self.assertIn("ZeroFreeBSTR", text)
        self.assertIn("Remove-Item Env:ALPACA_API_KEY", text)
        self.assertIn("Remove-Item Env:ALPACA_API_SECRET", text)
        self.assertNotIn("Set-Content", text)
        self.assertNotIn(".env", text)

    def test_launcher_supports_preflight_and_streamlit(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("[switch]$PreflightOnly", text)
        self.assertIn("live_strategy_service.py", text)
        self.assertIn("-m streamlit run", text)


if __name__ == "__main__":
    unittest.main()
