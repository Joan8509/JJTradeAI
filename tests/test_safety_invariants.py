"""Pruebas del verificador de invariantes PAPER."""

from pathlib import Path
import tempfile
import unittest

from safety_invariants import audit_safety_invariants, discover_python_sources


class SafetyInvariantsTests(unittest.TestCase):
    def test_clean_read_only_source_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "provider.py"
            source.write_text(
                "def fetch_bars(client):\n    return client.get_bars('SPY')\n",
                encoding="utf-8",
            )

            payload = audit_safety_invariants(directory)

        self.assertEqual(payload["status"], "OK")
        self.assertFalse(payload["order_execution"])

    def test_order_call_import_and_endpoint_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broker.py"
            source.write_text(
                "from alpaca.trading.client import TradingClient\n"
                "URL = 'https://paper-api.alpaca.markets/v2/orders'\n"
                "def act(client):\n"
                "    return client.submit_order(symbol='SPY')\n",
                encoding="utf-8",
            )

            payload = audit_safety_invariants(directory)
            rules = {item["rule"] for item in payload["findings"]}

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertFalse(payload["paper_only"])
        self.assertTrue(payload["order_execution"])
        self.assertEqual(
            rules,
            {"TRADING_IMPORT", "TRADING_ENDPOINT", "ORDER_MUTATION_CALL"},
        )

    def test_learning_import_in_decision_module_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "decision_engine.py"
            source.write_text(
                "from learning_engine import build_learning_advisory\n"
                "def build_decision(strategy_evaluations, learning_score=None):\n"
                "    return learning_score\n",
                encoding="utf-8",
            )

            payload = audit_safety_invariants(directory)
            rules = {item["rule"] for item in payload["findings"]}

        self.assertIn("LEARNING_DECISION_IMPORT", rules)
        self.assertIn("LEARNING_DECISION_PARAMETER", rules)

    def test_transitive_learning_dependency_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "decision_engine.py").write_text(
                "from decision_helper import decide\n"
                "def build_decision(values):\n"
                "    return decide(values)\n",
                encoding="utf-8",
            )
            (root / "decision_helper.py").write_text(
                "from learning_engine import summarize_strategy_performance\n"
                "def decide(values):\n"
                "    return values\n",
                encoding="utf-8",
            )

            payload = audit_safety_invariants(root)
            rules = {item["rule"] for item in payload["findings"]}

        self.assertIn("LEARNING_DECISION_TRANSITIVE", rules)
        self.assertTrue(payload["paper_only"])
        self.assertFalse(payload["learning_isolated"])

    def test_tests_and_operational_directories_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "exports").mkdir()
            (root / "safe.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "unsafe.py").write_text(
                "client.submit_order()\n",
                encoding="utf-8",
            )
            (root / "exports" / "unsafe.py").write_text(
                "client.submit_order()\n",
                encoding="utf-8",
            )

            sources = discover_python_sources(root)

        self.assertEqual([item.name for item in sources], ["safe.py"])


if __name__ == "__main__":
    unittest.main()
