"""Pruebas de reconexión, recuperación y salud del servicio en vivo."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from live_market import MarketBar
from live_service_runtime import ResilientStreamSupervisor, ServiceHealthRepository


NOW = datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc)


class FakeContinuity:
    provider_name = "ALPACA"
    feed = "iex"

    def __init__(self) -> None:
        self.calls = []

    def recover(self, symbol, *, end, initial_lookback):
        self.calls.append((symbol, end, initial_lookback))
        return 0


class ReturningStream:
    def __init__(self, *, emit_bar=False, fail=False) -> None:
        self.emit_bar = emit_bar
        self.fail = fail
        self.stopped = False

    def run(self, symbols, on_bar, *, on_error=None, on_status=None):
        if self.fail:
            raise ConnectionError("red caída")
        if on_status:
            on_status("CONECTADO")
        if self.emit_bar:
            on_bar(MarketBar("SPY", NOW, 1, 2, 1, 1.5, 10))

    def stop(self):
        self.stopped = True


class LiveServiceRuntimeTests(unittest.TestCase):
    def test_health_repository_tracks_connection_and_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            health = ServiceHealthRepository(Path(directory) / "market.db")
            health.start("scanner", provider="ALPACA", feed="iex", symbols=["spy"])
            health.update("scanner", "CONECTADO", connected=True, bar_timestamp=NOW)

            result = health.get("scanner")

            self.assertEqual(result["status"], "CONECTADO")
            self.assertEqual(result["symbols"], ["SPY"])
            self.assertEqual(result["last_bar_at"], NOW.isoformat())
            self.assertIsNotNone(result["last_connected_at"])

    def test_health_repository_sanitizes_error_before_persisting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            health = ServiceHealthRepository(Path(directory) / "market.db")
            health.start("scanner", provider="ALPACA", feed="iex", symbols=["SPY"])

            health.update(
                "scanner",
                "DESCONECTADO",
                error="Authorization: Bearer-abcdefghijklmnopqrstuvwxyz token=short",
            )
            result = health.get("scanner")

        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", result["last_error"])
        self.assertNotIn("token=short", result["last_error"])
        self.assertIn("[REDACTED]", result["last_error"])

    def test_supervisor_recovers_before_every_connection_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            continuity = FakeContinuity()
            health = ServiceHealthRepository(Path(directory) / "market.db")
            sleeps = []
            supervisor = ResilientStreamSupervisor(
                stream_factory=lambda: ReturningStream(),
                continuity=continuity,
                health=health,
                initial_backoff=1,
                max_backoff=8,
                sleeper=sleeps.append,
                now=lambda: NOW,
            )

            supervisor.run(["SPY", "QQQ"], lambda bar: None, max_attempts=3)

            self.assertEqual(len(continuity.calls), 6)
            self.assertEqual(sleeps, [1, 1])
            self.assertEqual(health.get("live_strategy_scanner")["reconnect_count"], 3)

    def test_failed_connections_use_exponential_backoff_and_preserve_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            continuity = FakeContinuity()
            health = ServiceHealthRepository(Path(directory) / "market.db")
            sleeps = []
            supervisor = ResilientStreamSupervisor(
                stream_factory=lambda: ReturningStream(fail=True),
                continuity=continuity,
                health=health,
                initial_backoff=2,
                max_backoff=4,
                sleeper=sleeps.append,
                now=lambda: NOW,
            )

            supervisor.run(["SPY"], lambda bar: None, max_attempts=3)

            result = health.get("live_strategy_scanner")
            self.assertEqual(sleeps, [2, 4])
            self.assertEqual(result["status"], "DETENIDO")
            self.assertIn("red caída", result["last_error"])

    def test_received_bar_updates_health_and_reaches_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            received = []
            health = ServiceHealthRepository(Path(directory) / "market.db")
            supervisor = ResilientStreamSupervisor(
                stream_factory=lambda: ReturningStream(emit_bar=True),
                continuity=FakeContinuity(),
                health=health,
                sleeper=lambda seconds: None,
                now=lambda: NOW,
            )

            supervisor.run(["SPY"], received.append, max_attempts=1)

            self.assertEqual(len(received), 1)
            self.assertEqual(
                health.get("live_strategy_scanner")["last_bar_at"], NOW.isoformat()
            )


if __name__ == "__main__":
    unittest.main()
