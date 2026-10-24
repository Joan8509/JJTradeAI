from contextlib import closing
import hashlib,json,shutil,sqlite3,subprocess,sys,tempfile,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from scripts.configure_sqlite_runtime import install,rollback,FILENAMES,VERSION,DLL_SHA256
from sqlite_runtime_guard import supports_safe_wal,require_safe_wal_runtime

ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'exports/sqlite_runtime'/VERSION/'sqlite3.dll'

class RuntimeGuardTests(unittest.TestCase):
    def test_official_fixed_versions_and_affected_builds(self):
        for version in ((3,50,7),(3,44,6),(3,51,3),(3,54,1)):self.assertTrue(supports_safe_wal(version))
        for version in ((3,50,4),(3,51,2),(3,44,5)):self.assertFalse(supports_safe_wal(version))
    def test_older_runtime_still_accepts_delete_without_creating_missing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'data.db'
            with patch('sqlite_runtime_guard.sqlite3.sqlite_version_info',(3,50,4)):require_safe_wal_runtime(db)
            self.assertFalse(db.exists())
            with closing(sqlite3.connect(db)) as conn:conn.execute('CREATE TABLE probe(id INTEGER)')
            with patch('sqlite_runtime_guard.sqlite3.sqlite_version_info',(3,50,4)):require_safe_wal_runtime(db)
    @unittest.skipUnless(supports_safe_wal(sqlite3.sqlite_version_info),'Requires fixed WAL build')
    def test_affected_runtime_refuses_wal_without_mutating_data(self):
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'data.db'
            with closing(sqlite3.connect(db)) as conn,conn:
                conn.execute('PRAGMA journal_mode=WAL');conn.execute('CREATE TABLE probe(id INTEGER)');conn.execute('INSERT INTO probe VALUES(7)')
                with patch('sqlite_runtime_guard.sqlite3.sqlite_version_info',(3,50,4)):
                    with self.assertRaisesRegex(RuntimeError,'SQLITE_WAL_RUNTIME_UNSAFE'):require_safe_wal_runtime(db)
                self.assertEqual(conn.execute('SELECT id FROM probe').fetchall(),[(7,)])

