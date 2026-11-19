"""Cross-process hints must follow durable publication; no broker or live DB."""
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
import os
import sqlite3
import subprocess
import sys
import tempfile

from market_signal_wakeup import SignalWakeup, CommittedSignalNotifier, event_name


class SignalWakeupTests(TestCase):
    def test_database_and_reader_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'test.db'
            self.assertNotEqual(event_name(database,'real'),event_name(database,'simulation'))
            self.assertNotEqual(event_name(database,'real'),event_name(database.with_name('other.db'),'real'))
            with self.assertRaises(ValueError):event_name(database,'unknown')

    @skipUnless(os.name=='nt','Win32 cross-process event')
    def test_cross_process_hint_is_latched_and_consumed_once(self):
        with tempfile.TemporaryDirectory() as folder:
            database=Path(folder)/'test.db'
            reader=SignalWakeup(database,'real')
            try:
                self.assertTrue(reader.native,'Native IPC unavailable in this test environment')
                code=('from market_signal_wakeup import SignalWakeup; import sys; '
                      'w=SignalWakeup(sys.argv[1],"real"); '
                      'assert w.native; w.set(); w.close()')
                child=subprocess.run([sys.executable,'-c',code,str(database)],
                    capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(child.returncode,0,child.stderr)
                reader.clear()  # Must not erase a newer latched publication.
                self.assertTrue(reader.wait(.1))
                self.assertFalse(reader.wait(0))
            finally:reader.close()

    def test_only_new_committed_exit_keys_wake_all_readers(self):
        readers=[]
        def factory(*args):
            reader=Mock();readers.append(reader);return reader
        notifier=CommittedSignalNotifier('isolated.db',factory=factory)
        signal=dict(reason='EXIT',signal=dict(candle='c1',side='UPPER'))
        notifier.after_commit({'AAPL':dict(reason='READY_NO_EXIT',signal=None)})
        for reader in readers:reader.set.assert_not_called()
        notifier.after_commit({'AAPL':signal});notifier.after_commit({'AAPL':signal})
        for reader in readers:self.assertEqual(reader.set.call_count,1)
        notifier.after_commit({'AAPL':dict(reason='EXIT',signal=dict(candle='c1',side='LOWER'))})
        for reader in readers:self.assertEqual(reader.set.call_count,2)
        notifier.close()
        for reader in readers:reader.close.assert_called_once()

    def test_retracted_then_valid_same_candle_wakes_without_resetting_signal(self):
        notifier=CommittedSignalNotifier('isolated.db',factory=lambda *args:Mock())
        signal=dict(reason='EXIT',signal=dict(candle='c1',side='UPPER',
            first_breakout_at='2026-11-17T15:16:03+00:00'))
        from copy import deepcopy
        original=deepcopy(signal)
        notifier.after_commit({'AAPL':signal})
        for _ in range(20):notifier.after_commit({'AAPL':signal})
        notifier.after_commit({'AAPL':dict(reason='READY_NO_EXIT',signal=None)})
        notifier.after_commit({'AAPL':signal})
        for reader in notifier.readers:self.assertEqual(reader.set.call_count,2)
        self.assertEqual(signal,original)

    def test_other_symbols_do_not_clear_active_signal_and_batch_is_one_wakeup(self):
        notifier=CommittedSignalNotifier('isolated.db',factory=lambda *args:Mock())
        signal=dict(reason='EXIT',signal=dict(candle='c1',side='UPPER'))
        notifier.after_commit({'AAPL':signal,'GLD':signal})
        notifier.after_commit({'GLD':dict(reason='READY_NO_EXIT',signal=None)})
        notifier.after_commit({'AAPL':signal})
        for reader in notifier.readers:self.assertEqual(reader.set.call_count,1)
        notifier.after_commit({'GLD':signal})
        for reader in notifier.readers:self.assertEqual(reader.set.call_count,2)

    def test_busy_transaction_never_wakes_before_successful_commit(self):
        from bollinger_tick_stream import TickPublisher
        with tempfile.TemporaryDirectory() as folder:
            attempted=Event();release=Event();notified=Event();failed=Event()
            repository=Mock(database=Path(folder)/'test.db')
            attempts=[]
            def flush(*args,**kwargs):
                attempts.append(1)
                if len(attempts)==1:
                    attempted.set();release.wait(3)
                    error=sqlite3.OperationalError('busy fixture')
                    error.sqlite_errorcode=sqlite3.SQLITE_BUSY
                    raise error
            repository.flush.side_effect=flush
            notifier=Mock();notifier.after_commit.side_effect=lambda *_:notified.set()
            with patch('market_signal_wakeup.CommittedSignalNotifier',return_value=notifier):
                publisher=TickPublisher(repository,'iex',['AAPL'],failed)
                try:
                    publisher.submit({'AAPL':dict(reason='EXIT',signal={'candle':'c1','side':'UPPER'})},
                        [],state='CONECTADO',now=datetime.now(timezone.utc))
                    self.assertTrue(attempted.wait(2))
                    notifier.after_commit.assert_not_called()
                    release.set();self.assertTrue(notified.wait(2))
                    self.assertGreaterEqual(len(attempts),2)
                    self.assertFalse(failed.is_set())
                finally:release.set();publisher.close()
            notifier.close.assert_called_once()

    def test_slow_entry_work_does_not_add_another_poll_delay(self):
        from real_execution_runtime import RealExecutionWorker
        wake=Mock();queue=Mock()
        stamps=iter([0.,.25,.25])
        worker=RealExecutionWorker(queue,SimpleNamespace(binding='synthetic'),Mock(),
            monotonic=lambda:next(stamps),signal_wakeup=wake)
        queue.step.side_effect=lambda *args,**kwargs:worker._stop.set()
        worker._loop('entries',.2)
        wake.wait.assert_called_once_with(0.)
