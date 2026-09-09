"""Pruebas de clasificación de eventos sin autoridad operativa."""

import unittest

from alert_event import classify_alert_event, classify_alert_transition


class AlertEventTests(unittest.TestCase):
    def test_unchanged_setup_is_auditable_without_repeated_ack(self) -> None:
        payload = {
            "strategy_summary": {"detected": 1, "confirmed": 1},
            "strategies": {"evaluations": [{
                "strategy_id": "CT15_ALCISTA", "bias": "CALL",
                "detected": True, "required_criteria_satisfied": True,
            }]},
        }

        event = classify_alert_transition(payload, payload)

        self.assertEqual(event["type"], "SETUP_SIN_CAMBIO")
        self.assertFalse(event["requires_ack"])

    def test_direction_change_creates_new_attention_event(self) -> None:
        def payload(bias):
            return {
                "strategy_summary": {"detected": 1, "confirmed": 1},
                "strategies": {"evaluations": [{
                    "strategy_id": f"CT15_{bias}", "bias": "CALL" if bias == "ALCISTA" else "PUT",
                    "detected": True, "required_criteria_satisfied": True,
                }]},
            }

        event = classify_alert_transition(payload("BAJISTA"), payload("ALCISTA"))

        self.assertEqual(event["type"], "SETUP_CONFIRMADO")
        self.assertTrue(event["requires_ack"])

    def test_expired_setup_does_not_alert_when_scanner_starts_late(self) -> None:
        payload = {
            "strategy_summary": {"detected": 1, "confirmed": 1},
            "setup_timing": {"status": "VENCIDA", "reason": "CT15 ya termino."},
            "strategies": {"evaluations": [{
                "strategy_id": "CT15_ALCISTA", "bias": "CALL",
                "detected": True, "required_criteria_satisfied": True,
            }]},
        }

        event = classify_alert_transition(payload, None)

        self.assertEqual(event["type"], "SETUP_VENCIDO")
        self.assertFalse(event["requires_ack"])

    def test_confirmed_strategy_requires_high_priority_market_ack(self) -> None:
        event = classify_alert_event({"strategy_summary": {"detected": 2, "confirmed": 1}})
        self.assertEqual(event["type"], "SETUP_CONFIRMADO")
        self.assertEqual(event["channel"], "MERCADO")
        self.assertTrue(event["requires_ack"])

    def test_no_setup_is_informational_and_does_not_require_ack(self) -> None:
        event = classify_alert_event({"strategy_summary": {"detected": 0, "confirmed": 0}})
        self.assertEqual(event["type"], "SIN_SETUP")
        self.assertFalse(event["requires_ack"])

    def test_data_incident_has_precedence_over_strategy_counts(self) -> None:
        event = classify_alert_event({
            "strategy_summary": {"detected": 2, "confirmed": 1},
            "market_data_reconciliation": {"status": "RECHAZADO"},
        })
        self.assertEqual(event["type"], "INCIDENTE_DATOS")
        self.assertEqual(event["channel"], "SISTEMA")


if __name__ == "__main__":
    unittest.main()
