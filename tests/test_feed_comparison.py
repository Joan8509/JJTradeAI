"""Pruebas de comparacion descriptiva IEX-SIP."""

from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from data_providers import DataBundle, DataProviderKind, prepare_market_frame
from feed_comparison import compare_feed_bundles, compare_historical_detectors


START = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)


def frame(count: int, *, close_offset: float = 0.0) -> pd.DataFrame:
    return prepare_market_frame(pd.DataFrame({
        "date": [START + timedelta(minutes=15 * index) for index in range(count)],
        "open": [100.0 + index for index in range(count)],
        "high": [101.0 + index for index in range(count)],
        "low": [99.0 + index for index in range(count)],
        "close": [100.5 + index + close_offset for index in range(count)],
        "volume": [1000.0 + index for index in range(count)],
    }))


def bundle(*, close_offset: float = 0.0) -> DataBundle:
    datasets = {timeframe: frame(220, close_offset=close_offset) for timeframe in ("15m", "1H", "1D")}
    return DataBundle(provider=DataProviderKind.MARKET_DATA_API, datasets=datasets, metadata={})


class FeedComparisonTests(unittest.TestCase):
    def test_historical_replay_counts_close_level_detector_divergence(self) -> None:
        iex = {timeframe: frame(220) for timeframe in ("15m", "1H", "1D")}
        sip = {timeframe: frame(220, close_offset=1.0) for timeframe in ("15m", "1H", "1D")}

        def snapshotter(datasets):
            latest = float(datasets["15m"].iloc[-1]["close"])
            return {"TEST@15m": {"detected": latest >= 210.0, "bias": "CALL"}}

        result = compare_historical_detectors(
            iex, sip, sessions=2, snapshotter=snapshotter
        )

        self.assertGreater(result["evaluated_close_count"], 0)
        self.assertGreater(result["divergent_close_count"], 0)
        self.assertGreater(result["divergence_rate_pct"], 0)
        self.assertGreater(result["unique_divergence_episode_count"], 0)
        self.assertEqual(result["by_detector"][0]["detector"], "TEST@15m")

    def test_equal_bundles_have_equal_detectors_and_zero_price_difference(self) -> None:
        result = compare_feed_bundles(bundle(), bundle(), symbol="spy")

        self.assertEqual(result["status"], "DETECTORES_COINCIDEN")
        self.assertEqual(result["detector_difference_count"], 0)
        self.assertEqual(result["timeframes"]["15m"]["close_max_abs_difference"], 0.0)

    def test_price_difference_is_measured_without_inventing_approval_threshold(self) -> None:
        result = compare_feed_bundles(bundle(), bundle(close_offset=1.0), symbol="QQQ")

        self.assertEqual(result["timeframes"]["15m"]["close_max_abs_difference"], 1.0)
        self.assertEqual(result["authority"], "COMPARACION_DESCRIPTIVA_NO_AUTORIZA_OPERACIONES")


if __name__ == "__main__":
    unittest.main()
