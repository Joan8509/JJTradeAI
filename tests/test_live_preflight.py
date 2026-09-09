"""Pruebas del diagnóstico local previo al scanner."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from live_preflight import recent_live_preflights, record_live_preflight, run_live_preflight


class LivePreflightTests(unittest.TestCase):
    def test_ready_local_hides_credentials_and_allows_options_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = run_live_preflight(
                symbols=("SPY",), benchmarks=("QQQ",), days=30,
                database=Path(directory) / "market.db",
                environment={"ALPACA_API_KEY": "super-secret-key", "ALPACA_API_SECRET": "super-secret-value", "ALPACA_DATA_FEED": "iex"},
            )
            self.assertEqual(payload["status"], "LISTO_LOCAL")
            self.assertEqual(payload["network_status"], "PENDIENTE")
            self.assertFalse(payload["secrets_exposed"])
            self.assertEqual(payload["symbols"], ["SPY"])
            self.assertEqual(payload["benchmarks"], ["QQQ"])
            self.assertNotIn("super-secret", str(payload))
            policy = next(item for item in payload["checks"] if item["name"] == "option_policy")
            self.assertEqual(policy["status"], "OMITIDO")

    def test_missing_credentials_delayed_feed_and_invalid_symbol_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = run_live_preflight(
                symbols=("BAD SYMBOL",), benchmarks=(), days=0,
                database=Path(directory) / "market.db",
                environment={"ALPACA_DATA_FEED": "delayed_sip"},
            )
            self.assertEqual(payload["status"], "BLOQUEADO")
            failed = {item["name"] for item in payload["checks"] if item["status"] == "ERROR"}
            self.assertTrue({"symbols", "backfill_days", "credentials", "feed"}.issubset(failed))

    def test_invalid_option_policy_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = run_live_preflight(
                symbols=("SPY",), benchmarks=(), days=30,
                database=Path(directory) / "market.db",
                option_policy=Path(directory) / "missing.json",
                environment={"ALPACA_API_KEY": "key", "ALPACA_API_SECRET": "secret"},
            )
            self.assertEqual(payload["status"], "BLOQUEADO")
            check = next(item for item in payload["checks"] if item["name"] == "option_policy")
            self.assertEqual(check["status"], "ERROR")

    def test_missing_websocket_runtime_blocks_before_network_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "live_preflight.find_spec", return_value=None
        ):
            payload = run_live_preflight(
                symbols=("SPY",), benchmarks=(), days=30,
                database=Path(directory) / "market.db",
                environment={"ALPACA_API_KEY": "key", "ALPACA_API_SECRET": "secret"},
            )

        self.assertEqual(payload["status"], "BLOQUEADO")
        check = next(
            item for item in payload["checks"]
            if item["name"] == "websocket_runtime"
        )
        self.assertEqual(check["status"], "ERROR")

    def test_preflight_history_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            payload = {"status": "LISTO_LOCAL", "checks": [], "secrets_exposed": False}
            run_id = record_live_preflight(database, payload)
            history = recent_live_preflights(database)
            self.assertEqual(history[0]["id"], run_id)
            self.assertEqual(history[0]["payload"]["status"], "LISTO_LOCAL")
            self.assertIs(history[0]["payload"]["secrets_exposed"], False)

    def test_preflight_history_sanitizes_unexpected_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            record_live_preflight(
                database,
                {
                    "status": "BLOQUEADO",
                    "api_secret": "must-not-persist",
                    "checks": [
                        {
                            "name": "remote",
                            "status": "ERROR",
                            "detail": "token=must-not-persist",
                        }
                    ],
                },
            )

            payload = recent_live_preflights(database)[0]["payload"]

        self.assertEqual(payload["api_secret"], "[REDACTED]")
        self.assertNotIn("must-not-persist", str(payload))


if __name__ == "__main__":
    unittest.main()
