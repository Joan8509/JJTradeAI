"""Pruebas de reevaluación derivada e inmutable."""

import unittest

from alert_reevaluation import reevaluate_alert


def report():
    criterion = {"criterion_id": "ok", "name": "OK", "status": "CUMPLE", "required": True, "detail": "Cumple.", "source": "test"}
    invalidation = lambda cid: {"criterion_id": cid, "name": cid, "status": "NO_DISPONIBLE", "required": True, "detail": "Pendiente.", "source": "test"}
    return {
        "data_as_of": "2026-07-21T14:00:00Z",
        "strategies": {"evaluations": [{"strategy_id": "TEST", "name": "Test", "bias": "CALL", "detected": True, "criteria": [criterion], "timeframe": "15m"}]},
        "invalidations": [invalidation("relevant_news"), invalidation("stale_data")],
        "panorama": {"conflicts": []},
        "live_data_freshness": {"status": "APROBADO"},
        "decision": {"data_quality_status": "APROBADO", "risk_status": "NO_DISPONIBLE", "governance_status": "NO_DISPONIBLE"},
    }


class AlertReevaluationTests(unittest.TestCase):
    def test_human_approval_does_not_bypass_risk_or_governance(self):
        original = report()
        result = reevaluate_alert(original, {"id": 4, "path_clear": True, "news_clear": True, "panorama_approved": True})
        self.assertEqual(result["panorama_status"], "APROBADO")
        self.assertEqual(result["decision"]["decision"], "NO_OPERAR")
        self.assertEqual(result["decision"]["risk_status"], "NO_DISPONIBLE")
        self.assertNotIn("review_id", original)

    def test_any_human_rejection_rejects_panorama(self):
        result = reevaluate_alert(report(), {"id": 5, "path_clear": False, "news_clear": True, "panorama_approved": True})
        self.assertEqual(result["panorama_status"], "RECHAZADO")

    def test_eligible_selected_contract_can_approve_only_risk_gate(self):
        selection = {"id": 9, "candidate": {"symbol": "SPY260724C00600000", "eligible": True, "risk_status": "APROBADO"}}
        result = reevaluate_alert(
            report(),
            {"id": 6, "path_clear": True, "news_clear": True, "panorama_approved": True},
            selection,
        )
        self.assertEqual(result["decision"]["risk_status"], "APROBADO")
        self.assertEqual(result["decision"]["governance_status"], "NO_DISPONIBLE")
        self.assertEqual(result["decision"]["decision"], "NO_OPERAR")
        self.assertEqual(result["selected_contract"], "SPY260724C00600000")

    def test_approved_governance_and_contract_can_complete_call_decision(self):
        selection = {"id": 9, "candidate": {"symbol": "SPY260724C00600000", "eligible": True, "risk_status": "APROBADO"}}
        governance = {"id": 12, "status": "APROBADO"}
        result = reevaluate_alert(
            report(),
            {"id": 7, "path_clear": True, "news_clear": True, "panorama_approved": True},
            selection,
            governance,
        )
        self.assertEqual(result["decision"]["governance_status"], "APROBADO")
        self.assertEqual(result["decision"]["decision"], "CALL")
        self.assertEqual(result["governance_review_id"], 12)
        self.assertEqual(result["visual_evidence"]["status"], "OMITIDO")

    def test_pending_visual_evidence_blocks_otherwise_complete_decision(self):
        selection = {"id": 9, "candidate": {"symbol": "SPY260724C00600000", "eligible": True, "risk_status": "APROBADO"}}
        governance = {"id": 12, "status": "APROBADO"}
        visual = {
            "status": "INTEGRO",
            "generated_at": "2026-07-27T15:00:00Z",
            "evidence_count": 1,
            "items": [{
                "evidence_id": 3, "timeframe": "15m", "content_hash": "a" * 64,
                "integrity_status": "OK", "latest_review_status": "PENDIENTE",
                "created_at": "2026-07-27T14:30:00Z",
            }],
        }

        result = reevaluate_alert(
            report(),
            {"id": 8, "path_clear": True, "news_clear": True, "panorama_approved": True},
            selection,
            governance,
            visual,
        )

        self.assertEqual(result["visual_evidence"]["status"], "REQUIERE_REVISION")
        self.assertEqual(result["panorama_status"], "REQUIERE_REVISION")
        self.assertEqual(result["decision"]["decision"], "NO_OPERAR")

    def test_visual_disagreement_rejects_panorama(self):
        visual = {
            "status": "INTEGRO", "evidence_count": 1,
            "items": [{
                "evidence_id": 4, "timeframe": "1H", "content_hash": "b" * 64,
                "integrity_status": "OK", "latest_review_status": "DIFIERE",
                "created_at": "2026-07-27T14:30:00Z",
                "latest_review_at": "2026-07-27T14:45:00Z",
            }],
        }

        result = reevaluate_alert(
            report(),
            {"id": 9, "path_clear": True, "news_clear": True, "panorama_approved": True},
            visual_audit=visual,
        )

        self.assertEqual(result["visual_evidence"]["status"], "RECHAZADO")
        self.assertEqual(result["panorama_status"], "RECHAZADO")

    def test_integral_coincident_visual_evidence_can_corrobate(self):
        selection = {"id": 9, "candidate": {"symbol": "SPY260724C00600000", "eligible": True, "risk_status": "APROBADO"}}
        governance = {"id": 12, "status": "APROBADO"}
        visual = {
            "status": "INTEGRO", "evidence_count": 1,
            "items": [{
                "evidence_id": 5, "timeframe": "1D", "content_hash": "c" * 64,
                "integrity_status": "OK", "latest_review_status": "COINCIDE",
                "created_at": "2026-07-27T14:30:00Z",
                "latest_review_at": "2026-07-27T14:45:00Z",
            }],
        }

        result = reevaluate_alert(
            report(),
            {
                "id": 10,
                "created_at": "2026-07-27T15:00:00Z",
                "path_clear": True,
                "news_clear": True,
                "panorama_approved": True,
            },
            selection,
            governance,
            visual,
        )

        self.assertEqual(result["visual_evidence"]["status"], "APROBADO")
        self.assertEqual(result["decision"]["decision"], "CALL")
        self.assertEqual(result["visual_evidence"]["evidence_ids"], [5])
        self.assertTrue(
            result["visual_evidence"]["human_review_covers_visual_evidence"]
        )

    def test_visual_change_after_human_review_requires_new_review(self):
        visual = {
            "status": "INTEGRO", "evidence_count": 1,
            "items": [{
                "evidence_id": 6, "timeframe": "15m", "content_hash": "d" * 64,
                "integrity_status": "OK", "latest_review_status": "COINCIDE",
                "created_at": "2026-07-27T15:00:00Z",
                "latest_review_at": "2026-07-27T15:05:00Z",
            }],
        }

        result = reevaluate_alert(
            report(),
            {
                "id": 11,
                "created_at": "2026-07-27T14:59:00Z",
                "path_clear": True,
                "news_clear": True,
                "panorama_approved": True,
            },
            visual_audit=visual,
        )

        self.assertEqual(result["visual_evidence"]["status"], "REQUIERE_REVISION")
        self.assertFalse(
            result["visual_evidence"]["human_review_covers_visual_evidence"]
        )


if __name__ == "__main__":
    unittest.main()
