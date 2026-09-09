"""Pruebas del estado consolidado de preparación PAPER."""

import unittest

from paper_readiness import evaluate_paper_readiness


class PaperReadinessTests(unittest.TestCase):
    def test_missing_credentials_block_configuration_and_never_authorize_real(self) -> None:
        result = evaluate_paper_readiness(
            preflight={"status": "BLOQUEADO", "checks": [{"name": "credentials", "status": "ERROR", "detail": "Faltan ALPACA_API_KEY o ALPACA_API_SECRET."}]},
            process={"active": False}, operational={"status": "NO_INICIADO"},
            pending_alert_count=0,
        )
        self.assertEqual(result["status"], "BLOQUEADO_CONFIG")
        self.assertTrue(any("Configurar ALPACA" in item for item in result["next_actions"]))
        self.assertFalse(result["real_trading_authorized"])

    def test_valid_preflight_without_process_is_ready_to_start(self) -> None:
        result = evaluate_paper_readiness(
            preflight={"status": "LISTO_LOCAL", "checks": []},
            process={"active": False}, operational={"status": "NO_INICIADO"},
            pending_alert_count=0,
        )
        self.assertEqual(result["status"], "LISTO_INICIAR")

    def test_active_ready_service_is_paper_ready_and_preserves_warnings(self) -> None:
        result = evaluate_paper_readiness(
            preflight={"status": "LISTO", "checks": [{"name": "option_policy", "status": "OMITIDO", "detail": "Opciones desactivadas."}]},
            process={"active": True}, operational={"status": "LISTO"},
            pending_alert_count=3,
        )
        self.assertEqual(result["status"], "LISTO_PAPER")
        self.assertEqual(result["pending_alert_count"], 3)
        self.assertEqual(result["warnings"], ["Opciones desactivadas."])

    def test_active_but_degraded_service_is_not_ready(self) -> None:
        result = evaluate_paper_readiness(
            preflight={"status": "LISTO", "checks": []}, process={"active": True},
            operational={"status": "DEGRADADO"}, pending_alert_count=0,
        )
        self.assertEqual(result["status"], "DEGRADADO")


if __name__ == "__main__":
    unittest.main()
