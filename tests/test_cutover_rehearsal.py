from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from scripts.rehearse_vps_cutover import exclusive_rows, relation_checks, rehearse, snapshot


class CutoverRehearsalTests(unittest.TestCase):
    def test_exclusive_comparison_uses_column_names_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, pc = root / 'vps.db', root / 'pc.db'
            for path, ddl, rows in (
                (remote, 'CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT)', [(1, 'same'), (2, 'remote-only')]),
                (pc, 'CREATE TABLE events (payload TEXT, id INTEGER PRIMARY KEY AUTOINCREMENT)', [('same', 1)]),
            ):
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(ddl)
                    db.executemany('INSERT INTO events VALUES (?,?)', rows)
            before = remote.read_bytes(), pc.read_bytes()
            result = exclusive_rows(remote, pc)
            self.assertEqual(result['events']['exclusive_distinct_rows'], 1)
            self.assertEqual(before, (remote.read_bytes(), pc.read_bytes()))

    def test_all_foreign_keys_checked_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'db.db'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('CREATE TABLE parent(id INTEGER PRIMARY KEY);'
                                 'CREATE TABLE child(parent_id REFERENCES parent(id));'
                                 'INSERT INTO child VALUES (999);')
            result = relation_checks(path)
            self.assertTrue(result['integrity_ok'])
            self.assertEqual(result['foreign_key_violations_by_table'], {'child': 1})

    def test_snapshot_does_not_change_live_wal_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'db.db'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE events(id INTEGER)')
                db.execute('INSERT INTO events VALUES (123)')
                db.commit()
                result = snapshot(path, root / 'backup.db')
                with closing(sqlite3.connect(root / 'backup.db')) as copy:
                    self.assertEqual(copy.execute('SELECT id FROM events').fetchone()[0], 123)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
                self.assertEqual(len(result['sha256']), 64)

    def test_output_outside_backup_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                rehearse('not_opened', 'not_opened', Path(tmp) / 'output')
            self.assertFalse((Path(tmp) / 'output').exists())