@unittest.skipUnless(sys.platform=='win32' and NATIVE.is_file(),'Prepared official DLL required; never fetched by tests')
class PrivatePreloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.site=self.root/'venv/Lib/site-packages';self.site.mkdir(parents=True)
        binary=self.root/'exports/sqlite_runtime'/VERSION/'sqlite3.dll';binary.parent.mkdir(parents=True);shutil.copyfile(NATIVE,binary)
        self.db=self.root/'exports/market_data.db'
        with closing(sqlite3.connect(self.db)) as conn,conn:conn.execute('CREATE TABLE probe(id INTEGER)');conn.execute('INSERT INTO probe VALUES(7)')
    def child(self,prefix=''):
        code='import sys;sys.path.insert(0,'+repr(str(self.site))+');'+prefix+'import jjtrade_sqlite_preload;jjtrade_sqlite_preload.activate();import sqlite3;print(sqlite3.sqlite_version)'
        return subprocess.run([sys.executable,'-S','-c',code],capture_output=True,timeout=20)
    def test_install_load_and_rollback_preserve_database_bytes(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        install(self.root);result=self.child()
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'));self.assertEqual(result.stdout.decode().strip(),VERSION)
        rollback(self.root)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
        self.assertFalse(any((self.site/n).exists() for n in FILENAMES))
    def test_missing_config_cannot_fall_back_to_old_sqlite(self):
        install(self.root);(self.site/'jjtrade_sqlite_runtime.json').unlink()
        result=self.child();self.assertEqual(result.returncode,78);self.assertIn(b'JJTRADE_SQLITE_RUNTIME_BLOCKED',result.stderr)
    def test_tampered_dll_is_rejected_before_loading(self):
        install(self.root);(self.root/'exports/sqlite_runtime'/VERSION/'sqlite3.dll').write_bytes(b'invalid fixture')
        self.assertEqual(self.child().returncode,78)
    def test_already_imported_sqlite_cannot_silently_use_another_build(self):
        install(self.root);self.assertEqual(self.child('import sqlite3;').returncode,78)
    def test_unknown_pth_is_preserved_for_review(self):
        pth=self.site/FILENAMES[0];pth.write_text('owner change')
        with self.assertRaisesRegex(ValueError,'EXISTING_RUNTIME_REQUIRES_REVIEW'):install(self.root)
        self.assertEqual(pth.read_text(),'owner change')
    def test_rollback_does_not_discard_local_edits(self):
        install(self.root);target=self.site/FILENAMES[2];target.write_text('owner change')
        with self.assertRaisesRegex(ValueError,'LOCAL_CHANGES_REQUIRE_REVIEW'):rollback(self.root)
        self.assertEqual(target.read_text(),'owner change')
    @unittest.skipUnless(supports_safe_wal(sqlite3.sqlite_version_info),'Requires fixed WAL build')
    def test_rollback_refuses_to_remove_runtime_while_wal_is_active(self):
        install(self.root)
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            with self.assertRaisesRegex(ValueError,'CHECKPOINT_AND_DELETE_REQUIRED'):rollback(self.root)
            self.assertTrue((self.site/FILENAMES[0]).exists())
            conn.execute('PRAGMA journal_mode=DELETE')
        rollback(self.root)

@unittest.skipUnless(supports_safe_wal(sqlite3.sqlite_version_info),'Requires fixed WAL build')
class DurableWalTests(unittest.TestCase):
    def test_backup_of_wal_source_is_portable_and_preserves_relations(self):
        from database_backup import create_sqlite_backup
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source.db'
            with closing(sqlite3.connect(source)) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.executescript('CREATE TABLE parent(id INTEGER PRIMARY KEY);CREATE TABLE child(id INTEGER REFERENCES parent(id));INSERT INTO parent VALUES(7);INSERT INTO child VALUES(7);')
                receipt=create_sqlite_backup(source,Path(temp)/'backups')
                with closing(sqlite3.connect(receipt['backup_path'])) as copy:
                    self.assertEqual(copy.execute('PRAGMA journal_mode').fetchone()[0],'delete')
                    self.assertEqual(copy.execute('PRAGMA foreign_key_check').fetchall(),[])
                    self.assertEqual(copy.execute('SELECT id FROM child').fetchall(),[(7,)])
    def test_reader_snapshot_cannot_hold_exit_and_retraction_and_anchor_closes(self):
        from bollinger_tick_stream import RealtimeBollingerWorker
        from tests.test_bollinger_tick_stream import seed,trade,CANDLE
        with tempfile.TemporaryDirectory() as temp:
            database=Path(temp)/'source.db';seed(database)
            with closing(sqlite3.connect(database)) as db:db.execute('PRAGMA journal_mode=WAL')
            worker=RealtimeBollingerWorker(database,'iex',['AAPL'])
            def observe(message,received):
                return dict(symbol='AAPL',source_timestamp=message['t'],received_at=received.isoformat(),signal=dict(side='SUPERIOR',candle=CANDLE.isoformat()) if message['i']==1 else None),'READY_NO_EXIT'
            try:
                with closing(sqlite3.connect(database)) as reader,patch.object(worker.geometry,'observe',side_effect=observe):
                    reader.execute('BEGIN');self.assertEqual(reader.execute('SELECT COUNT(*) FROM bollinger_tick_latest').fetchone()[0],0)
                    for identity in (1,2):
                        worker.trade(trade(104. if identity==1 else 100.,datetime.now(timezone.utc),identity))
                        until=time.monotonic()+1
                        while time.monotonic()<until:
                            with closing(sqlite3.connect(database)) as db:row=db.execute('SELECT payload_json FROM bollinger_tick_latest WHERE symbol=?',('AAPL',)).fetchone()
                            if row and bool(json.loads(row[0])['signal'])==(identity==1):break
                            time.sleep(.01)
                        else:self.fail('Reader snapshot blocked publication')
                    self.assertEqual(reader.execute('SELECT COUNT(*) FROM bollinger_tick_latest').fetchone()[0],0)
                    reader.rollback()
            finally:worker.close()
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM bollinger_tick_audit').fetchone()[0],2)
                self.assertEqual(db.execute('PRAGMA journal_mode=DELETE').fetchone()[0],'delete')
            self.assertFalse(worker.failed.is_set())

if __name__=='__main__':unittest.main()
