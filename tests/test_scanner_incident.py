"""Pruebas de incidentes persistentes del scanner."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from scanner_incident import ScannerIncidentRepository, sanitize_incident_detail


BAR = datetime(2026, 7, 27, 14, 44, tzinfo=timezone.utc)


class ScannerIncidentTests(unittest.TestCase):
    def test_records_redacted_incident_and_resolves_on_later_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ScannerIncidentRepository(Path(directory) / "market.db")
            incident_id = repository.record(
                symbol="spy",
                bar_timestamp=BAR,
                error=RuntimeError(
                    "api_key=abcdefghijklmnopqrstuvwxyz123456 failure"
                ),
            )
            open_incident = repository.recent(unresolved_only=True)[0]

            same_bar = repository.resolve_open(
                symbol="SPY",
                resolution_bar_timestamp=BAR,
            )
            resolved = repository.resolve_open(
                symbol="SPY",
                resolution_bar_timestamp=BAR + timedelta(minutes=15),
            )

            self.assertEqual(open_incident["id"], incident_id)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", open_incident["error_detail"])
            self.assertEqual(len(open_incident["error_fingerprint"]), 64)
            self.assertEqual(same_bar, 0)
            self.assertEqual(resolved, 1)
            self.assertEqual(repository.unresolved_count(), 0)
            self.assertIsNotNone(repository.recent()[0]["resolved_at"])

    def test_incidents_are_isolated_by_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ScannerIncidentRepository(Path(directory) / "market.db")
            repository.record(symbol="SPY", bar_timestamp=BAR, error=ValueError("SPY"))
            repository.record(symbol="QQQ", bar_timestamp=BAR, error=ValueError("QQQ"))
            repository.resolve_open(
                symbol="SPY",
                resolution_bar_timestamp=BAR + timedelta(minutes=15),
            )

            self.assertEqual(repository.unresolved_count(), 1)
            self.assertEqual(repository.unresolved_count(symbols=("SPY",)), 0)
            self.assertEqual(repository.unresolved_count(symbols=("QQQ",)), 1)

    def test_sanitizer_redacts_labeled_and_long_values(self) -> None:
        detail = sanitize_incident_detail(
            "Authorization: Bearer-abcdefghijklmnopqrstuvwxyz token=short"
        )

        self.assertNotIn("Bearer-", detail)
        self.assertNotIn("token=short", detail)
        self.assertIn("[REDACTED]", detail)

    def test_naive_timestamps_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ScannerIncidentRepository(Path(directory) / "market.db")
            with self.assertRaisesRegex(ValueError, "zona horaria"):
                repository.record(
                    symbol="SPY",
                    bar_timestamp=datetime(2026, 7, 27, 10, 0),
                    error=ValueError("bad"),
                )


if __name__ == "__main__":
    unittest.main()
