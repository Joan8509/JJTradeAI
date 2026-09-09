"""Pruebas del estado operativo consciente de sesiones."""

from datetime import date, datetime, timedelta, timezone
import unittest

from market_calendar import MarketSession
from operational_monitor import evaluate_operational_status, evaluate_reconciliation_coverage


NOW = datetime(2026, 7, 21, 15, 0, tzinfo=timezone.utc)
SESSION = MarketSession(date(2026, 7, 21), NOW - timedelta(hours=2), NOW + timedelta(hours=4))
PREFLIGHT = {"status": "LISTO"}


class OperationalMonitorTests(unittest.TestCase):
    def test_connected_recent_bar_is_ready_during_session(self) -> None:
        result = evaluate_operational_status(
            preflight=PREFLIGHT,
            health={"status": "CONECTADO", "last_bar_at": (NOW - timedelta(minutes=1)).isoformat()},
            session=SESSION, now=NOW,
        )
        self.assertEqual(result["status"], "LISTO")
        self.assertTrue(result["market_open"])

    def test_stale_bar_is_degraded_only_while_market_open(self) -> None:
        health = {"status": "CONECTADO", "last_bar_at": (NOW - timedelta(hours=2)).isoformat()}
        opened = evaluate_operational_status(preflight=PREFLIGHT, health=health, session=SESSION, now=NOW)
        closed = evaluate_operational_status(preflight=PREFLIGHT, health=health, session=None, now=NOW)
        self.assertEqual(opened["status"], "DEGRADADO")
        self.assertEqual(closed["status"], "LISTO_EN_ESPERA")

    def test_disconnected_is_blocked_even_outside_session(self) -> None:
        result = evaluate_operational_status(
            preflight=PREFLIGHT, health={"status": "DESCONECTADO"}, session=None, now=NOW
        )
        self.assertEqual(result["status"], "BLOQUEADO")

    def test_missing_remote_preflight_prevents_ready_status(self) -> None:
        result = evaluate_operational_status(
            preflight={"status": "LISTO_LOCAL"},
            health={"status": "CONECTADO", "last_bar_at": NOW.isoformat()},
            session=SESSION, now=NOW,
        )
        self.assertEqual(result["status"], "DEGRADADO")

    def test_rejected_latest_reconciliation_degrades_open_session(self) -> None:
        result = evaluate_operational_status(
            preflight=PREFLIGHT,
            health={"status": "CONECTADO", "last_bar_at": NOW.isoformat()},
            session=SESSION, now=NOW, reconciliation={"status": "RECHAZADO"},
        )
        self.assertEqual(result["status"], "DEGRADADO")
        self.assertTrue(any("reconciliación" in reason for reason in result["reasons"]))

    def test_multi_symbol_coverage_cannot_hide_rejected_asset(self) -> None:
        result = evaluate_operational_status(
            preflight=PREFLIGHT,
            health={"status": "CONECTADO", "last_bar_at": NOW.isoformat()},
            session=SESSION, now=NOW,
            expected_symbols=("SPY", "QQQ"),
            reconciliations={
                "SPY": {"status": "APROBADO", "trigger_timestamp": NOW.isoformat()},
                "QQQ": {"status": "RECHAZADO", "trigger_timestamp": NOW.isoformat()},
            },
        )
        self.assertEqual(result["status"], "DEGRADADO")
        self.assertTrue(any("QQQ" in reason for reason in result["reasons"]))

    def test_missing_symbol_has_opening_grace_then_becomes_degraded(self) -> None:
        opening = MarketSession(SESSION.session_date, NOW - timedelta(minutes=10), NOW + timedelta(hours=6))
        grace = evaluate_reconciliation_coverage(
            {}, expected_symbols=("SPY",), session=opening, now=NOW
        )
        self.assertEqual(grace["status"], "APROBADO")
        later = evaluate_reconciliation_coverage(
            {}, expected_symbols=("SPY",), session=SESSION, now=NOW
        )
        self.assertEqual(later["status"], "DEGRADADO")

    def test_stale_symbol_reconciliation_is_degraded(self) -> None:
        result = evaluate_reconciliation_coverage(
            {"SPY": {"status": "APROBADO", "trigger_timestamp": (NOW - timedelta(minutes=21)).isoformat()}},
            expected_symbols=("SPY",), session=SESSION, now=NOW,
        )
        self.assertEqual(result["status"], "DEGRADADO")

    def test_open_processing_incident_degrades_connected_service(self) -> None:
        result = evaluate_operational_status(
            preflight=PREFLIGHT,
            health={"status": "CONECTADO", "last_bar_at": NOW.isoformat()},
            session=SESSION,
            now=NOW,
            open_processing_incident_count=2,
        )

        self.assertEqual(result["status"], "DEGRADADO")
        self.assertTrue(
            any("2 incidente(s)" in reason for reason in result["reasons"])
        )

    def test_negative_incident_count_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no puede ser negativo"):
            evaluate_operational_status(
                preflight=PREFLIGHT,
                health=None,
                session=None,
                now=NOW,
                open_processing_incident_count=-1,
            )


if __name__ == "__main__":
    unittest.main()
