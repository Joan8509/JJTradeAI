"""Pruebas del lease que impide scanners simultáneos."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from scanner_instance import ScannerInstanceLease, _pid_is_alive, consume_stop_request, read_instance_status, request_scanner_stop


class ScannerInstanceTests(unittest.TestCase):
    def test_current_process_is_alive(self) -> None:
        self.assertTrue(_pid_is_alive(os.getpid()))

    def test_acquire_reports_current_process_and_release_removes_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner.lock"
            lease = ScannerInstanceLease(path)
            lease.acquire()
            status = read_instance_status(path)
            self.assertTrue(status["active"])
            self.assertEqual(status["pid"], os.getpid())
            lease.release()
            self.assertEqual(read_instance_status(path)["status"], "DETENIDO")

    def test_second_lease_is_blocked_while_first_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner.lock"
            first = ScannerInstanceLease(path)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "scanner activo"):
                    ScannerInstanceLease(path).acquire()
            finally:
                first.release()

    def test_stale_or_invalid_lease_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner.lock"
            path.write_text(json.dumps({"pid": 2147483647, "token": "old"}), encoding="utf-8")
            self.assertEqual(read_instance_status(path)["status"], "LEASE_OBSOLETO")
            lease = ScannerInstanceLease(path)
            lease.acquire()
            self.assertTrue(read_instance_status(path)["active"])
            lease.release()

            path.write_text("no-json", encoding="utf-8")
            invalid_recovery = ScannerInstanceLease(path)
            invalid_recovery.acquire()
            invalid_recovery.release()

    def test_release_does_not_remove_another_owner_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanner.lock"
            lease = ScannerInstanceLease(path)
            lease.acquire()
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["token"] = "different-owner"
            path.write_text(json.dumps(payload), encoding="utf-8")
            lease.release()
            self.assertTrue(path.exists())

    def test_stop_request_is_consumed_only_by_current_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "scanner.lock"
            stop = Path(directory) / "scanner.stop"
            lease = ScannerInstanceLease(lock)
            lease.acquire()
            try:
                result = request_scanner_stop(lock, stop)
                self.assertEqual(result["status"], "PARADA_SOLICITADA")
                self.assertFalse(consume_stop_request(stop, owner_token="wrong-token"))
                self.assertTrue(stop.exists())
                self.assertTrue(consume_stop_request(stop, owner_token=lease.token))
                self.assertFalse(stop.exists())
            finally:
                lease.release()


if __name__ == "__main__":
    unittest.main()
