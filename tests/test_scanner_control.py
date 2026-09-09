"""Pruebas del controlador local sin lanzar conexiones reales."""

from pathlib import Path
import tempfile
import unittest

from scanner_control import build_scanner_arguments, start_scanner
from scanner_instance import ScannerInstanceLease


class FakeProcess:
    pid = 4321


class ScannerControlTests(unittest.TestCase):
    def test_build_arguments_normalizes_symbols_and_uses_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            arguments = build_scanner_arguments(
                symbols="qqq, SPY,spy", days=30,
                database=Path(directory) / "market.db",
            )
            self.assertEqual(arguments[:4], ["--symbols", "QQQ,SPY", "--days", "30"])
            self.assertEqual(arguments[4], "--database")

    def test_build_arguments_rejects_invalid_symbol_days_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            with self.assertRaisesRegex(ValueError, "símbolos"):
                build_scanner_arguments(symbols="SPY & calc", days=30, database=database)
            with self.assertRaisesRegex(ValueError, "backfill"):
                build_scanner_arguments(symbols="SPY", days=0, database=database)
            with self.assertRaisesRegex(ValueError, "política"):
                build_scanner_arguments(
                    symbols="SPY", days=30, database=database,
                    option_policy=Path(directory) / "missing.json",
                )

    def test_start_builds_detached_command_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def fake_popen(command, **kwargs):
                calls.append((command, kwargs))
                return FakeProcess()

            result = start_scanner(
                ["--symbols", "SPY,QQQ"],
                lock_file=Path(directory) / "scanner.lock",
                log_file=Path(directory) / "scanner.log",
                python_executable="python-test",
                popen_factory=fake_popen,
            )
            self.assertEqual(result["status"], "INICIANDO")
            self.assertEqual(result["pid"], 4321)
            self.assertEqual(calls[0][0][0], "python-test")
            self.assertIn("live_strategy_service.py", calls[0][0][1])
            self.assertEqual(calls[0][0][-2:], ["--symbols", "SPY,QQQ"])
            self.assertTrue(Path(result["log_path"]).exists())

    def test_start_passes_credentials_to_child_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def fake_popen(command, **kwargs):
                calls.append((command, kwargs))
                return FakeProcess()

            start_scanner(
                ["--symbols", "SPY"],
                lock_file=Path(directory) / "scanner.lock",
                log_file=Path(directory) / "scanner.log",
                environment={"ALPACA_API_KEY": "test-key", "ALPACA_API_SECRET": "test-secret"},
                popen_factory=fake_popen,
            )
            child_environment = calls[0][1]["env"]
            self.assertEqual(child_environment["ALPACA_API_KEY"], "test-key")
            self.assertEqual(child_environment["ALPACA_API_SECRET"], "test-secret")

    def test_start_refuses_active_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "scanner.lock"
            lease = ScannerInstanceLease(lock)
            lease.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "ya está activo"):
                    start_scanner([], lock_file=lock, log_file=Path(directory) / "scanner.log")
            finally:
                lease.release()


if __name__ == "__main__":
    unittest.main()
