"""Pruebas de backup consistente, huella y retención SQLite."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from database_backup import (create_sqlite_backup, restore_sqlite_backup,
                             verify_sqlite_backup, backup_read_snapshot)


class DatabaseBackupTests(unittest.TestCase):
    def test_snapshot_stays_consistent_while_external_wal_writer_commits_during_copy(self):
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            source=self._database(directory)
            with closing(sqlite3.connect(source)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('CREATE TABLE padding (payload BLOB)')
                writer.executemany('INSERT INTO padding VALUES (?)',[(b'x'*8192,)]*64)
                writer.commit()
                with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as reader, \
                     closing(sqlite3.connect(Path(directory)/'isolated.db')) as destination:
                    progress_calls=[]
                    def progress(status,remaining,total):
                        progress_calls.append((status,remaining,total))
                        if len(progress_calls)==1:
                            writer.execute("INSERT INTO events(value) VALUES ('during backup')")
                            writer.commit()
                    backup_read_snapshot(reader,destination,pages=1,progress=progress)
                    self.assertFalse(reader.in_transaction)
                    self.assertGreater(len(progress_calls),2)
                    self.assertEqual(destination.execute('SELECT count(*) FROM events').fetchone()[0],1)
                    self.assertEqual(writer.execute('SELECT count(*) FROM events').fetchone()[0],2)
                    self.assertEqual(destination.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    remaining=[r[1] for r in progress_calls]
                    self.assertEqual(remaining,sorted(remaining,reverse=True))

    def test_snapshot_does_not_rollback_an_existing_caller_transaction(self):
        from contextlib import closing
        with closing(sqlite3.connect(':memory:')) as source, closing(sqlite3.connect(':memory:')) as target:
            source.execute('BEGIN')
            with self.assertRaises(ValueError):backup_read_snapshot(source,target)
            self.assertTrue(source.in_transaction)

    def _database(self, directory: str) -> Path:
        path = Path(directory) / "market.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO events (value) VALUES ('alerta')")
            connection.commit()
        finally:
            connection.close()
        return path

    def test_backup_is_integral_hashed_and_queryable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            result = create_sqlite_backup(source, Path(directory) / "backups")
            backup = Path(result["backup_path"])
            self.assertTrue(backup.is_file())
            self.assertTrue(Path(result["manifest_path"]).is_file())
            self.assertEqual(len(result["sha256"]), 64)
            self.assertEqual(verify_sqlite_backup(backup, expected_sha256=result["sha256"])["status"], "OK")
            connection = sqlite3.connect(backup)
            try:
                self.assertEqual(connection.execute("SELECT value FROM events").fetchone()[0], "alerta")
            finally:
                connection.close()

    def test_retention_removes_only_old_matching_backups_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            root = Path(directory) / "backups"
            for _ in range(3):
                create_sqlite_backup(source, root, retention=2)
            self.assertEqual(len(list(root.glob("market_*.db"))), 2)
            self.assertEqual(len(list(root.glob("market_*.json"))), 2)
            unrelated = root / "other_file.txt"
            unrelated.write_text("preservar", encoding="utf-8")
            create_sqlite_backup(source, root, retention=1)
            self.assertTrue(unrelated.exists())

    def test_wrong_hash_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            result = create_sqlite_backup(source, Path(directory) / "backups")
            verification = verify_sqlite_backup(result["backup_path"], expected_sha256="0" * 64)
            self.assertEqual(verification["status"], "BLOQUEADO")
            self.assertFalse(verification["hash_matches"])

    def test_restore_to_new_target_preserves_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            backup = create_sqlite_backup(source, Path(directory) / "backups")
            target = Path(directory) / "restored" / "market.db"
            result = restore_sqlite_backup(backup["backup_path"], target)
            self.assertEqual(result["status"], "RESTAURADO")
            self.assertIsNone(result["safety_backup_path"])
            connection = sqlite3.connect(target)
            try:
                self.assertEqual(connection.execute("SELECT value FROM events").fetchone()[0], "alerta")
            finally:
                connection.close()

    def test_existing_target_requires_overwrite_and_gets_safety_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            backup = create_sqlite_backup(source, Path(directory) / "backups")
            target = Path(directory) / "target.db"
            connection = sqlite3.connect(target)
            try:
                connection.execute("CREATE TABLE old_data (value TEXT)")
                connection.execute("INSERT INTO old_data VALUES ('preservar')")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "--overwrite"):
                restore_sqlite_backup(backup["backup_path"], target)
            result = restore_sqlite_backup(
                backup["backup_path"], target, overwrite=True,
                safety_backup_directory=Path(directory) / "safety",
            )
            self.assertTrue(Path(result["safety_backup_path"]).is_file())
            connection = sqlite3.connect(result["safety_backup_path"])
            try:
                self.assertEqual(connection.execute("SELECT value FROM old_data").fetchone()[0], "preservar")
            finally:
                connection.close()

    def test_restore_requires_valid_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            backup = create_sqlite_backup(source, Path(directory) / "backups")
            Path(backup["manifest_path"]).unlink()
            with self.assertRaisesRegex(ValueError, "manifiesto"):
                restore_sqlite_backup(backup["backup_path"], Path(directory) / "restored.db")

    def test_retention_removes_visual_bundle_paired_with_old_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._database(directory)
            root = Path(directory) / "backups"
            first = create_sqlite_backup(source, root, retention=10)
            paired_visual = Path(first["backup_path"]).with_suffix(".visual.zip")
            paired_visual.write_bytes(b"paired")
            create_sqlite_backup(source, root, retention=1)

            self.assertFalse(Path(first["backup_path"]).exists())
            self.assertFalse(paired_visual.exists())


if __name__ == "__main__":
    unittest.main()
