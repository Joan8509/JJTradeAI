"""Bounded hints from isolated SQLite; no production database or broker."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
from unittest import TestCase
from unittest.mock import patch
from real_entry_signal_hints import entry_signal_symbols


class EntrySignalHintsTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'isolated.db'
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE bollinger_tick_latest(symbol TEXT PRIMARY KEY,payload_json TEXT)')
            db.executemany('INSERT INTO bollinger_tick_latest VALUES(?,?)',[
                ('SLV',json.dumps(dict(reason='EXIT',signal={'side':'INFERIOR'}))),
                ('AAPL',json.dumps(dict(reason='INSIDE',signal=None)))])

    def test_one_indexed_read_selects_signal_and_retains_missing_symbols(self):
        before=hashlib.sha256(self.path.read_bytes()).digest()
        with patch('real_entry_signal_hints.sqlite3.connect',wraps=sqlite3.connect) as connect:
            self.assertEqual(entry_signal_symbols(self.path,['AAPL','SLV','MISSING']),{'SLV','MISSING'})
            connect.assert_called_once()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(),before)

    def test_missing_database_falls_back_and_is_never_created(self):
        missing=self.path.with_name('missing.db')
        self.assertIsNone(entry_signal_symbols(missing,['SLV']))
        self.assertFalse(missing.exists())

    def test_corrupt_payload_requests_full_validation_instead_of_empty_result(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE bollinger_tick_latest SET payload_json='INVALID' WHERE symbol='SLV'")
        self.assertIsNone(entry_signal_symbols(self.path,['AAPL','SLV']))

    def test_empty_and_oversized_requests_do_not_query_database(self):
        self.assertEqual(entry_signal_symbols(self.path,[]),set())
        self.assertIsNone(entry_signal_symbols(self.path,[str(i) for i in range(101)]))

    def test_locked_database_falls_back_without_a_multi_second_wait(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('BEGIN EXCLUSIVE')
            self.assertIsNone(entry_signal_symbols(self.path,['SLV']))
            db.rollback()
