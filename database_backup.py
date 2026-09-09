"""Backups consistentes, verificables y restaurables de bases SQLite locales."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
from typing import Any, Sequence


def create_sqlite_backup(source: str | Path, backup_directory: str | Path, *, retention: int = 30) -> dict[str, Any]:
    """Usa la API online de SQLite, verifica la copia y aplica retención segura."""
    if retention <= 0:
        raise ValueError("La retención debe ser mayor que cero.")
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise ValueError(f"No existe la base SQLite: {source_path}")
    backup_root = Path(backup_directory).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_root / f"{source_path.stem}_{timestamp}.db"
    partial = destination.with_suffix(".db.partial")
    source_connection = sqlite3.connect(source_path)
    destination_connection = sqlite3.connect(partial)
    try:
        source_check = source_connection.execute("PRAGMA quick_check").fetchone()[0]
        if source_check != "ok":
            raise ValueError(f"La base origen no supera quick_check: {source_check}")
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    check_connection = sqlite3.connect(partial)
    try:
        backup_check = check_connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        check_connection.close()
    if backup_check != "ok":
        partial.unlink(missing_ok=True)
        raise ValueError(f"El backup no supera quick_check: {backup_check}")
    partial.replace(destination)
    digest = _sha256(destination)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_name": source_path.name,
        "backup_name": destination.name,
        "size_bytes": destination.stat().st_size,
        "sha256": digest,
        "integrity": "ok",
    }
    manifest_path = destination.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    removed = prune_sqlite_backups(backup_root, source_stem=source_path.stem, retention=retention)
    return {**manifest, "backup_path": str(destination), "manifest_path": str(manifest_path), "removed_backup_count": removed}


def prune_sqlite_backups(backup_directory: str | Path, *, source_stem: str, retention: int) -> int:
    if retention <= 0:
        raise ValueError("La retención debe ser mayor que cero.")
    root = Path(backup_directory).resolve()
    if not root.is_dir():
        return 0
    candidates = sorted(root.glob(f"{source_stem}_*.db"), key=lambda item: item.name, reverse=True)
    removed = 0
    for candidate in candidates[retention:]:
        resolved = candidate.resolve()
        if resolved.parent != root or not resolved.name.startswith(f"{source_stem}_"):
            raise ValueError("La retención intentó salir del directorio autorizado.")
        resolved.unlink()
        resolved.with_suffix(".json").unlink(missing_ok=True)
        resolved.with_suffix(".visual.zip").unlink(missing_ok=True)
        removed += 1
    return removed


def verify_sqlite_backup(path: str | Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    backup = Path(path).resolve()
    if not backup.is_file():
        raise ValueError(f"No existe el backup: {backup}")
    connection = sqlite3.connect(backup)
    try:
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        connection.close()
    digest = _sha256(backup)
    hash_matches = expected_sha256 is None or digest == expected_sha256.lower()
    return {"status": "OK" if integrity == "ok" and hash_matches else "BLOQUEADO", "integrity": integrity, "sha256": digest, "hash_matches": hash_matches, "path": str(backup)}


def restore_sqlite_backup(
    backup: str | Path,
    target: str | Path,
    *,
    expected_sha256: str | None = None,
    overwrite: bool = False,
    safety_backup_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Restaura atómicamente y respalda primero cualquier destino existente."""
    backup_path = Path(backup).resolve()
    target_path = Path(target).resolve()
    if backup_path == target_path:
        raise ValueError("El backup y el destino no pueden ser el mismo archivo.")
    expected = expected_sha256 or _manifest_sha256(backup_path)
    verification = verify_sqlite_backup(backup_path, expected_sha256=expected)
    if verification["status"] != "OK":
        raise ValueError("El backup no supera integridad y huella; restauración bloqueada.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    safety_backup = None
    if target_path.exists():
        if not overwrite:
            raise ValueError("El destino ya existe; usa --overwrite para autorizar su reemplazo.")
        safety_root = Path(safety_backup_directory).resolve() if safety_backup_directory else target_path.parent / "backups" / "pre_restore"
        safety_backup = create_sqlite_backup(target_path, safety_root, retention=30)
    partial = target_path.with_suffix(target_path.suffix + ".restore_partial")
    partial.unlink(missing_ok=True)
    shutil.copyfile(backup_path, partial)
    restored_check = verify_sqlite_backup(partial, expected_sha256=expected)
    if restored_check["status"] != "OK":
        partial.unlink(missing_ok=True)
        raise ValueError("La copia restaurada no coincide con el backup verificado.")
    partial.replace(target_path)
    return {
        "status": "RESTAURADO", "backup_path": str(backup_path),
        "target_path": str(target_path), "sha256": expected,
        "safety_backup_path": safety_backup["backup_path"] if safety_backup else None,
    }


def _manifest_sha256(backup: Path) -> str:
    manifest_path = backup.with_suffix(".json")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        value = str(payload["sha256"]).lower()
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("Falta un manifiesto válido con SHA-256 para restaurar.") from error
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("El SHA-256 del manifiesto no es válido.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("--directory", default="exports/backups")
    parser.add_argument("--retention", type=int, default=30)
    parser.add_argument("--verify")
    parser.add_argument("--restore")
    parser.add_argument("--target")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--safety-backup-directory")
    args = parser.parse_args(argv)
    try:
        selected_actions = sum(bool(value) for value in (args.source, args.verify, args.restore))
        if selected_actions != 1:
            raise ValueError("Elige exactamente una acción: crear, --verify o --restore.")
        if args.restore:
            if not args.target:
                raise ValueError("--restore requiere --target.")
            result = restore_sqlite_backup(
                args.restore, args.target, overwrite=args.overwrite,
                safety_backup_directory=args.safety_backup_directory,
            )
        elif args.verify:
            verify_path = Path(args.verify).resolve()
            result = verify_sqlite_backup(verify_path, expected_sha256=_manifest_sha256(verify_path))
        else:
            result = create_sqlite_backup(args.source, args.directory, retention=args.retention)
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"Backup BLOQUEADO: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status", "OK") in {"OK", "RESTAURADO"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
