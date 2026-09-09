"""Pruebas de la evidencia historica de una sesion PAPER real."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from live_market import MarketBar
from live_preflight import record_live_preflight
from live_service_runtime import ServiceHealthRepository
from market_reconciliation import MarketReconciliationRepository
from market_store import MarketBarStore
from paper_session_evidence import build_paper_session_evidence
from scanner_incident import ScannerIncidentRepository


NOW = datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)


class PaperSessionEvidenceTests(unittest.TestCase):
    def test_approves_accumulated_real_market_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            lock = Path(directory) / "scanner.lock"
            record_live_preflight(
                database,
                {
                    "status": "LISTO",
                    "network_status": "OK",
                    "symbols": ["SPY", "QQQ"],
                    "secrets_exposed": False,
                },
            )
            health = ServiceHealthRepository(database)
            health.start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY", "QQQ"),
            )
            health.update("live_strategy_scanner", "DETENIDO")
            store = MarketBarStore(database)
            reconciliations = MarketReconciliationRepository(database)
            for symbol in ("SPY", "QQQ"):
                for offset in range(15):
                    store.upsert_bar(
                        MarketBar(
                            symbol,
                            NOW - timedelta(minutes=14 - offset),
                            1,
                            2,
                            1,
                            1.5,
                            100,
                        ),
                        provider="ALPACA",
                        feed="iex",
                    )
                reconciliations.record(
                    provider="ALPACA",
                    feed="iex",
                    symbol=symbol,
                    trigger_timestamp=NOW,
                    payload={"status": "APROBADO", "difference_count": 0},
                )

            payload = build_paper_session_evidence(
                database,
                lock_file=lock,
                now=NOW,
            )

        self.assertEqual(payload["status"], "APROBADO")
        self.assertTrue(all(check["status"] == "OK" for check in payload["checks"]))
        self.assertEqual(payload["service_health"]["status"], "DETENIDO")
        self.assertFalse(payload["secrets_exposed"])
        self.assertFalse(payload["real_trading_authorized"])
        self.assertFalse(payload["order_execution"])
        self.assertEqual(payload["feed"], "iex")
        self.assertTrue(all(item["evidence_complete"] for item in payload["reconciliations"]))

    def test_reports_missing_database_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.db"
            payload = build_paper_session_evidence(
                database,
                lock_file=Path(directory) / "scanner.lock",
                now=NOW,
            )

            self.assertFalse(database.exists())

        self.assertEqual(payload["status"], "NO_INICIADO")

    def test_corrupt_database_returns_blocked_report_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "corrupt.db"
            database.write_bytes(b"not a sqlite database")

            payload = build_paper_session_evidence(
                database,
                lock_file=Path(directory) / "scanner.lock",
                now=NOW,
            )

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertEqual(payload["checks"][0]["status"], "ERROR")
        self.assertIn("restaurar", payload["next_actions"][0])
        self.assertFalse(payload["secrets_exposed"])

    def test_rejected_reconciliation_blocks_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            record_live_preflight(
                database,
                {"status": "LISTO", "network_status": "OK", "symbols": ["SPY"]},
            )
            ServiceHealthRepository(database).start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY",),
            )
            MarketBarStore(database).upsert_bar(
                MarketBar("SPY", NOW, 1, 2, 1, 1.5, 100),
                provider="ALPACA",
                feed="iex",
            )
            MarketReconciliationRepository(database).record(
                provider="ALPACA",
                feed="iex",
                symbol="SPY",
                trigger_timestamp=NOW,
                payload={"status": "RECHAZADO", "difference_count": 1},
            )

            payload = build_paper_session_evidence(
                database,
                lock_file=Path(directory) / "scanner.lock",
                now=NOW,
            )

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertIn("diferencias", payload["next_actions"][0])

    def test_one_bar_is_not_enough_for_real_session_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            record_live_preflight(
                database,
                {"status": "LISTO", "network_status": "OK", "symbols": ["SPY"]},
            )
            ServiceHealthRepository(database).start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY",),
            )
            MarketBarStore(database).upsert_bar(
                MarketBar("SPY", NOW, 1, 2, 1, 1.5, 100),
                provider="ALPACA",
                feed="iex",
            )

            payload = build_paper_session_evidence(
                database,
                lock_file=Path(directory) / "scanner.lock",
                now=NOW,
            )

        self.assertEqual(payload["status"], "EN_CURSO")
        self.assertIn("15 barras", " ".join(payload["next_actions"]))

    def test_nonzero_differences_block_even_if_status_says_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            record_live_preflight(
                database,
                {"status": "LISTO", "network_status": "OK", "symbols": ["SPY"]},
            )
            ServiceHealthRepository(database).start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY",),
            )
            store = MarketBarStore(database)
            for offset in range(15):
                store.upsert_bar(
                    MarketBar(
                        "SPY",
                        NOW - timedelta(minutes=14 - offset),
                        1,
                        2,
                        1,
                        1.5,
                        100,
                    ),
                    provider="ALPACA",
                    feed="iex",
                )
            MarketReconciliationRepository(database).record(
                provider="ALPACA",
                feed="iex",
                symbol="SPY",
                trigger_timestamp=NOW,
                payload={"status": "APROBADO", "difference_count": 2},
            )

            payload = build_paper_session_evidence(
                database,
                lock_file=Path(directory) / "scanner.lock",
                now=NOW,
            )

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertFalse(payload["reconciliations"][0]["evidence_complete"])

    def test_open_processing_incident_blocks_otherwise_approved_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            lock = Path(directory) / "scanner.lock"
            record_live_preflight(
                database,
                {"status": "LISTO", "network_status": "OK", "symbols": ["SPY"]},
            )
            ServiceHealthRepository(database).start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY",),
            )
            store = MarketBarStore(database)
            for offset in range(15):
                store.upsert_bar(
                    MarketBar(
                        "SPY",
                        NOW - timedelta(minutes=14 - offset),
                        1,
                        2,
                        1,
                        1.5,
                        100,
                    ),
                    provider="ALPACA",
                    feed="iex",
                )
            MarketReconciliationRepository(database).record(
                provider="ALPACA",
                feed="iex",
                symbol="SPY",
                trigger_timestamp=NOW,
                payload={"status": "APROBADO", "difference_count": 0},
            )
            ScannerIncidentRepository(database).record(
                symbol="SPY",
                bar_timestamp=NOW,
                error=RuntimeError("detector failure"),
            )

            payload = build_paper_session_evidence(
                database,
                lock_file=lock,
                now=NOW,
            )

        self.assertEqual(payload["status"], "BLOQUEADO")
        self.assertEqual(payload["processing_incidents"]["open_count"], 1)
        self.assertNotIn(
            "error_detail",
            payload["processing_incidents"]["open"][0],
        )
        self.assertIn("recuperacion", payload["next_actions"][0])

    def test_resolved_processing_incident_is_audited_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            lock = Path(directory) / "scanner.lock"
            record_live_preflight(
                database,
                {"status": "LISTO", "network_status": "OK", "symbols": ["SPY"]},
            )
            ServiceHealthRepository(database).start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY",),
            )
            store = MarketBarStore(database)
            for offset in range(15):
                store.upsert_bar(
                    MarketBar(
                        "SPY",
                        NOW - timedelta(minutes=14 - offset),
                        1,
                        2,
                        1,
                        1.5,
                        100,
                    ),
                    provider="ALPACA",
                    feed="iex",
                )
            MarketReconciliationRepository(database).record(
                provider="ALPACA",
                feed="iex",
                symbol="SPY",
                trigger_timestamp=NOW,
                payload={"status": "APROBADO", "difference_count": 0},
            )
            incidents = ScannerIncidentRepository(database)
            incidents.record(
                symbol="SPY",
                bar_timestamp=NOW - timedelta(minutes=15),
                error=RuntimeError("temporary failure"),
            )
            incidents.resolve_open(
                symbol="SPY",
                resolution_bar_timestamp=NOW,
            )

            payload = build_paper_session_evidence(
                database,
                lock_file=lock,
                now=NOW,
            )

        self.assertEqual(payload["status"], "APROBADO")
        self.assertEqual(payload["processing_incidents"]["open_count"], 0)
        self.assertEqual(
            len(payload["processing_incidents"]["resolved_in_session"]),
            1,
        )

    def test_does_not_reuse_evidence_created_before_remote_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            store = MarketBarStore(database)
            for offset in range(15):
                store.upsert_bar(
                    MarketBar(
                        "SPY",
                        NOW - timedelta(minutes=14 - offset),
                        1,
                        2,
                        1,
                        1.5,
                        100,
                    ),
                    provider="ALPACA",
                    feed="iex",
                )
            MarketReconciliationRepository(database).record(
                provider="ALPACA",
                feed="iex",
                symbol="SPY",
                trigger_timestamp=NOW,
                payload={"status": "APROBADO", "difference_count": 0},
            )
            record_live_preflight(
                database,
                {"status": "LISTO", "network_status": "OK", "symbols": ["SPY"]},
            )
            ServiceHealthRepository(database).start(
                "live_strategy_scanner",
                provider="ALPACA",
                feed="iex",
                symbols=("SPY",),
            )

            payload = build_paper_session_evidence(
                database,
                lock_file=Path(directory) / "scanner.lock",
                now=NOW,
            )

        self.assertEqual(payload["status"], "EN_CURSO")
        self.assertEqual(payload["bars"][0]["bar_count"], 0)
        self.assertEqual(payload["reconciliations"][0]["status"], "FALTANTE")
        self.assertIsNotNone(payload["session"]["preflight_run_id"])


if __name__ == "__main__":
    unittest.main()
