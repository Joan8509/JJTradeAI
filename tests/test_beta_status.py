"""Pruebas del reporte beta generado desde estado real."""

import unittest

from beta_status import build_beta_status


RELEASE_OK = {"status": "OK", "check_count": 9, "failed_count": 0, "checks": [{"name": "unit_tests", "status": "OK"}]}


class BetaStatusTests(unittest.TestCase):
    def test_code_ready_but_missing_credentials_is_environment_blocked(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "BLOQUEADO", "network_status": "PENDIENTE", "checks": [{"status": "ERROR", "detail": "Faltan credenciales."}]},
            process={"status": "DETENIDO", "active": False},
        )
        self.assertEqual(payload["status"], "CODIGO_LISTO_ENTORNO_BLOQUEADO")
        self.assertEqual(payload["blockers"], ["Faltan credenciales."])
        self.assertFalse(payload["real_trading_authorized"])

    def test_valid_environment_without_process_is_ready_for_paper(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "LISTO_LOCAL", "network_status": "PENDIENTE", "checks": []},
            process={"status": "DETENIDO", "active": False},
            methodology={
                "status": "OK",
                "detector_count": 9,
                "partial_detector_count": 8,
                "methodology_complete": False,
            },
        )
        self.assertEqual(payload["status"], "LISTO_PARA_SESION_PAPER")
        self.assertEqual(payload["methodology_coverage_status"], "OK")
        self.assertEqual(payload["methodology_detector_count"], 9)
        self.assertEqual(payload["methodology_partial_detector_count"], 8)
        self.assertTrue(payload["methodology_limitations_remain"])

    def test_release_failure_has_precedence(self) -> None:
        payload = build_beta_status(
            release={"status": "BLOQUEADO", "check_count": 1, "failed_count": 1, "checks": []},
            preflight={"status": "LISTO", "checks": []},
            process={"status": "ACTIVO", "active": True},
        )
        self.assertEqual(payload["status"], "BLOQUEADO_CODIGO")

    def test_methodology_coverage_failure_blocks_code(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "LISTO", "checks": []},
            process={"status": "DETENIDO", "active": False},
            methodology={"status": "BLOQUEADO", "methodology_complete": False},
        )

        self.assertEqual(payload["status"], "BLOQUEADO_CODIGO")
        self.assertIn(
            "La cobertura metodologica tiene inconsistencias.",
            payload["blockers"],
        )

    def test_open_incident_requires_recovery_without_reclassifying_code(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "LISTO", "network_status": "OK", "checks": []},
            process={"status": "ACTIVO", "active": True},
            methodology={"status": "OK", "methodology_complete": False},
            safety={
                "status": "OK",
                "paper_only": True,
                "order_execution": False,
                "learning_isolated": True,
            },
            paper_evidence={"status": "BLOQUEADO"},
            open_processing_incident_count=2,
        )

        self.assertEqual(payload["status"], "RECUPERACION_PAPER_REQUERIDA")
        self.assertEqual(payload["code_health"], "OK")
        self.assertEqual(payload["open_processing_incident_count"], 2)
        self.assertFalse(payload["real_market_validated"])
        self.assertTrue(payload["paper_only_verified"])
        self.assertTrue(payload["learning_isolated"])

    def test_approved_paper_evidence_marks_real_market_validation(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "LISTO", "network_status": "OK", "checks": []},
            process={"status": "DETENIDO", "active": False},
            safety={
                "status": "OK",
                "paper_only": True,
                "order_execution": False,
                "learning_isolated": True,
            },
            paper_evidence={"status": "APROBADO"},
            visual_evidence={
                "status": "APROBADO",
                "evidence_count": 3,
                "complete_alert_count": 1,
            },
        )

        self.assertEqual(payload["status"], "BETA_PAPER_VALIDADA")
        self.assertTrue(payload["real_market_validated"])
        self.assertEqual(payload["live_signal_path_status"], "LISTO")
        self.assertFalse(payload["live_signal_waits_for_visual_evidence"])
        self.assertFalse(payload["visual_evidence_required_for_live_signal"])
        self.assertEqual(
            payload["visual_evidence_role"],
            "AUDITORIA_POST_ALERTA_OPCIONAL",
        )
        self.assertEqual(payload["real_market_validation_status"], "APROBADO")
        self.assertTrue(payload["visual_evidence_validated"])
        self.assertEqual(payload["visual_evidence_count"], 3)
        self.assertEqual(payload["visual_complete_alert_count"], 1)
        self.assertFalse(
            any(
                "Alpaca" in action or "TC2000" in action
                for action in payload["validation_next_actions"]
            )
        )
        self.assertEqual(payload["post_alert_audit_actions"], [])

    def test_approved_paper_path_does_not_wait_for_missing_visual_evidence(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "LISTO", "network_status": "OK", "checks": []},
            process={"status": "DETENIDO", "active": False},
            safety={
                "status": "OK", "paper_only": True,
                "order_execution": False, "learning_isolated": True,
            },
            paper_evidence={"status": "APROBADO"},
            visual_evidence={
                "status": "NO_INICIADO", "evidence_count": 0,
                "complete_alert_count": 0,
            },
        )

        self.assertEqual(payload["status"], "BETA_PAPER_VALIDADA")
        self.assertEqual(payload["live_signal_path_status"], "LISTO")
        self.assertFalse(
            any("TC2000" in item for item in payload["validation_next_actions"])
        )
        self.assertTrue(payload["post_alert_audit_actions"])

    def test_safety_failure_blocks_code(self) -> None:
        payload = build_beta_status(
            release=RELEASE_OK,
            preflight={"status": "LISTO", "checks": []},
            process={"status": "DETENIDO", "active": False},
            safety={"status": "BLOQUEADO"},
        )

        self.assertEqual(payload["status"], "BLOQUEADO_CODIGO")
        self.assertIn("invariantes PAPER", " ".join(payload["blockers"]))

    def test_negative_incident_count_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_beta_status(
                release=RELEASE_OK,
                preflight=None,
                process={},
                open_processing_incident_count=-1,
            )


if __name__ == "__main__":
    unittest.main()
