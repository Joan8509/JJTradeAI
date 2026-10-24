"""A failed ingest must release a quiet stream for task-level recovery."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from live_service_runtime import ResilientStreamSupervisor
from live_strategy_service import monitor_scanner_shutdown


class QuietStream:
    def __init__(self):
        self.started = Event()
        self.stopped = Event()

    def run(self, symbols, on_bar, *, on_error=None, on_status=None):
        on_status('CONECTADO')
        self.started.set()
        self.stopped.wait(8)

    def stop(self):
        self.stopped.set()


class ScannerFailureRecoveryTests(unittest.TestCase):
    def test_failed_ingest_stops_quiet_stream_without_another_market_message(self):
        stream = QuietStream()
        factory = Mock(return_value=stream)
        supervisor = ResilientStreamSupervisor(stream_factory=factory,
            continuity=SimpleNamespace(provider_name='ALPACA', feed='iex', recover=Mock()), health=Mock())
        finished, failed = Event(), Event()
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            run_thread = Thread(target=supervisor.run, args=(['AAPL'], Mock()))
            monitor = Thread(target=monitor_scanner_shutdown,
                args=(supervisor, finished, Path(directory)/'stop', 'owner', SimpleNamespace(failed=failed)))
            try:
                run_thread.start()
                self.assertTrue(stream.started.wait(3))
                monitor.start()
                failed.set()
                self.assertTrue(stream.stopped.wait(3))
                run_thread.join(3)
                monitor.join(3)
                self.assertFalse(run_thread.is_alive())
                self.assertFalse(monitor.is_alive())
                factory.assert_called_once()  # Never reconnect using a permanently failed worker.
            finally:
                finished.set()
                supervisor.stop()
                run_thread.join(3)
                if monitor.ident is not None:
                    monitor.join(3)

    def test_healthy_silent_worker_does_not_force_restart(self):
        finished = Event()
        supervisor = Mock()
        with tempfile.TemporaryDirectory() as directory:
            monitor = Thread(target=monitor_scanner_shutdown,
                args=(supervisor, finished, Path(directory)/'stop', 'owner', SimpleNamespace(failed=Event())))
            monitor.start()
            try:
                self.assertFalse(finished.wait(1.1))
                supervisor.stop.assert_not_called()
            finally:
                finished.set()
                monitor.join(3)
            self.assertFalse(monitor.is_alive())

    def test_cooperative_stop_still_requires_current_owner(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            path = Path(directory)/'stop'
            path.write_text(json.dumps({'token': 'previous-owner'}))
            finished = Event()
            supervisor = Mock()
            monitor = Thread(target=monitor_scanner_shutdown,
                             args=(supervisor, finished, path, 'current-owner'))
            monitor.start()
            try:
                self.assertFalse(finished.wait(1.1))
                supervisor.stop.assert_not_called()
                # Atomic replacement, as used by request_scanner_stop.
                replacement = path.with_suffix('.tmp')
                replacement.write_text(json.dumps({'token': 'current-owner'}))
                replacement.replace(path)
                monitor.join(3)
                self.assertFalse(monitor.is_alive())
                supervisor.stop.assert_called_once()
                self.assertFalse(path.exists())
            finally:
                finished.set()
                monitor.join(3)
