import unittest
from bollinger_expansion import measure_band_expansion


class BandExpansionTests(unittest.TestCase):
    def test_each_band_not_total_width_must_expand(self):
        self.assertFalse(measure_band_expansion(113, 91, 110, 90).meets(0))
        self.assertFalse(measure_band_expansion(113, 90, 110, 90).meets(0))
        self.assertTrue(measure_band_expansion(113, 89, 110, 90).meets(0))

    def test_threshold_inclusive_for_both_candidates(self):
        one = measure_band_expansion(201, 99, 200, 100)
        two = measure_band_expansion(202, 98, 200, 100)
        self.assertTrue(one.meets(1)); self.assertFalse(one.meets(2))
        self.assertTrue(two.meets(1)); self.assertTrue(two.meets(2))
        self.assertFalse(measure_band_expansion(202, 99.5, 200, 100).meets(1))

    def test_scale_translation_and_direction_independent(self):
        normal = measure_band_expansion(202, 97, 200, 100)
        scaled = measure_band_expansion(2020, 970, 2000, 1000)
        translated = measure_band_expansion(302, 197, 300, 200)
        reflected = measure_band_expansion(203, 98, 200, 100)
        self.assertEqual(normal, scaled); self.assertEqual(normal, translated)
        self.assertEqual(normal.minimum_pct, reflected.minimum_pct)

    def test_non_finite_degenerate_and_invalid_threshold_rejected(self):
        for args in [(float('nan'), 1, 2, 1), (3, 1, 1, 1), (1, 3, 2, 1)]:
            with self.assertRaises(ValueError): measure_band_expansion(*args)
        measured = measure_band_expansion(3, 0, 2, 1)
        for value in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): measured.meets(value)


if __name__ == '__main__': unittest.main()
