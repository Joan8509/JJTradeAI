"""Pruebas del mapa geométrico de medias móviles."""

import unittest

import pandas as pd

from analysis_models import DirectionBias
from levels_engine import map_moving_average_levels


class LevelsEngineTests(unittest.TestCase):
    def test_call_lists_closest_overhead_average_first(self) -> None:
        frame = pd.DataFrame(
            {
                "close": [100.0],
                "moving_average_20": [101.0],
                "moving_average_40": [105.0],
                "moving_average_100": [95.0],
                "moving_average_200": [90.0],
            }
        )

        levels = map_moving_average_levels({"1H": frame}, DirectionBias.CALL)

        self.assertEqual(levels[0].period, 20)
        self.assertTrue(levels[0].ahead_of_bias)
        self.assertEqual(levels[0].distance_pct, 1.0)

    def test_put_marks_levels_below_price_as_ahead(self) -> None:
        frame = pd.DataFrame(
            {"close": [100.0], "moving_average_20": [95.0]}
        )

        levels = map_moving_average_levels({"1D": frame}, DirectionBias.PUT)

        self.assertTrue(levels[0].ahead_of_bias)

    def test_neutral_bias_has_no_directional_level_map(self) -> None:
        self.assertEqual(map_moving_average_levels({}, DirectionBias.NEUTRAL), ())


if __name__ == "__main__":
    unittest.main()
