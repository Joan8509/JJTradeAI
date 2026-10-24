from contextlib import closing,redirect_stdout
import io,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from database_backup import create_sqlite_backup
from visual_evidence_backup import create_visual_evidence_backup
import live_strategy_service as service

class VerifiedStartupBackupTests(unittest.TestCase):
    def fixture(self,folder):
        p=Path(folder)/'db.sqlite'
        with closing(sqlite3.connect(p)) as db,db:db.execute('CREATE TABLE items(id INTEGER)');db.execute('INSERT INTO items VALUES(1)')
        return create_sqlite_backup(p,Path(folder)/'backups')
    def test_visual_reuses_exact_verified_snapshot_without_second_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt=self.fixture(folder)
            with patch('visual_evidence_backup.verify_sqlite_backup',side_effect=AssertionError('Redundant full scan')):
                result=create_visual_evidence_backup(receipt['backup_path'],Path(folder)/'visual',verified_backup=receipt)
            self.assertEqual(result['evidence_count'],0)
    def test_wrong_file_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.fixture(folder);r['backup_path']=str(Path(folder)/'wrong.db')
            with self.assertRaises(ValueError):create_visual_evidence_backup(next((Path(folder)/'backups').glob('*.db')),Path(folder)/'visual',verified_backup=r)
    def test_changed_snapshot_is_rejected_even_with_unchanged_size(self):
        with tempfile.TemporaryDirectory() as folder:
            r=self.fixture(folder)
            with closing(sqlite3.connect(r['backup_path'])) as db,db:db.execute('UPDATE items SET id=2')
            with self.assertRaisesRegex(ValueError,'cambió'):create_visual_evidence_backup(r['backup_path'],Path(folder)/'visual',verified_backup=r)
    def test_corrupt_source_cannot_become_verified_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'bad.db';p.write_bytes(b'not a sqlite database')
            with self.assertRaises(sqlite3.DatabaseError):create_sqlite_backup(p,Path(folder)/'backups')
    def run_main(self,folder,flags,expected_backup):
        args=['scanner','--data-only','--database',str(Path(folder)/'live.db'),
            '--lock-file',str(Path(folder)/'lock'),'--stop-file',str(Path(folder)/'stop'),*flags]
        import live_preflight
        original=live_preflight.run_live_preflight
        with patch('sys.argv',args),patch.dict(os.environ,{'ALPACA_API_KEY':'fixture','ALPACA_API_SECRET':'fixture','ALPACA_DATA_FEED':'iex'}), \
             patch.object(service,'run_live_preflight',wraps=original) as preflight, \
             patch.object(service,'ScannerInstanceLease',return_value=Mock(acquire=Mock(return_value={'pid':1}))), \
             patch.object(service.atexit,'register'),patch.object(service,'create_sqlite_backup',side_effect=RuntimeError('fixture-backup-failed')) as backup, \
             patch.object(service.AlpacaMarketConfig,'from_env',side_effect=RuntimeError('fixture-before-network')) as config,redirect_stdout(io.StringIO()):
            if '--preflight-only' in flags:self.assertEqual(service.main(),0)
            else:
                with self.assertRaisesRegex(RuntimeError,'fixture-backup-failed' if expected_backup else 'fixture-before-network'):service.main()
            self.assertEqual(preflight.call_args.kwargs['integrity_verified_by_backup'],expected_backup)
            if expected_backup:backup.assert_called_once();config.assert_not_called()
            else:backup.assert_not_called()
    def test_normal_startup_cannot_connect_when_required_backup_fails(self):
        with tempfile.TemporaryDirectory() as folder:self.run_main(folder,[],True)
    def test_preflight_only_retains_independent_integrity_check(self):
        with tempfile.TemporaryDirectory() as folder:self.run_main(folder,['--preflight-only'],False)
    def test_explicit_no_backup_still_retains_independent_integrity_check(self):
        with tempfile.TemporaryDirectory() as folder:self.run_main(folder,['--no-startup-backup'],False)

if __name__=='__main__':unittest.main()
