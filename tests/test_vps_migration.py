from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.prepare_vps_migration import digest, prepare, review


class MigrationTests(unittest.TestCase):
    def source(self, root):
        path = root / 'source.db'
        db = sqlite3.connect(path)
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''CREATE TABLE minute_bars (timestamp TEXT);
            CREATE TABLE bollinger_live_events (event_key TEXT PRIMARY KEY);
            CREATE TABLE bollinger_phone_notifications
            (event_key TEXT PRIMARY KEY, state TEXT);''')
        for index, state in enumerate(('ENVIADO', 'ENVIANDO', 'ENVIO_NO_CONFIRMADO')):
            db.execute('INSERT INTO bollinger_phone_notifications VALUES (?,?)', (str(index), state))
        db.commit()
        return path, db

    def test_live_wal_snapshot_preserves_uncertain_claims_and_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, writer = self.source(root)
            try:
                package = root / 'package'
                prepare(source, package)
                before = digest(source)
                result = review(package, source)
                self.assertEqual(before, digest(source))
                self.assertFalse(result['activation_allowed'])
                self.assertEqual(result['incoming']['bollinger_phone_notifications']['states'],
                                 {'ENVIADO': 1, 'ENVIANDO': 1, 'ENVIO_NO_CONFIRMADO': 1})
                with self.assertRaises(FileExistsError):
                    prepare(source, package)
                with (package / 'market_data.db').open('ab') as handle:
                    handle.write(b'tampered')
                with self.assertRaises(ValueError):
                    review(package, source)
            finally:
                writer.close()

    def test_missing_source_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'absent.db'
            with self.assertRaises(ValueError):
                prepare(source, Path(tmp) / 'package')
            self.assertFalse(source.exists())

    def test_missing_dedup_blocks_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'empty.db'
            sqlite3.connect(source).close()
            package = Path(tmp) / 'package'
            with self.assertRaises(ValueError):
                prepare(source, package)
            self.assertFalse((package / 'manifest.json').exists())

    def test_credential_column_blocks_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, db = self.source(root)
            db.execute('CREATE TABLE private_settings (api_key TEXT)')
            db.commit()
            db.close()
            with self.assertRaises(ValueError):
                prepare(source, root / 'package')
            self.assertFalse((root / 'package' / 'manifest.json').exists())
