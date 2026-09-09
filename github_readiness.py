"""Audita preparacion local antes de publicar JJTrade AI en GitHub privado."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence

from prepublish_check import find_blocked_candidates, git_candidate_files


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ReadinessItem:
    """Resultado de una verificacion de publicacion."""

    name: str
    status: str
    detail: str
    action: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "OK"


def _run_git(
    command: Sequence[str],
    runner: CommandRunner | None = None,
) -> subprocess.CompletedProcess[str]:
    effective_runner = runner or (
        lambda args: subprocess.run(args, capture_output=True, text=True)
    )
    return effective_runner(tuple(command))


def _git_text(
    command: Sequence[str],
    runner: CommandRunner | None = None,
) -> tuple[int, str]:
    result = _run_git(command, runner=runner)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode, output


def check_github_readiness(
    *,
    runner: CommandRunner | None = None,
    candidates: Sequence[str] | None = None,
) -> list[ReadinessItem]:
    """Devuelve una checklist local para el primer push privado."""
    items: list[ReadinessItem] = []

    repo_code, repo_output = _git_text(
        ("git", "rev-parse", "--is-inside-work-tree"),
        runner=runner,
    )
    items.append(
        ReadinessItem(
            name="git_repo",
            status="OK" if repo_code == 0 and repo_output == "true" else "BLOQUEADO",
            detail="Repositorio Git detectado." if repo_code == 0 else repo_output,
            action="Ejecuta git init en la carpeta del proyecto."
            if repo_code != 0
            else "",
        )
    )

    branch_code, branch_output = _git_text(
        ("git", "branch", "--show-current"),
        runner=runner,
    )
    items.append(
        ReadinessItem(
            name="git_branch",
            status="OK" if branch_code == 0 and branch_output == "main" else "PENDIENTE",
            detail=branch_output or "No se pudo detectar la rama actual.",
            action="" if branch_code == 0 and branch_output == "main" else "git branch -M main",
        )
    )

    for key, label, action in (
        ("user.name", "git_user_name", 'git config user.name "TU NOMBRE"'),
        ("user.email", "git_user_email", 'git config user.email "TU EMAIL"'),
    ):
        code, output = _git_text(("git", "config", "--get", key), runner=runner)
        items.append(
            ReadinessItem(
                name=label,
                status="OK" if code == 0 and bool(output) else "PENDIENTE",
                detail=output or f"Configura git config {key}.",
                action="" if code == 0 and bool(output) else action,
            )
        )

    log_code, log_output = _git_text(("git", "log", "--oneline", "-1"), runner=runner)
    items.append(
        ReadinessItem(
            name="initial_commit",
            status="OK" if log_code == 0 and bool(log_output) else "PENDIENTE",
            detail=log_output or "Aun no existe commit inicial.",
            action=(
                ""
                if log_code == 0 and bool(log_output)
                else "Ejecuta health check, prepublish, git add . y git commit."
            ),
        )
    )

    remote_code, remote_output = _git_text(("git", "remote", "-v"), runner=runner)
    items.append(
        ReadinessItem(
            name="git_remote",
            status="OK" if remote_code == 0 and bool(remote_output) else "PENDIENTE",
            detail=remote_output or "Aun no hay remoto configurado.",
            action=(
                ""
                if remote_code == 0 and bool(remote_output)
                else "Crea un repo privado y ejecuta git remote add origin <URL>."
            ),
        )
    )

    candidate_files = list(candidates) if candidates is not None else git_candidate_files()
    findings = find_blocked_candidates(candidate_files)
    items.append(
        ReadinessItem(
            name="prepublish_candidates",
            status="OK" if not findings else "BLOQUEADO",
            detail=(
                f"{len(candidate_files)} candidatos revisados sin bloqueos."
                if not findings
                else f"{len(findings)} candidatos bloqueados."
            ),
            action=(
                ""
                if not findings
                else "Revisa .gitignore y ejecuta prepublish_check.py --manifest."
            ),
        )
    )

    return items


def readiness_payload(items: Sequence[ReadinessItem]) -> dict[str, object]:
    """Construye una salida serializable para automatizacion."""
    pending = [item for item in items if not item.passed]
    blocked = [item for item in items if item.status == "BLOQUEADO"]
    return {
        "status": "BLOQUEADO" if blocked else "OK" if not pending else "PENDIENTE",
        "pending_count": len(pending),
        "items": [
            {
                "name": item.name,
                "status": item.status,
                "detail": item.detail,
                "action": item.action,
            }
            for item in items
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
        description="Audita preparacion local antes de publicar en GitHub privado.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime la salida en JSON para automatizacion.",
    )
    parser.add_argument(
        "--output",
        help="Ruta donde guardar el JSON de readiness. Implica --json.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        items = check_github_readiness()
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"No se pudo evaluar GitHub readiness: {error}", file=sys.stderr)
        return 2

    payload = readiness_payload(items)
    if args.output:
        write_json_output(args.output, payload)
        print(f"GitHub readiness JSON escrito: {args.output}")
        return 0 if payload["status"] == "OK" else 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "OK" else 1

    for item in items:
        print(f"[{item.status}] {item.name}: {item.detail}")
        if item.action:
            print(f"  Accion: {item.action}")
    if payload["pending_count"]:
        print(f"GitHub readiness: {payload['status']} ({payload['pending_count']} items)")
        return 1
    print("GitHub readiness: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
