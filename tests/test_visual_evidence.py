"""Pruebas de evidencia visual TC2000 complementaria."""

from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from live_strategy_service import AlertRepository
from visual_evidence import VisualEvidenceRepository, inspect_image


def png(width: int = 640, height: int = 360) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = (
        struct.pack(">I", len(ihdr_data))
        + b"IHDR"
        + ihdr_data
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    )
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    compressed = zlib.compress(raw)
    idat = (
        struct.pack(">I", len(compressed))
        + b"IDAT"
        + compressed
        + struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    )
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND"))
    return signature + ihdr + idat + iend


class VisualEvidenceTests(unittest.TestCase):
    def _alert(self, database: Path) -> int:
        return int(
            AlertRepository(database).record(
                provider="ALPACA",
                feed="iex",
                symbol="SPY",
                trigger_timestamp=__import__("datetime").datetime(
                    2026, 7, 27, 14, 0, tzinfo=__import__("datetime").timezone.utc
                ),
                report={
                    "data_as_of": "2026-07-27T14:00:00+00:00",
                    "decision": {"decision": "NO_OPERAR"},
                    "strategy_summary": {"detected": 1, "confirmed": 0},
                },
            )
        )

    def test_records_content_addressed_image_without_changing_alert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            storage = Path(directory) / "images"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(database, storage)

            evidence_id = repository.record(
                alert_id,
                timeframe="15m",
                filename="../spy-chart.png",
                content=png(),
                indicators_visible=("MA20", "BOLLINGER", "MA20"),
                notes="Captura visible.",
            )
            evidence = repository.recent(alert_id)[0]
            alert = AlertRepository(database).recent()[0]

            self.assertEqual(evidence_id, evidence["id"])
            self.assertEqual(evidence["symbol"], "SPY")
            self.assertEqual(evidence["original_filename"], "spy-chart.png")
            self.assertEqual(evidence["indicators_visible"], ["BOLLINGER", "MA20"])
            self.assertTrue(repository.image_path(evidence).is_file())
            self.assertEqual(alert["decision"], "NO_OPERAR")
            self.assertEqual(
                evidence["authority"], "EVIDENCIA_VISUAL_NO_MODIFICA_DECISION"
            )

    def test_duplicate_image_for_same_alert_and_timeframe_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(database, Path(directory) / "images")
            content = png()

            first = repository.record(
                alert_id, timeframe="1H", filename="one.png", content=content
            )
            second = repository.record(
                alert_id, timeframe="1H", filename="two.png", content=content
            )

            self.assertEqual(first, second)
            self.assertEqual(len(repository.recent(alert_id)), 1)

    def test_reviews_are_versioned_and_disagreement_requires_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(database, Path(directory) / "images")
            evidence_id = repository.record(
                alert_id, timeframe="1D", filename="daily.png", content=png()
            )

            with self.assertRaisesRegex(ValueError, "requiere notas"):
                repository.record_review(evidence_id, status="DIFIERE")
            repository.record_review(
                evidence_id, status="DIFIERE", notes="La MA40 no coincide."
            )
            repository.record_review(
                evidence_id, status="COINCIDE", notes="Configuracion corregida."
            )

            self.assertEqual(
                [item["status"] for item in repository.reviews(evidence_id)],
                ["COINCIDE", "DIFIERE"],
            )

    def test_rejects_invalid_or_too_small_images(self) -> None:
        with self.assertRaisesRegex(ValueError, "PNG o JPEG"):
            inspect_image(b"not-an-image")
        with self.assertRaisesRegex(ValueError, "al menos"):
            inspect_image(png(100, 100))
        with self.assertRaisesRegex(ValueError, "PNG"):
            inspect_image(
                b"\x89PNG\r\n\x1a\n"
                + b"\x00\x00\x00\rIHDR"
                + struct.pack(">II", 640, 360)
                + b"\x08\x02\x00\x00\x00"
                + b"\x00\x00\x00\x00"
            )

    def test_audit_detects_tampering_and_summarizes_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(database, Path(directory) / "images")
            evidence_id = repository.record(
                alert_id, timeframe="15m", filename="chart.png", content=png()
            )
            repository.record_review(
                evidence_id, status="COINCIDE", notes="Revision manual."
            )

            clean = repository.audit(alert_id)
            evidence = repository.recent(alert_id)[0]
            repository.image_path(evidence).write_bytes(png(800, 450))
            tampered = repository.audit(alert_id)

        self.assertEqual(clean["status"], "INTEGRO")
        self.assertEqual(clean["pending_review_count"], 0)
        self.assertEqual(clean["items"][0]["latest_review_status"], "COINCIDE")
        self.assertFalse(clean["decision_modified"])
        self.assertEqual(tampered["status"], "BLOQUEADO_ARCHIVOS")
        self.assertEqual(tampered["integrity_failure_count"], 1)

    def test_empty_visual_audit_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(database, Path(directory) / "images")

            payload = repository.audit(alert_id)

        self.assertEqual(payload["status"], "SIN_EVIDENCIA")
        self.assertEqual(payload["evidence_count"], 0)

    def test_overall_audit_requires_reviewed_multitimeframe_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(
                database,
                Path(directory) / "images",
            )
            first_id = repository.record(
                alert_id,
                timeframe="15m",
                filename="15m.png",
                content=png(),
            )
            repository.record_review(first_id, status="COINCIDE")
            partial = repository.overall_audit()
            for timeframe, width in (("1H", 641), ("1D", 642)):
                evidence_id = repository.record(
                    alert_id,
                    timeframe=timeframe,
                    filename=f"{timeframe}.png",
                    content=png(width, 360),
                )
                repository.record_review(evidence_id, status="COINCIDE")
            complete = repository.overall_audit()

        self.assertEqual(partial["status"], "EN_REVISION")
        self.assertEqual(partial["complete_alert_count"], 0)
        self.assertEqual(complete["status"], "APROBADO")
        self.assertEqual(complete["complete_alert_count"], 1)
        self.assertFalse(complete["decision_modified"])
        self.assertFalse(complete["real_trading_authorized"])

    def test_overall_audit_blocks_tampered_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            alert_id = self._alert(database)
            repository = VisualEvidenceRepository(
                database,
                Path(directory) / "images",
            )
            evidence_id = repository.record(
                alert_id,
                timeframe="15m",
                filename="chart.png",
                content=png(),
            )
            repository.record_review(evidence_id, status="COINCIDE")
            evidence = repository.recent(alert_id)[0]
            repository.image_path(evidence).write_bytes(png(800, 450))

            payload = repository.overall_audit()

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertEqual(payload["integrity_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
