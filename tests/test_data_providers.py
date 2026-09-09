"""Pruebas de fuentes de datos normalizadas."""

from io import BytesIO
from pathlib import Path
import unittest

import pandas as pd

from data_providers import (
    DataBundle,
    DataProviderKind,
    build_demo_data_bundle,
    data_source_metadata,
    load_tc2000_file_data_bundle,
    load_tc2000_file_bundle,
    load_tc2000_upload_data_bundle,
    load_tc2000_upload_bundle,
    prepare_market_frame,
)
from data_loader import load_tc2000_txt
from demo_data import generate_demo_datasets


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "exports" / "sample.txt"


class NamedBytesIO(BytesIO):
    """Buffer con nombre para simular uploads de Streamlit."""

    def __init__(self, payload: bytes, name: str) -> None:
        super().__init__(payload)
        self.name = name


class DataProviderTests(unittest.TestCase):
    def test_prepare_market_frame_adds_required_metrics(self) -> None:
        frame = load_tc2000_txt(SAMPLE_PATH)

        result = prepare_market_frame(frame)

        self.assertIn("bollinger_upper", result.columns)
        self.assertIn("gap_pct", result.columns)

    def test_tc2000_file_bundle_loads_available_timeframes(self) -> None:
        result = load_tc2000_file_bundle(
            timeframe_15m=SAMPLE_PATH,
            timeframe_1h=SAMPLE_PATH,
        )

        self.assertEqual(set(result), {"15m", "1H"})

    def test_tc2000_file_data_bundle_preserves_source_metadata(self) -> None:
        result = load_tc2000_file_data_bundle(timeframe_15m=SAMPLE_PATH)

        self.assertIs(result.provider, DataProviderKind.TC2000_TXT)
        self.assertEqual(set(result.datasets), {"15m"})
        self.assertEqual(result.metadata["timeframes"], ("15m",))
        self.assertIn("15m", result.metadata["files"])

    def test_tc2000_upload_bundle_uses_timeframe_keys(self) -> None:
        payload = SAMPLE_PATH.read_bytes()
        result = load_tc2000_upload_bundle(
            {"15m": NamedBytesIO(payload, "sample.txt")}
        )

        self.assertEqual(set(result), {"15m"})
        self.assertIn("bollinger_mid", result["15m"].columns)

    def test_tc2000_upload_data_bundle_preserves_source_metadata(self) -> None:
        payload = SAMPLE_PATH.read_bytes()
        result = load_tc2000_upload_data_bundle(
            {"15m": NamedBytesIO(payload, "sample.txt")}
        )

        self.assertIs(result.provider, DataProviderKind.TC2000_UPLOAD)
        self.assertEqual(result.metadata["files"], {"15m": "sample.txt"})

    def test_demo_data_bundle_marks_synthetic_provider(self) -> None:
        result = build_demo_data_bundle(generate_demo_datasets())

        self.assertIs(result.provider, DataProviderKind.DEMO_SYNTHETIC)
        self.assertIn("15m", result.datasets)
        self.assertEqual(set(result.metadata["timeframes"]), set(result.datasets))

    def test_data_source_metadata_uses_safe_whitelist(self) -> None:
        bundle = DataBundle(
            provider=DataProviderKind.MARKET_DATA_API,
            datasets={"15m": pd.DataFrame(), "1D": pd.DataFrame()},
            metadata={
                "timeframes": ["1D", "15m", "BAD"],
                "files": {"15m": "SPY_15m.txt", "BAD": "ignored.txt"},
                "api_key": "SECRET",
                "token": "SECRET",
                "vendor": "ALPACA",
                "symbol": "SPY",
                "feed": "sip",
                "closed_through": {"15m": "2026-07-20T14:00:00Z", "BAD": "ignored"},
            },
        )

        result = data_source_metadata(bundle)

        self.assertEqual(result["provider"], "MARKET_DATA_API")
        self.assertEqual(result["timeframes"], ("15m", "1D"))
        self.assertEqual(result["files"], {"15m": "SPY_15m.txt"})
        self.assertNotIn("api_key", result)
        self.assertNotIn("token", result)
        self.assertEqual(result["vendor"], "ALPACA")
        self.assertEqual(result["symbol"], "SPY")
        self.assertEqual(result["feed"], "sip")
        self.assertEqual(
            result["closed_through"], {"15m": "2026-07-20T14:00:00Z"}
        )

    def test_data_source_metadata_falls_back_to_dataset_timeframes(self) -> None:
        bundle = DataBundle(
            provider=DataProviderKind.DEMO_SYNTHETIC,
            datasets={"1H": pd.DataFrame(), "15m": pd.DataFrame()},
            metadata={},
        )

        result = data_source_metadata(bundle)

        self.assertEqual(result["timeframes"], ("15m", "1H"))

    def test_empty_provider_bundle_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_tc2000_file_bundle()
        with self.assertRaises(ValueError):
            load_tc2000_upload_bundle({})


if __name__ == "__main__":
    unittest.main()
