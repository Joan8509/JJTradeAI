"""Ejecuta verificaciones locales antes de release o publicacion privada."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class HealthCheck:
    """Comando verificable del proyecto."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class HealthCheckResult:
    """Resultado normalizado para una verificacion."""

    name: str
    command: tuple[str, ...]
    returncode: int
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def build_checks(python_executable: str = sys.executable) -> list[HealthCheck]:
    """Construye la lista conservadora de checks de release local."""
    return [
        HealthCheck(
            "unit_tests",
            (python_executable, "-m", "unittest", "discover", "tests"),
        ),
        HealthCheck("prepublish", (python_executable, "prepublish_check.py")),
        HealthCheck(
            "validation_runner_version",
            (python_executable, "validation_runner.py", "--version"),
        ),
        HealthCheck(
            "validation_batch_version",
            (python_executable, "validation_batch.py", "--version"),
        ),
        HealthCheck(
            "report_auditor_version",
            (python_executable, "report_auditor.py", "--version"),
        ),
        HealthCheck(
            "live_strategy_service_cli",
            (python_executable, "live_strategy_service.py", "--help"),
        ),
        HealthCheck(
            "scanner_control_cli",
            (python_executable, "scanner_control.py", "--help"),
        ),
        HealthCheck(
            "scanner_instance_cli",
            (python_executable, "scanner_instance.py", "--help"),
        ),
        HealthCheck(
            "database_backup_cli",
            (python_executable, "database_backup.py", "--help"),
        ),
        HealthCheck(
            "beta_status_cli",
            (python_executable, "beta_status.py", "--help"),
        ),
        HealthCheck(
            "paper_rehearsal",
            (python_executable, "paper_rehearsal.py"),
        ),
        HealthCheck(
            "paper_session_evidence_cli",
            (python_executable, "paper_session_evidence.py", "--help"),
        ),
        HealthCheck(
            "visual_evidence_backup_cli",
            (python_executable, "visual_evidence_backup.py", "--help"),
        ),
        HealthCheck(
            "methodology_coverage",
            (python_executable, "methodology_coverage.py"),
        ),
        HealthCheck(
            "safety_invariants",
            (python_executable, "safety_invariants.py"),
        ),
    ]


def run_check(check: HealthCheck, runner: CommandRunner | None = None) -> HealthCheckResult:
    """Ejecuta un check y conserva stdout/stderr para auditoria."""
    effective_runner = runner or (
        lambda command: subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
    )
    completed = effective_runner(check.command)
    output = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part and part.strip()
    )
    return HealthCheckResult(
        name=check.name,
        command=check.command,
        returncode=completed.returncode,
        output=output,
    )


def run_health_checks(
    checks: Sequence[HealthCheck] | None = None,
    *,
    runner: CommandRunner | None = None,
) -> list[HealthCheckResult]:
    """Ejecuta todos los checks definidos."""
    selected_checks = list(checks) if checks is not None else build_checks()
    return [run_check(check, runner=runner) for check in selected_checks]


def health_payload(results: Sequence[HealthCheckResult]) -> dict[str, object]:
    """Construye una salida serializable del health check."""
    failed = [result for result in results if not result.passed]
    return {
        "status": "OK" if not failed else "BLOQUEADO",
        "check_count": len(results),
        "failed_count": len(failed),
        "checks": [
            {
                "name": result.name,
                "status": "OK" if result.passed else "ERROR",
                "command": list(result.command),
                "returncode": result.returncode,
                "output": result.output,
            }
            for result in results
        ],
    }


def write_json_output(path: str | Path, payload: dict[str, object]) -> None:
    """Guarda un payload JSON creando carpetas padre si hace falta."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta verificaciones locales antes de release.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime la salida en JSON para auditoria o automatizacion.",
    )
    parser.add_argument(
        "--output",
        help="Ruta donde guardar el JSON de resultado. Implica --json.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    results = run_health_checks()
    payload = health_payload(results)
    if args.output:
        write_json_output(args.output, payload)
        print(f"Release health JSON escrito: {args.output}")
        return 0 if payload["status"] == "OK" else 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "OK" else 1

    for result in results:
        status = "OK" if result.passed else "ERROR"
        print(f"[{status}] {result.name}")
        if result.output:
            print(result.output)
    if payload["failed_count"]:
        print(f"Release health check: BLOQUEADO ({payload['failed_count']} fallos)")
        return 1
    print(f"Release health check: OK ({len(results)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
