"""Revisa candidatos de Git antes de publicar JJTrade AI en privado."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Sequence


BLOCKED_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*secret*",
    "*token*",
    "credentials*",
    "*credential*",
    "exports/*.db",
    "exports/*.db-*",
    "exports/backups/**",
    "exports/*.lock",
    "exports/*.stop",
    "exports/*.log",
    "exports/tc2000_cases/*.txt",
    "exports/tc2000_cases/case_intake*.csv",
    "exports/tc2000_cases/package_inventory.csv",
    "exports/validation_*",
    "exports/validation_*/**",
    "exports/beta_*",
    "exports/beta_*/**",
    "exports/audit_*.csv",
    "exports/prepublish_manifest.csv",
    "exports/release_health.json",
    "exports/github_readiness.json",
    "exports/paper_rehearsal*.json",
    "exports/paper_session_evidence*.json",
    "exports/methodology_coverage*.json",
    "exports/safety_invariants*.json",
    "exports/visual_evidence/**",
    ".streamlit/*.log",
)

ALLOWED_EXCEPTIONS = ("exports/sample.txt",)


@dataclass(frozen=True)
class PrepublishFinding:
    """Archivo candidato que no debe entrar al commit."""

    path: str
    pattern: str


@dataclass(frozen=True)
class PrepublishManifestRow:
    """Fila auditable de un candidato revisado."""

    path: str
    status: str
    matched_pattern: str


def _normalize_path(path: str | Path) -> str:
    normalized = Path(path).as_posix()
    return normalized[2:] if normalized.startswith("./") else normalized


def _matches_pattern(path: str, pattern: str) -> bool:
    normalized_path = path.lower()
    normalized_pattern = pattern.lower()
    if fnmatch(normalized_path, normalized_pattern):
        return True
    if normalized_pattern.endswith("/**"):
        return normalized_path.startswith(normalized_pattern[:-3].rstrip("/") + "/")
    return False


def find_blocked_candidates(
    candidates: Iterable[str | Path],
    *,
    blocked_patterns: Sequence[str] = BLOCKED_PATH_PATTERNS,
    allowed_exceptions: Sequence[str] = ALLOWED_EXCEPTIONS,
) -> list[PrepublishFinding]:
    """Devuelve archivos candidatos que violan la politica de publicacion."""
    allowed = {_normalize_path(path).lower() for path in allowed_exceptions}
    findings: list[PrepublishFinding] = []
    for candidate in candidates:
        path = _normalize_path(candidate)
        if path.lower() in allowed:
            continue
        for pattern in blocked_patterns:
            if _matches_pattern(path, pattern):
                findings.append(PrepublishFinding(path=path, pattern=pattern))
                break
    return findings


def build_manifest_rows(
    candidates: Iterable[str | Path],
    findings: Iterable[PrepublishFinding],
) -> list[PrepublishManifestRow]:
    """Crea filas de manifiesto para guardar evidencia pre-publicacion."""
    finding_by_path = {finding.path: finding for finding in findings}
    rows = []
    for candidate in candidates:
        path = _normalize_path(candidate)
        finding = finding_by_path.get(path)
        rows.append(
            PrepublishManifestRow(
                path=path,
                status="BLOQUEADO" if finding else "OK",
                matched_pattern=finding.pattern if finding else "",
            )
        )
    return sorted(rows, key=lambda row: row.path)


def write_manifest_csv(path: str | Path, rows: Iterable[PrepublishManifestRow]) -> None:
    """Escribe un CSV auditable de candidatos revisados."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("path", "status", "matched_pattern"),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "path": row.path,
                    "status": row.status,
                    "matched_pattern": row.matched_pattern,
                }
            )


def git_candidate_files() -> list[str]:
    """Lista archivos versionados o no ignorados que Git podria publicar."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Revisa candidatos de Git antes de publicar JJTrade AI.",
    )
    parser.add_argument(
        "--manifest",
        help="Ruta CSV donde guardar el manifiesto de candidatos revisados.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        candidates = git_candidate_files()
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"No se pudo consultar Git: {error}", file=sys.stderr)
        return 2

    findings = find_blocked_candidates(candidates)
    if args.manifest:
        write_manifest_csv(args.manifest, build_manifest_rows(candidates, findings))
        print(f"Manifest escrito: {args.manifest}")
    if findings:
        print("Prepublish check: BLOQUEADO")
        for finding in findings:
            print(f"- {finding.path} coincide con {finding.pattern}")
        return 1

    print(f"Prepublish check: OK ({len(candidates)} candidatos revisados)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
