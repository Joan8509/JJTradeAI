"""Pruebas del radar intravela y su vigencia metodologica."""

import unittest

from datetime import datetime, timedelta, timezone
import math
import pandas as pd

from live_bollinger_preview import attach_strategy_preview, evaluate_live_bollinger_preview
from strategy_registry import STRATEGY_REGISTRY


class LiveStrategyPreviewTests(unittest.TestCase):
    def test_week_window_preserves_preview_across_session_and_candle_boundaries(self):
        # A long archive, overnight bars and weekend boundaries must not change
        # the latest 20-period preview when the ingestion read is bounded.
        rows = []
        for day in pd.bdate_range('2026-09-14', '2026-10-15'):
            for minute in range(720):
                stamp = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)+timedelta(minutes=minute)
                price = 100+math.sin(len(rows)/31)
                rows.append(dict(date=stamp, open=price, high=price+.1,
                                 low=price-.1, close=price+.03, volume=100))
        frame = pd.DataFrame(rows)
        for end in (datetime(2026, 10, 12, 13, 30, tzinfo=timezone.utc),
                    datetime(2026, 10, 15, 13, 44, tzinfo=timezone.utc),
                    datetime(2026, 10, 15, 16, 8, tzinfo=timezone.utc),
                    datetime(2026, 10, 15, 19, 59, tzinfo=timezone.utc)):
            with self.subTest(end=end):
                archive = frame.loc[frame.date <= end]
                recent = archive.loc[archive.date >= end-timedelta(days=7)]
                full = evaluate_live_bollinger_preview(archive, symbol='AAPL', as_of=end)
                bounded = evaluate_live_bollinger_preview(recent, symbol='AAPL', as_of=end)
                for name in ('price', 'bollinger_upper', 'bollinger_lower'):
                    self.assertAlmostEqual(full[name], bounded[name], places=8)
                for name in set(full)-{'price', 'bollinger_upper', 'bollinger_lower'}:
                    self.assertEqual(full[name], bounded[name])

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

    def test_plain_bollinger_exposure_surfaces_probable_put_when_strong(self) -> None:
        report = {"strategies": {"evaluations": [{
            "strategy_id": "EXPUESTO_BOLLINGER_INFERIOR",
            "name": "Expuesto Bollinger Inferior", "bias": "PUT",
            "timeframe": "15m", "detected": True, "criteria": [],
        }]}}
        result = attach_strategy_preview(
            {"as_of": "2026-08-17T15:00:00+00:00"}, report
        )
        self.assertEqual(result["strategies"][0]["bias"], "ESPERAR")
        self.assertEqual(result["strategies"][0]["potential_bias"], "PUT")
        self.assertIn("PROBABLE", result["strategies"][0]["direction_status"])

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
