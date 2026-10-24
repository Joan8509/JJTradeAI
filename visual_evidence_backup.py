"""Backup verificable y restauracion conservadora de evidencia visual."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Sequence
import zipfile

from database_backup import verify_sqlite_backup


MAX_VISUAL_BUNDLE_BYTES = 2 * 1024 * 1024 * 1024


def create_visual_evidence_backup(
    database_backup: str | Path,
    visual_directory: str | Path,
    *,
    destination: str | Path | None = None,
    verified_backup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Empaqueta las imagenes referidas por un snapshot SQLite ya verificado."""
    database_path = Path(database_backup).resolve()
    visual_root = Path(visual_directory).resolve()
    if verified_backup is None:
        database_verification = verify_sqlite_backup(database_path)
    else:
        # Only a caller that just created/verified this exact immutable snapshot
        # supplies the receipt. Hash the file again to detect replacement; the
        # standalone API/CLI retains its independent integrity check by default.
        if (Path(verified_backup.get('backup_path','')).resolve()!=database_path or
                verified_backup.get('integrity')!='ok' or
                verified_backup.get('size_bytes')!=database_path.stat().st_size):
            raise ValueError('El recibo no corresponde al respaldo visual.')
        digest=_sha256(database_path)
        if digest!=verified_backup.get('sha256'):
            raise ValueError('El respaldo cambió después de verificarlo.')
        database_verification=dict(status='OK',sha256=digest)
    if database_verification["status"] != "OK":
        raise ValueError("La base de respaldo no supera integridad SQLite.")
    records = _visual_records(database_path)
    files = []
    total_bytes = 0
    for record in records:
        relative = _safe_relative_path(record["relative_path"])
        source = (visual_root / relative).resolve()
        if visual_root not in source.parents or not source.is_file():
            raise ValueError(
                f"Falta la evidencia visual #{record['id']}: {relative.as_posix()}."
            )
        digest = _sha256(source)
        if digest != record["content_hash"]:
            raise ValueError(
                f"La evidencia visual #{record['id']} no coincide con su SHA-256."
            )
        size = source.stat().st_size
        if size != record["byte_count"]:
            raise ValueError(
                f"La evidencia visual #{record['id']} no coincide en tamano."
            )
        total_bytes += size
        if total_bytes > MAX_VISUAL_BUNDLE_BYTES:
            raise ValueError("La evidencia visual excede el limite total de 2 GB.")
        files.append(
            {
                "evidence_id": int(record["id"]),
                "relative_path": relative.as_posix(),
                "sha256": digest,
                "size_bytes": size,
                "source": source,
            }
        )

    destination_path = (
        Path(destination).resolve()
        if destination is not None
        else database_path.with_suffix(".visual.zip")
    )
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise ValueError("El paquete visual de destino ya existe.")
    partial = destination_path.with_suffix(destination_path.suffix + ".partial")
    partial.unlink(missing_ok=True)
    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_backup_name": database_path.name,
        "database_sha256": database_verification["sha256"],
        "evidence_count": len(files),
        "total_bytes": total_bytes,
        "files": [
            {key: item[key] for key in ("evidence_id", "relative_path", "sha256", "size_bytes")}
            for item in files
        ],
        "authority": "BACKUP_VISUAL_NO_MODIFICA_DECISION",
    }
    try:
        with zipfile.ZipFile(
            partial, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            for item in files:
                archive.write(
                    item["source"],
                    arcname=f"visual_evidence/{item['relative_path']}",
                )
        verification = verify_visual_evidence_backup(
            partial,
            expected_database_sha256=database_verification["sha256"],
        )
        if verification["status"] != "OK":
            raise ValueError("El paquete visual creado no supera verificacion.")
        partial.replace(destination_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {
        **verification,
        "backup_path": str(destination_path),
        "database_backup_path": str(database_path),
    }


def verify_visual_evidence_backup(
    backup: str | Path,
    *,
    expected_database_sha256: str | None = None,
) -> dict[str, Any]:
    archive_path = Path(backup).resolve()
    if not archive_path.is_file():
        raise ValueError(f"No existe el paquete visual: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            names = archive.namelist()
            if names.count("manifest.json") != 1:
                raise ValueError("El paquete visual no contiene un manifiesto unico.")
            manifest = json.loads(archive.read("manifest.json"))
            files = _validate_manifest(manifest)
            expected_names = {
                "manifest.json",
                *{
                    f"visual_evidence/{item['relative_path']}"
                    for item in files
                },
            }
            if set(names) != expected_names or len(names) != len(expected_names):
                raise ValueError("El paquete visual contiene entradas no declaradas.")
            total = 0
            for item in files:
                name = f"visual_evidence/{item['relative_path']}"
                content = archive.read(name)
                total += len(content)
                if total > MAX_VISUAL_BUNDLE_BYTES:
                    raise ValueError("El paquete visual excede el limite total.")
                if len(content) != item["size_bytes"]:
                    raise ValueError(f"Tamano incorrecto en {name}.")
                if hashlib.sha256(content).hexdigest() != item["sha256"]:
                    raise ValueError(f"SHA-256 incorrecto en {name}.")
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"Paquete visual invalido: {error}") from error
    database_hash_matches = (
        expected_database_sha256 is None
        or manifest["database_sha256"] == expected_database_sha256.lower()
    )
    return {
        "status": "OK" if database_hash_matches else "BLOQUEADO",
        "path": str(archive_path),
        "bundle_sha256": _sha256(archive_path),
        "database_sha256": manifest["database_sha256"],
        "database_hash_matches": database_hash_matches,
        "evidence_count": manifest["evidence_count"],
        "total_bytes": manifest["total_bytes"],
        "manifest": manifest,
    }


def restore_visual_evidence_backup(
    backup: str | Path,
    target_directory: str | Path,
    *,
    expected_database_sha256: str | None = None,
) -> dict[str, Any]:
    """Restaura solo archivos nuevos; bloquea conflictos y nunca sobrescribe."""
    verification = verify_visual_evidence_backup(
        backup,
        expected_database_sha256=expected_database_sha256,
    )
    if verification["status"] != "OK":
        raise ValueError("El paquete visual no corresponde al backup SQLite.")
    target_root = Path(target_directory).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    manifest = verification["manifest"]
    planned = []
    with zipfile.ZipFile(Path(backup).resolve(), mode="r") as archive:
        for item in manifest["files"]:
            relative = _safe_relative_path(item["relative_path"])
            destination = (target_root / relative).resolve()
            if target_root not in destination.parents:
                raise ValueError("La restauracion visual intento salir del destino.")
            if destination.exists():
                if not destination.is_file() or _sha256(destination) != item["sha256"]:
                    raise ValueError(
                        f"Conflicto en {relative.as_posix()}; no se sobrescribe."
                    )
                continue
            content = archive.read(f"visual_evidence/{relative.as_posix()}")
            planned.append((destination, content))
    restored = 0
    for destination, content in planned:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".restore_partial")
        partial.write_bytes(content)
        if hashlib.sha256(content).hexdigest() != _sha256(partial):
            partial.unlink(missing_ok=True)
            raise ValueError("La copia visual parcial no supera SHA-256.")
        partial.replace(destination)
        restored += 1
    return {
        "status": "RESTAURADO",
        "backup_path": str(Path(backup).resolve()),
        "target_directory": str(target_root),
        "restored_count": restored,
        "already_present_count": manifest["evidence_count"] - restored,
        "database_sha256": manifest["database_sha256"],
    }


def _visual_records(database: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='alert_visual_evidence'"
        ).fetchone()
        if exists is None:
            return []
        rows = connection.execute(
            "SELECT id, relative_path, content_hash, byte_count "
            "FROM alert_visual_evidence ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("version") != 1:
        raise ValueError("Version de manifiesto visual no admitida.")
    database_sha = str(manifest["database_sha256"]).lower()
    if not _valid_sha256(database_sha):
        raise ValueError("SHA-256 de base invalido en el manifiesto visual.")
    raw_files = manifest["files"]
    if not isinstance(raw_files, list):
        raise ValueError("Lista de archivos visuales invalida.")
    files = []
    paths = set()
    total = 0
    for raw in raw_files:
        relative = _safe_relative_path(raw["relative_path"]).as_posix()
        digest = str(raw["sha256"]).lower()
        size = int(raw["size_bytes"])
        if relative in paths or not _valid_sha256(digest) or size < 0:
            raise ValueError("Entrada visual duplicada o invalida.")
        paths.add(relative)
        total += size
        if total > MAX_VISUAL_BUNDLE_BYTES:
            raise ValueError("El manifiesto visual excede el limite total.")
        files.append(
            {
                "evidence_id": int(raw["evidence_id"]),
                "relative_path": relative,
                "sha256": digest,
                "size_bytes": size,
            }
        )
    if int(manifest["evidence_count"]) != len(files) or int(manifest["total_bytes"]) != total:
        raise ValueError("Los totales del manifiesto visual no coinciden.")
    return files


def _safe_relative_path(value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("Ruta visual no segura.")
    return path


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--create", help="Backup SQLite ya creado.")
    actions.add_argument("--verify", help="Paquete visual ZIP.")
    actions.add_argument("--restore", help="Paquete visual ZIP.")
    parser.add_argument(
        "--visual-directory",
        default="exports/visual_evidence",
        help="Origen al crear o destino al restaurar.",
    )
    parser.add_argument("--destination", help="Ruta del nuevo paquete al crear.")
    parser.add_argument("--database-sha256", help="SHA-256 del backup SQLite asociado.")
    args = parser.parse_args(argv)
    try:
        if args.create:
            result = create_visual_evidence_backup(
                args.create,
                args.visual_directory,
                destination=args.destination,
            )
        elif args.verify:
            result = verify_visual_evidence_backup(
                args.verify,
                expected_database_sha256=args.database_sha256,
            )
        else:
            result = restore_visual_evidence_backup(
                args.restore,
                args.visual_directory,
                expected_database_sha256=args.database_sha256,
            )
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as error:
        print(f"Backup visual BLOQUEADO: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"OK", "RESTAURADO"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
