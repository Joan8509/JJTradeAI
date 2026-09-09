"""Pruebas del paquete de recuperacion de evidencia visual."""

from pathlib import Path
import tempfile
import unittest
import zipfile

from database_backup import create_sqlite_backup
from live_strategy_service import AlertRepository
from tests.test_visual_evidence import png
from visual_evidence import VisualEvidenceRepository
from visual_evidence_backup import (
    create_visual_evidence_backup,
    restore_visual_evidence_backup,
    verify_visual_evidence_backup,
)


class VisualEvidenceBackupTests(unittest.TestCase):
    def _fixture(self, directory: str):
        root = Path(directory)
        database = root / "market.db"
        alert_id = AlertRepository(database).record(
            provider="ALPACA",
            feed="iex",
            symbol="SPY",
            trigger_timestamp=__import__("datetime").datetime(
                2026, 7, 27, 14, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            report={
                "data_as_of": "2026-07-27T14:00:00+00:00",
                "decision": {"decision": "NO_OPERAR"},
                "strategy_summary": {"detected": 1, "confirmed": 0},
            },
        )
        visual_root = root / "visual"
        repository = VisualEvidenceRepository(database, visual_root)
        repository.record(
            int(alert_id),
            timeframe="15m",
            filename="chart.png",
            content=png(),
        )
        database_backup = create_sqlite_backup(database, root / "backups")
        return database_backup, visual_root

    def test_creates_verifies_and_restores_matching_visual_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_backup, visual_root = self._fixture(directory)
            bundle = create_visual_evidence_backup(
                database_backup["backup_path"], visual_root
            )
            verification = verify_visual_evidence_backup(
                bundle["backup_path"],
                expected_database_sha256=database_backup["sha256"],
            )
            restored_root = Path(directory) / "restored_visual"
            restored = restore_visual_evidence_backup(
                bundle["backup_path"],
                restored_root,
                expected_database_sha256=database_backup["sha256"],
            )

            self.assertEqual(verification["status"], "OK")
            self.assertEqual(verification["evidence_count"], 1)
            self.assertEqual(restored["restored_count"], 1)
            self.assertEqual(len(list(restored_root.glob("*.png"))), 1)

    def test_missing_or_changed_source_blocks_bundle_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_backup, visual_root = self._fixture(directory)
            image = next(visual_root.glob("*.png"))
            image.write_bytes(png(800, 450))

            with self.assertRaisesRegex(ValueError, "SHA-256"):
                create_visual_evidence_backup(
                    database_backup["backup_path"], visual_root
                )

    def test_wrong_database_hash_blocks_verification_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_backup, visual_root = self._fixture(directory)
            bundle = create_visual_evidence_backup(
                database_backup["backup_path"], visual_root
            )

            verification = verify_visual_evidence_backup(
                bundle["backup_path"], expected_database_sha256="0" * 64
            )

            self.assertEqual(verification["status"], "BLOQUEADO")
            with self.assertRaisesRegex(ValueError, "no corresponde"):
                restore_visual_evidence_backup(
                    bundle["backup_path"],
                    Path(directory) / "restored",
                    expected_database_sha256="0" * 64,
                )

    def test_restore_never_overwrites_conflicting_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_backup, visual_root = self._fixture(directory)
            bundle = create_visual_evidence_backup(
                database_backup["backup_path"], visual_root
            )
            verification = verify_visual_evidence_backup(bundle["backup_path"])
            relative = verification["manifest"]["files"][0]["relative_path"]
            target = Path(directory) / "restore"
            conflicting = target / relative
            conflicting.parent.mkdir(parents=True)
            conflicting.write_bytes(png(800, 450))

            with self.assertRaisesRegex(ValueError, "no se sobrescribe"):
                restore_visual_evidence_backup(bundle["backup_path"], target)

    def test_undeclared_archive_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_backup, visual_root = self._fixture(directory)
            bundle = create_visual_evidence_backup(
                database_backup["backup_path"], visual_root
            )
            with zipfile.ZipFile(bundle["backup_path"], "a") as archive:
                archive.writestr("../unexpected.txt", "bad")

            with self.assertRaisesRegex(ValueError, "no declaradas"):
                verify_visual_evidence_backup(bundle["backup_path"])


if __name__ == "__main__":
    unittest.main()
