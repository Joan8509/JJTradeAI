"""Control local start/stop/status del scanner sin ejecutar órdenes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Sequence

from scanner_instance import read_instance_status, request_scanner_stop
from live_preflight import SYMBOL_PATTERN


PROJECT_ROOT = Path(__file__).resolve().parent


def build_scanner_arguments(
    *, symbols: str, days: int, database: str | Path,
    option_policy: str | Path | None = None,
) -> list[str]:
    normalized = sorted({item.strip().upper() for item in symbols.split(",") if item.strip()})
    if not normalized or any(not SYMBOL_PATTERN.fullmatch(item) for item in normalized):
        raise ValueError("Los símbolos del scanner no son válidos.")
    if days <= 0:
        raise ValueError("Los días de backfill deben ser mayores que cero.")
    arguments = ["--symbols", ",".join(normalized), "--days", str(days), "--database", str(Path(database).resolve())]
    if option_policy is not None:
        policy_path = Path(option_policy).resolve()
        if not policy_path.is_file():
            raise ValueError("No existe la política de opciones indicada.")
        arguments.extend(["--option-policy", str(policy_path)])
    return arguments


def start_scanner(
    scanner_arguments: Sequence[str], *,
    lock_file: str | Path = "exports/live_scanner.lock",
    log_file: str | Path = "exports/live_scanner.log",
    python_executable: str = sys.executable,
    environment: dict[str, str] | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    current = read_instance_status(lock_file)
    if current.get("active"):
        raise RuntimeError(f"El scanner ya está activo con PID {current.get('pid')}.")
    log_path = Path(log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [python_executable, str(PROJECT_ROOT / "live_strategy_service.py"), *scanner_arguments]
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    child_environment = os.environ.copy()
    if environment:
        child_environment.update(environment)
    with log_path.open("a", encoding="utf-8") as log:
        process = popen_factory(
            command, cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
            close_fds=True, env=child_environment,
        )
    return {"status": "INICIANDO", "pid": int(process.pid), "log_path": str(log_path), "command": command}


def stop_scanner(*, lock_file: str | Path = "exports/live_scanner.lock", stop_file: str | Path = "exports/live_scanner.stop") -> dict[str, Any]:
    return request_scanner_stop(lock_file, stop_file)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-file", default="exports/live_scanner.lock")
    parser.add_argument("--stop-file", default="exports/live_scanner.stop")
    parser.add_argument("--log-file", default="exports/live_scanner.log")
    subparsers = parser.add_subparsers(dest="action", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("scanner_arguments", nargs=argparse.REMAINDER)
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            forwarded = args.scanner_arguments[1:] if args.scanner_arguments[:1] == ["--"] else args.scanner_arguments
            result = start_scanner(forwarded, lock_file=args.lock_file, log_file=args.log_file)
        elif args.action == "stop":
            result = stop_scanner(lock_file=args.lock_file, stop_file=args.stop_file)
        else:
            result = read_instance_status(args.lock_file)
    except (RuntimeError, OSError) as error:
        print(json.dumps({"status": "BLOQUEADO", "detail": str(error)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.action != "status" or result.get("active") else 1


if __name__ == "__main__":
    raise SystemExit(main())
