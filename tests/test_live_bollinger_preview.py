"""Pruebas del radar intravela y su vigencia metodologica."""

import unittest

from live_bollinger_preview import attach_strategy_preview
from strategy_registry import STRATEGY_REGISTRY


class LiveStrategyPreviewTests(unittest.TestCase):
    def _report(self) -> dict[str, object]:
        return {
            "strategies": {
                "evaluations": [{
                    "strategy_id": "RETORNO_BOLLINGER_LATERAL_BAJISTA",
                    "name": "Retorno Bajista a Bollinger",
                    "bias": "PUT", "timeframe": "15m", "detected": True,
                    "criteria": [],
                }]
            }
        }

    def test_opening_strategy_is_visible_at_five_minute_close(self) -> None:
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T13:34:00+00:00"}, self._report()
        )
        self.assertEqual(len(result["strategies"]), 1)

    def test_opening_strategy_expires_after_first_five_minutes(self) -> None:
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T13:35:00+00:00"}, self._report()
        )
        self.assertEqual(result["strategies"], [])

    def test_plain_bollinger_exposure_does_not_assign_call_or_put(self) -> None:
        report = {"strategies": {"evaluations": [{
            "strategy_id": "EXPUESTO_BOLLINGER_INFERIOR",
            "name": "Expuesto Bollinger Inferior", "bias": "CALL",
            "timeframe": "15m", "detected": True, "criteria": [],
        }]}}
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T15:00:00+00:00"}, report
        )
        self.assertEqual(result["strategies"][0]["bias"], "ESPERAR")
        self.assertEqual(
            result["strategies"][0]["direction_status"],
            "SIN DIRECCIÓN CONFIRMADA",
        )

    def test_conflicting_methodology_directions_are_downgraded(self) -> None:
        evaluations = [
            {"strategy_id": "CAMBIO_TENDENCIA_HORA_ALCISTA", "name": "Alcista",
             "bias": "CALL", "timeframe": "1H", "detected": True, "criteria": []},
            {"strategy_id": "REBOTE_PUNTO_MEDIO_BAJISTA", "name": "Bajista",
             "bias": "PUT", "timeframe": "1H", "detected": True, "criteria": []},
        ]
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T15:00:00+00:00"},
            {"strategies": {"evaluations": evaluations}},
        )
        self.assertTrue(all(
            item["bias"] == "ESPERAR" for item in result["strategies"]
        ))
        self.assertTrue(all(
            item["direction_status"] == "DIRECCIONES EN CONFLICTO"
            for item in result["strategies"]
        ))

    def test_efecto_iman_is_visible_when_only_worden_is_pending(self) -> None:
        criteria = [
            {"criterion_id": "directional_gap", "name": "Salto", "required": True,
             "status": "CUMPLE"},
            {"criterion_id": "worden_volume_cross", "name": "Volumen Worden",
             "required": True, "status": "NO_DISPONIBLE"},
        ]
        report = {"strategies": {"evaluations": [{
            "strategy_id": "EFECTO_IMAN_TENDENCIA_ALCISTA",
            "name": "Efecto ImÃ¡n en Tendencia Alcista", "bias": "PUT",
            "timeframe": "15m+1H+1D", "detected": False, "criteria": criteria,
        }]}}
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T15:00:00+00:00"}, report
        )
        self.assertEqual(len(result["strategies"]), 1)
        self.assertEqual(result["strategies"][0]["bias"], "ESPERAR")
        self.assertEqual(result["strategies"][0]["potential_bias"], "PUT")
        self.assertIn("REQUIERE CONFIRMACION", result["strategies"][0]["direction_status"])

    def test_efecto_iman_stays_hidden_when_geometry_fails(self) -> None:
        criteria = [
            {"criterion_id": "directional_gap", "name": "Salto", "required": True,
             "status": "NO_CUMPLE"},
            {"criterion_id": "worden_volume_cross", "name": "Volumen Worden",
             "required": True, "status": "NO_DISPONIBLE"},
        ]
        report = {"strategies": {"evaluations": [{
            "strategy_id": "EFECTO_IMAN_TENDENCIA_ALCISTA", "name": "Efecto ImÃ¡n",
            "bias": "PUT", "detected": False, "criteria": criteria,
        }]}}
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T15:00:00+00:00"}, report
        )
        self.assertEqual(result["strategies"], [])

    def test_any_strategy_can_be_visible_when_detected(self) -> None:
        evaluations = [
            {
                "strategy_id": strategy_id,
                "name": metadata["nombre"],
                "bias": "CALL" if index % 2 == 0 else "PUT",
                "timeframe": "15m",
                "detected": True,
                "criteria": [],
            }
            for index, (strategy_id, metadata) in enumerate(STRATEGY_REGISTRY.items())
        ]
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T13:34:00+00:00"},
            {"strategies": {"evaluations": evaluations}},
        )
        visible_ids = {item["strategy_id"] for item in result["strategies"]}
        self.assertEqual(visible_ids, set(STRATEGY_REGISTRY))

    def test_non_magnet_strategy_is_visible_while_confirmation_is_pending(self) -> None:
        report = {"strategies": {"evaluations": [{
            "strategy_id": "MOMENTUM_ALCISTA", "name": "Momentum Alcista",
            "bias": "CALL", "detected": False,
            "criteria": [
                {"criterion_id": "structure", "name": "Estructura", "required": True,
                 "status": "CUMPLE"},
                {"criterion_id": "path", "name": "Camino libre", "required": True,
                 "status": "REQUIERE_REVISION"},
            ],
        }]}}
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T15:00:00+00:00"}, report
        )
        self.assertEqual(result["strategies"][0]["bias"], "ESPERAR")
        self.assertEqual(result["strategies"][0]["potential_bias"], "CALL")


if __name__ == "__main__":
    unittest.main()
