"""Evidencia visual complementaria de TC2000 asociada a alertas."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import zlib

from safe_diagnostics import sanitize_diagnostic_detail


SUPPORTED_TIMEFRAMES = ("15m", "1H", "1D")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 200
MAX_IMAGE_DIMENSION = 12_000
DEFAULT_VISUAL_EVIDENCE_DIRECTORY = (
    Path(__file__).resolve().parent / "exports" / "visual_evidence"
)


class VisualEvidenceRepository:
    """Conserva capturas por hash sin permitir que modifiquen una decision."""

    def __init__(
        self,
        database_path: str | Path,
        storage_directory: str | Path = DEFAULT_VISUAL_EVIDENCE_DIRECTORY,
    ) -> None:
        self.database_path = Path(database_path)
        self.storage_directory = Path(storage_directory)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS alert_visual_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    source TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    byte_count INTEGER NOT NULL,
                    relative_path TEXT NOT NULL,
                    indicators_json TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    UNIQUE(alert_id, timeframe, content_hash),
                    FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id)
                );
                CREATE TABLE IF NOT EXISTS alert_visual_evidence_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES alert_visual_evidence(id)
                );
                CREATE INDEX IF NOT EXISTS idx_visual_evidence_alert
                ON alert_visual_evidence (alert_id, id);
                CREATE INDEX IF NOT EXISTS idx_visual_evidence_reviews
                ON alert_visual_evidence_reviews (evidence_id, id);
                """
            )

    def record(
        self,
        alert_id: int,
        *,
        timeframe: str,
        filename: str,
        content: bytes,
        indicators_visible: tuple[str, ...] = (),
        notes: str = "",
    ) -> int:
        normalized_timeframe = timeframe.strip()
        if normalized_timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError("La temporalidad visual debe ser 15m, 1H o 1D.")
        media_type, extension, width, height = inspect_image(content)
        digest = hashlib.sha256(content).hexdigest()
        safe_filename = _safe_filename(filename, extension)
        indicators = tuple(
            sorted({item.strip().upper() for item in indicators_visible if item.strip()})
        )

        with self._connect() as connection:
            alert = connection.execute(
                "SELECT symbol FROM strategy_alerts WHERE id=?",
                (alert_id,),
            ).fetchone()
            if alert is None:
                raise ValueError(f"No existe la alerta {alert_id}.")
            symbol = str(alert["symbol"])

        destination = self.storage_directory / f"{digest}.{extension}"
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError("El archivo visual existente no coincide con su hash.")
        else:
            temporary = destination.with_suffix(destination.suffix + ".partial")
            temporary.write_bytes(content)
            temporary.replace(destination)

        relative_path = destination.relative_to(self.storage_directory).as_posix()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO alert_visual_evidence (
                    alert_id, created_at, symbol, timeframe, source,
                    original_filename, content_hash, media_type, width, height,
                    byte_count, relative_path, indicators_json, notes, authority
                ) VALUES (?, ?, ?, ?, 'TC2000_SCREENSHOT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    datetime.now(timezone.utc).isoformat(),
                    symbol,
                    normalized_timeframe,
                    safe_filename,
                    digest,
                    media_type,
                    width,
                    height,
                    len(content),
                    relative_path,
                    json.dumps(indicators),
                    notes.strip(),
                    "EVIDENCIA_VISUAL_NO_MODIFICA_DECISION",
                ),
            )
            row = connection.execute(
                "SELECT id FROM alert_visual_evidence "
                "WHERE alert_id=? AND timeframe=? AND content_hash=?",
                (alert_id, normalized_timeframe, digest),
            ).fetchone()
        return int(row["id"])

    def recent(self, alert_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_visual_evidence "
                "WHERE alert_id=? ORDER BY id DESC",
                (alert_id,),
            ).fetchall()
        return [_decode_evidence(row) for row in rows]

    def record_review(
        self,
        evidence_id: int,
        *,
        status: str,
        notes: str = "",
    ) -> int:
        normalized = status.strip().upper()
        if normalized not in {"PENDIENTE", "COINCIDE", "DIFIERE", "NO_EVALUABLE"}:
            raise ValueError("El estado de revision visual no es valido.")
        if normalized in {"DIFIERE", "NO_EVALUABLE"} and not notes.strip():
            raise ValueError("La discrepancia o limitacion visual requiere notas.")
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM alert_visual_evidence WHERE id=?",
                (evidence_id,),
            ).fetchone()
            if exists is None:
                raise ValueError(f"No existe la evidencia visual {evidence_id}.")
            cursor = connection.execute(
                """
                INSERT INTO alert_visual_evidence_reviews (
                    evidence_id, created_at, status, notes, authority
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    datetime.now(timezone.utc).isoformat(),
                    normalized,
                    notes.strip(),
                    "REVISION_VISUAL_NO_MODIFICA_DECISION",
                ),
            )
        return int(cursor.lastrowid)

    def reviews(self, evidence_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_visual_evidence_reviews "
                "WHERE evidence_id=? ORDER BY id DESC",
                (evidence_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def image_path(self, evidence: dict[str, Any]) -> Path:
        relative = Path(str(evidence["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("La ruta de evidencia visual no es segura.")
        path = (self.storage_directory / relative).resolve()
        if self.storage_directory.resolve() not in path.parents:
            raise ValueError("La ruta de evidencia visual sale del almacen.")
        return path

    def audit(self, alert_id: int) -> dict[str, Any]:
        """Verifica archivos y resume la revision sin alterar evidencia."""
        evidence_items = self.recent(alert_id)
        rows = []
        for evidence in evidence_items:
            integrity_status = "OK"
            integrity_detail = "Archivo presente y SHA-256 verificado."
            try:
                path = self.image_path(evidence)
                content = path.read_bytes()
                actual_hash = hashlib.sha256(content).hexdigest()
                media_type, _, width, height = inspect_image(content)
                if actual_hash != evidence["content_hash"]:
                    raise ValueError("El SHA-256 actual no coincide con el registrado.")
                if len(content) != evidence["byte_count"]:
                    raise ValueError("El tamano actual no coincide con el registrado.")
                if (
                    media_type != evidence["media_type"]
                    or width != evidence["width"]
                    or height != evidence["height"]
                ):
                    raise ValueError(
                        "El formato o las dimensiones no coinciden con el registro."
                    )
            except (OSError, ValueError) as error:
                integrity_status = "ERROR"
                integrity_detail = sanitize_diagnostic_detail(error)
            reviews = self.reviews(int(evidence["id"]))
            latest_review = reviews[0] if reviews else None
            rows.append(
                {
                    "evidence_id": evidence["id"],
                    "symbol": evidence["symbol"],
                    "timeframe": evidence["timeframe"],
                    "source": evidence["source"],
                    "content_hash": evidence["content_hash"],
                    "media_type": evidence["media_type"],
                    "width": evidence["width"],
                    "height": evidence["height"],
                    "byte_count": evidence["byte_count"],
                    "indicators_visible": evidence["indicators_visible"],
                    "created_at": evidence["created_at"],
                    "integrity_status": integrity_status,
                    "integrity_detail": integrity_detail,
                    "latest_review_status": (
                        latest_review["status"] if latest_review else "PENDIENTE"
                    ),
                    "latest_review_at": (
                        latest_review["created_at"] if latest_review else None
                    ),
                }
            )
        integrity_failures = sum(
            item["integrity_status"] == "ERROR" for item in rows
        )
        pending_reviews = sum(
            item["latest_review_status"] == "PENDIENTE" for item in rows
        )
        disagreements = sum(
            item["latest_review_status"] == "DIFIERE" for item in rows
        )
        if not rows:
            status = "SIN_EVIDENCIA"
        elif integrity_failures:
            status = "BLOQUEADO_ARCHIVOS"
        else:
            status = "INTEGRO"
        return {
            "status": status,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "alert_id": alert_id,
            "evidence_count": len(rows),
            "integrity_failure_count": integrity_failures,
            "pending_review_count": pending_reviews,
            "disagreement_count": disagreements,
            "items": rows,
            "decision_modified": False,
            "authority": "AUDITORIA_VISUAL_NO_MODIFICA_DECISION",
        }

    def overall_audit(self) -> dict[str, Any]:
        """Resume evidencia real sin confundir integridad con decision."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT alert_id FROM alert_visual_evidence "
                "ORDER BY alert_id"
            ).fetchall()
        alert_audits = [self.audit(int(row["alert_id"])) for row in rows]
        summaries = []
        for audit in alert_audits:
            items = audit["items"]
            timeframes = sorted(
                {str(item["timeframe"]) for item in items}
            )
            complete = (
                set(timeframes) == set(SUPPORTED_TIMEFRAMES)
                and all(item["integrity_status"] == "OK" for item in items)
                and all(item["latest_review_status"] == "COINCIDE" for item in items)
            )
            summaries.append(
                {
                    "alert_id": audit["alert_id"],
                    "evidence_count": audit["evidence_count"],
                    "timeframes": timeframes,
                    "integrity_failure_count": audit["integrity_failure_count"],
                    "pending_review_count": audit["pending_review_count"],
                    "disagreement_count": audit["disagreement_count"],
                    "multitimeframe_complete": complete,
                }
            )
        evidence_count = sum(item["evidence_count"] for item in summaries)
        integrity_failures = sum(
            item["integrity_failure_count"] for item in summaries
        )
        pending_reviews = sum(
            item["pending_review_count"] for item in summaries
        )
        disagreements = sum(
            item["disagreement_count"] for item in summaries
        )
        complete_alerts = sum(
            bool(item["multitimeframe_complete"]) for item in summaries
        )
        if not summaries:
            status = "NO_INICIADO"
        elif integrity_failures:
            status = "BLOQUEADO"
        elif disagreements:
            status = "DIFIERE"
        elif complete_alerts:
            status = "APROBADO"
        else:
            status = "EN_REVISION"
        return {
            "status": status,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "alert_count": len(summaries),
            "evidence_count": evidence_count,
            "integrity_failure_count": integrity_failures,
            "pending_review_count": pending_reviews,
            "disagreement_count": disagreements,
            "complete_alert_count": complete_alerts,
            "alerts": summaries,
            "decision_modified": False,
            "real_trading_authorized": False,
            "authority": "HITO_VISUAL_TC2000_NO_MODIFICA_DECISION",
        }


