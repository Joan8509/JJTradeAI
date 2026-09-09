"""Lease de instancia única para impedir scanners duplicados."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Any, Sequence


class ScannerInstanceLease:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.token = secrets.token_hex(16)
        self.acquired = False

    def acquire(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            metadata = {
                "pid": os.getpid(), "token": self.token,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "RUNNING",
            }
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                current = read_instance_status(self.path)
                if current.get("active"):
                    raise RuntimeError(f"Ya existe un scanner activo con PID {current.get('pid')}.")
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            try:
                os.write(descriptor, (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8"))
            finally:
                os.close(descriptor)
            self.acquired = True
            return metadata
        raise RuntimeError("No se pudo recuperar el lease obsoleto del scanner.")

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        if current.get("token") == self.token:
            self.path.unlink(missing_ok=True)
        self.acquired = False

    def __enter__(self) -> "ScannerInstanceLease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


def read_instance_status(path: str | Path) -> dict[str, Any]:
    lock_path = Path(path).resolve()
    if not lock_path.exists():
        return {"status": "DETENIDO", "active": False, "lock_path": str(lock_path)}
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {"status": "LEASE_INVALIDO", "active": False, "lock_path": str(lock_path)}
    active = _pid_is_alive(pid)
    return {
        "status": "ACTIVO" if active else "LEASE_OBSOLETO", "active": active,
        "pid": pid, "started_at": payload.get("started_at"), "lock_path": str(lock_path),
    }


def request_scanner_stop(lock_path: str | Path, stop_path: str | Path) -> dict[str, Any]:
    """Escribe una solicitud que solo la instancia dueña puede aceptar."""
    lock = Path(lock_path).resolve()
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        token = str(payload["token"])
        pid = int(payload["pid"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError("No existe un lease válido al cual solicitar parada.") from error
    if not _pid_is_alive(pid):
        raise RuntimeError("El lease existe, pero su proceso ya no está activo.")
    request = {
        "token": token, "requested_at": datetime.now(timezone.utc).isoformat(),
        "requester_pid": os.getpid(),
    }
    destination = Path(stop_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    temporary.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return {"status": "PARADA_SOLICITADA", "scanner_pid": pid, "stop_path": str(destination)}


def consume_stop_request(stop_path: str | Path, *, owner_token: str) -> bool:
    """Consume solo solicitudes firmadas con el token del lease actual."""
    path = Path(stop_path).resolve()
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not secrets.compare_digest(str(payload.get("token", "")), owner_token):
        return False
    path.unlink(missing_ok=True)
    return True


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except (OSError, ValueError, OverflowError):
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    """Consulta Windows sin enviar señales ni confundir procesos ajenos."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--lock-file", default="exports/live_scanner.lock")
    args = parser.parse_args(argv)
    if not args.status:
        parser.error("Indica --status.")
    payload = read_instance_status(args.lock_file)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["active"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
