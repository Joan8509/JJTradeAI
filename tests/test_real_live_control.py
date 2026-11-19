from contextlib import contextmanager,closing
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
import tempfile,time

from real_live_control import RealRuntimeProxy,register_selected_account,next_official_session
from real_live_storage import RealEncryptedStore
from real_live_commands import request_close,CommandExecution
from tests import test_real_order_ledger as journal
from tests import test_schwab_option_order_request as options


class RealControlTests(TestCase):
    def test_display_uses_one_consistent_journal_read_and_refreshes_next_render(self):
        from copy import deepcopy
        buy=dict(id='BUY',instruction='BUY_TO_OPEN',contract=journal.CONTRACT,state='FILLED',
            exit_plan=dict(target='10'),fills={'1':dict(quantity=1,price='1',time=options.NOW.isoformat())})
        sell=dict(id='SELL',instruction='SELL_TO_CLOSE',parent_id='BUY',state='FILLED',
            fills={'2':dict(quantity=1,price='1.1',time=options.NOW.isoformat())})
        ledger=Mock();ledger.display_requests.side_effect=[deepcopy([buy]),deepcopy([buy,sell])]
        proxy=RealRuntimeProxy(journal.BINDING)
        with patch('real_order_ledger.RealOrderLedger',return_value=ledger):
            positions,history=proxy.display_positions()
            self.assertEqual(ledger.display_requests.call_count,1)
            self.assertEqual(positions[0]['quantity'],1);self.assertEqual(history[0]['state'],'OPEN')
            positions,history=proxy.display_positions()
            self.assertEqual(ledger.display_requests.call_count,2)
            self.assertEqual(positions,[]);self.assertEqual(history[0]['state'],'CLOSED')

    def test_remove_proxy_passes_exact_plan_and_row_without_rearming(self):
        queue=Mock()
        proxy=RealRuntimeProxy('a'*64,queue=queue)
        proxy.remove('PLAN','ROW')
        queue.remove.assert_called_once_with('a'*64,'PLAN','ROW')
        queue.arm.assert_not_called();queue.pause.assert_not_called()

    def test_real_lock_preserves_existing_file_and_does_not_grow_on_reads(self):
        from real_live_storage import _byte_lock
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.dpapi';lock=path.with_suffix('.lock')
            lock.write_bytes(b'legacy-lock-bytes')
            for _ in range(10):
                with _byte_lock(path):pass
            self.assertEqual(lock.read_bytes(),b'legacy-lock-bytes')

    def test_real_byte_lock_excludes_competing_handle_and_releases_after_failure(self):
        from real_live_storage import _byte_lock
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.dpapi'
            with _byte_lock(path):
                with self.assertRaises(OSError):
                    with _byte_lock(path):self.fail('competing lock acquired')
            with self.assertRaisesRegex(RuntimeError,'synthetic'):
                with _byte_lock(path):raise RuntimeError('synthetic')
            with _byte_lock(path):pass

    def test_selected_account_descriptor_encrypted_and_never_arms_queue(self):
        store=journal.Vault();context=SimpleNamespace(binding='a'*64,account_number='12345678',account_hash='HASH')
        register_selected_account(context,store_factory=lambda:store)
        self.assertEqual(store.data['account']['binding'],'a'*64)
        self.assertNotIn('tokens',store.data);self.assertNotIn('rows',store.data)

    def test_dashboard_requires_current_matching_host_before_arming(self):
        status=journal.Vault();control=journal.Vault();queue=Mock()
        now=options.NOW
        context=SimpleNamespace(binding='a'*64,account_number='12345678',account_hash='HASH')
        register_selected_account(context,store_factory=lambda:control)
        proxy=RealRuntimeProxy('a'*64,queue=queue,status_factory=lambda:status,control_factory=lambda:control,
            clock=lambda:now,session_provider=lambda:(now,now+timedelta(hours=6)))
        self.assertFalse(proxy.can_arm())
        status.save(dict(binding='a'*64,checked_at=now.isoformat(),ready_to_arm=True))
        self.assertTrue(proxy.can_arm());proxy.arm([dict(symbol='AAPL',quantity=1,target='10')])
        queue.arm.assert_called_once()
        self.assertTrue(queue.arm.call_args.kwargs['first_entry_only'])
        self.assertFalse(queue.arm.call_args.kwargs['repeat_new_signals'])
        status.data['checked_at']=(now-timedelta(seconds=5)).isoformat();self.assertFalse(proxy.can_arm())
        status.data.update(checked_at=now.isoformat(),binding='b'*64);self.assertFalse(proxy.can_arm())

    def test_account_change_refuses_an_armed_queue_even_without_fills(self):
        store=journal.Vault();first=SimpleNamespace(binding='a'*64,account_number='12345678',account_hash='HASH')
        register_selected_account(first,store_factory=lambda:store)
        ledger=Mock();ledger.requests.return_value=[]
        queue=Mock();queue.read.return_value=dict(rows=[dict(state='ARMED')])
        with patch('real_order_ledger.RealOrderLedger',return_value=ledger),patch('real_live_control.RealAutomaticQueue',return_value=queue):
            with self.assertRaisesRegex(ValueError,'ACTIVE_QUEUE'):
                register_selected_account(SimpleNamespace(binding='b'*64,account_number='87654321',account_hash='OTHER'),store_factory=lambda:store)
        self.assertEqual(store.data['account']['binding'],'a'*64)

    def test_official_calendar_uses_stored_sessions_and_does_not_guess_weekdays(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'calendar.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE market_sessions(session_date TEXT,opens_at TEXT,closes_at TEXT)')
                db.execute('INSERT INTO market_sessions VALUES (?,?,?)',('2026-11-02',options.NOW.isoformat(),(options.NOW+timedelta(hours=6)).isoformat()))
                db.commit()
            start,end=next_official_session(options.NOW-timedelta(days=1),path)
            self.assertEqual(start,options.NOW)
            with self.assertRaisesRegex(ValueError,'SESSION_UNAVAILABLE'):next_official_session(end,path)

    def test_manual_close_persisted_once_and_dispatch_uses_owned_position(self):
        store=journal.Vault();ledger=Mock();ledger.requests.return_value=[
            dict(id='BUY',instruction='BUY_TO_OPEN',exit_plan={'target':'20'},fills={'x':dict(quantity=1)})]
        first=request_close('a'*64,'BUY',store_factory=lambda:store,ledger=ledger)
        self.assertEqual(request_close('a'*64,'BUY',store_factory=lambda:store,ledger=ledger),first)
        execution=Mock(binding='a'*64);execution.poll.return_value=[]
        bridge=CommandExecution(execution,store_factory=lambda:store);bridge.poll();bridge.poll()
        execution.close_manually.assert_called_once_with('BUY')
        self.assertEqual(store.data['commands'][0]['state'],'ACKNOWLEDGED')
        with self.assertRaises(ValueError):request_close('a'*64,'FOREIGN',store_factory=lambda:store,ledger=ledger)

    def test_real_file_locks_serialize_threads_and_do_not_retry_body_failure(self):
        from schwab_connection import EncryptedSchwabStore
        @contextmanager
        def base_lock(store):yield
        class Store(RealEncryptedStore):
            def __init__(self,path):self.path=path
        with tempfile.TemporaryDirectory() as directory,patch.object(EncryptedSchwabStore,'locked',base_lock):
            path=Path(directory)/'synthetic.dpapi';counter=[0]
            def increment():
                with Store(path).locked():
                    before=counter[0];time.sleep(.001);counter[0]=before+1
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:increment(),range(20)))
            self.assertEqual(counter[0],20)
            effects=[]
            with self.assertRaises(OSError):
                with Store(path).locked():effects.append('once');raise OSError('SYNTHETIC')
            self.assertEqual(effects,['once'])
