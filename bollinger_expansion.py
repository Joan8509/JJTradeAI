"""Measure each band's outward movement against the previous band width.

The shared detector uses the explicitly authorized one-percent minimum.
This module never reads private configuration or emits signals.
"""
from dataclasses import dataclass
import math

MINIMUM_BAND_EXPANSION_PCT = 1.0


@dataclass(frozen=True)
class BandExpansion:
    upper_pct: float
    lower_pct: float

    @property
    def minimum_pct(self):
        return min(self.upper_pct, self.lower_pct)

    def meets(self, minimum_pct):
        minimum_pct = float(minimum_pct)
        if not math.isfinite(minimum_pct) or minimum_pct < 0:
            raise ValueError('INVALID_MINIMUM_BAND_EXPANSION')
        # A zero threshold still requires BOTH bands to move outward strictly.
        return self.minimum_pct > 0 and self.minimum_pct >= minimum_pct


def measure_band_expansion(upper, lower, previous_upper, previous_lower):
    upper, lower, previous_upper, previous_lower = map(
        float, (upper, lower, previous_upper, previous_lower))
    if not all(math.isfinite(v) for v in (upper, lower, previous_upper, previous_lower)):
        raise ValueError('INVALID_BAND_GEOMETRY')
    width = previous_upper - previous_lower
    if width <= 0 or upper <= lower:
        raise ValueError('INVALID_BAND_GEOMETRY')
    return BandExpansion(100 * (upper - previous_upper) / width,
                         100 * (previous_lower - lower) / width)


def expansion_evidence(upper, lower, previous_upper, previous_lower):
    measured = measure_band_expansion(upper, lower, previous_upper, previous_lower)
    return dict(upper=upper, lower=lower, previous_upper=previous_upper,
                previous_lower=previous_lower, upper_pct=measured.upper_pct,
                lower_pct=measured.lower_pct, minimum_pct=measured.minimum_pct,
                required_pct=MINIMUM_BAND_EXPANSION_PCT)