def inspect_image(content: bytes) -> tuple[str, str, int, int]:
    if not content:
        raise ValueError("La captura esta vacia.")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("La captura excede el limite de 10 MB.")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _png_dimensions(content)
        media_type, extension = "image/png", "png"
    elif content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9"):
        width, height = _jpeg_dimensions(content)
        media_type, extension = "image/jpeg", "jpg"
    else:
        raise ValueError("La captura debe ser una imagen PNG o JPEG valida.")
    if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
        raise ValueError(
            f"La captura debe medir al menos {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}."
        )
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ValueError("Las dimensiones de la captura exceden el limite seguro.")
    return media_type, extension, width, height


def _png_dimensions(content: bytes) -> tuple[int, int]:
    offset = 8
    width = height = 0
    saw_header = False
    saw_end = False
    while offset + 12 <= len(content):
        chunk_length = int.from_bytes(content[offset:offset + 4], "big")
        chunk_type = content[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        crc_end = data_end + 4
        if crc_end > len(content):
            break
        expected_crc = int.from_bytes(content[data_end:crc_end], "big")
        actual_crc = zlib.crc32(chunk_type + content[data_start:data_end])
        if expected_crc != actual_crc:
            raise ValueError("La captura PNG tiene un bloque corrupto.")
        if chunk_type == b"IHDR":
            if saw_header or chunk_length != 13 or offset != 8:
                raise ValueError("La cabecera PNG no es valida.")
            width = int.from_bytes(content[data_start:data_start + 4], "big")
            height = int.from_bytes(content[data_start + 4:data_start + 8], "big")
            saw_header = True
        elif chunk_type == b"IEND":
            if chunk_length != 0:
                raise ValueError("El cierre PNG no es valido.")
            saw_end = True
            offset = crc_end
            break
        offset = crc_end
    if not saw_header or not saw_end or offset != len(content):
        raise ValueError("La estructura de la captura PNG no es valida.")
    return width, height


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    start_of_frame = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset < len(content):
        while offset < len(content) and content[offset] != 0xFF:
            offset += 1
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            break
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(content):
            break
        segment_length = int.from_bytes(content[offset:offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(content):
            break
        if marker in start_of_frame and segment_length >= 7:
            height = int.from_bytes(content[offset + 3:offset + 5], "big")
            width = int.from_bytes(content[offset + 5:offset + 7], "big")
            return width, height
        offset += segment_length
    raise ValueError("No se pudieron leer las dimensiones de la imagen JPEG.")


def _safe_filename(filename: str, extension: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        name = f"captura.{extension}"
    return name[:200]


def _decode_evidence(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["indicators_visible"] = json.loads(item.pop("indicators_json"))
    return item
