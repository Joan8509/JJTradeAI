"""Pruebas de vigencia temporal metodologica."""

import unittest

from setup_timing import evaluate_setup_timing


def ct15(closed_through: str) -> dict:
    return {
        "data_source": {"closed_through": {"15m": closed_through}},
        "strategies": {"evaluations": [{
            "strategy_id": "CT15_ALCISTA",
            "bias": "CALL",
            "detected": True,
            "required_criteria_satisfied": True,
        }]},
    }


class SetupTimingTests(unittest.TestCase):
    def test_ct15_is_valid_only_on_first_fifteen_minute_bar(self) -> None:
        first = evaluate_setup_timing(ct15("2026-08-10T13:30:00+00:00"))
        later = evaluate_setup_timing(ct15("2026-08-10T19:45:00+00:00"))

        self.assertEqual(first["status"], "VIGENTE")
        self.assertEqual(later["status"], "VENCIDA")
        self.assertIn("primera vela", later["reason"])

    def test_unknown_strategy_does_not_receive_invented_window(self) -> None:
        payload = ct15("2026-08-10T19:45:00+00:00")
        payload["strategies"]["evaluations"][0]["strategy_id"] = "MOMENTUM_ALCISTA"

        result = evaluate_setup_timing(payload)

        self.assertEqual(result["status"], "NO_APLICA")


if __name__ == "__main__":
    unittest.main()
