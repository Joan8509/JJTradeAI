"""Pruebas del ensayo PAPER sintetico de infraestructura."""

from pathlib import Path
import tempfile
import unittest

from paper_rehearsal import run_paper_rehearsal


class PaperRehearsalTests(unittest.TestCase):
    def test_runs_end_to_end_without_claiming_real_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = run_paper_rehearsal(Path(directory) / "rehearsal.db")

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["persisted_bar_count"], 15)
        self.assertEqual(payload["event_type"], "SETUP_CONFIRMADO")
        self.assertEqual(payload["reconciliation_status"], "APROBADO")
        self.assertEqual(payload["pending_acknowledgement_count"], 0)
        self.assertTrue(all(payload["checks"].values()))
        self.assertTrue(payload["synthetic"])
        self.assertFalse(payload["methodology_validated"])
        self.assertFalse(payload["real_market_validated"])
        self.assertFalse(payload["order_execution"])

    def test_rejects_an_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "existing.db"
            database.touch()

            with self.assertRaisesRegex(ValueError, "base de datos nueva"):
                run_paper_rehearsal(database)


if __name__ == "__main__":
    unittest.main()
