"""Fuentes de datos normalizadas para JJTrade AI."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import IO, Any

import pandas as pd

from data_loader import load_tc2000_txt, load_tc2000_upload
from indicators import add_bollinger_metrics, add_gap_metrics, calculate_bollinger


TIMEFRAME_LABELS = ("15m", "1H", "1D")


class DataProviderKind(str, Enum):
    """Fuentes de datos admitidas por la arquitectura."""

    TC2000_TXT = "TC2000_TXT"
    TC2000_UPLOAD = "TC2000_UPLOAD"
    MARKET_DATA_API = "MARKET_DATA_API"
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"


@dataclass(frozen=True)
class DataBundle:
    """Datos canónicos junto con trazabilidad de la fuente."""

    provider: DataProviderKind
    datasets: Mapping[str, pd.DataFrame]
    metadata: Mapping[str, Any]
    auxiliary_datasets: Mapping[str, pd.DataFrame] = field(default_factory=dict)


def _ordered_available_timeframes(
    candidates: object,
    datasets: Mapping[str, pd.DataFrame],
) -> tuple[str, ...]:
    if isinstance(candidates, (list, tuple, set)):
        requested = {str(item) for item in candidates}
    else:
        requested = set(datasets)
    return tuple(
        timeframe
        for timeframe in TIMEFRAME_LABELS
        if timeframe in requested and timeframe in datasets
    )


def data_source_metadata(bundle: DataBundle) -> dict[str, Any]:
    """Devuelve metadatos auditables sin campos sensibles ni arbitrarios."""
    timeframes = _ordered_available_timeframes(
        bundle.metadata.get("timeframes"),
        bundle.datasets,
    )
    raw_files = bundle.metadata.get("files", {})
    files: dict[str, str] = {}
    if isinstance(raw_files, Mapping):
        files = {
            timeframe: str(raw_files[timeframe])
            for timeframe in timeframes
            if timeframe in raw_files and raw_files[timeframe] is not None
        }

    metadata: dict[str, Any] = {
        "provider": bundle.provider.value,
        "timeframes": timeframes,
    }
    for field in ("vendor", "symbol", "feed"):
        value = bundle.metadata.get(field)
        if isinstance(value, str) and value.strip():
            metadata[field] = value.strip()
    closed_through = bundle.metadata.get("closed_through")
    if isinstance(closed_through, Mapping):
        safe_closed = {
            timeframe: str(closed_through[timeframe])
            for timeframe in timeframes
            if timeframe in closed_through
        }
        if safe_closed:
            metadata["closed_through"] = safe_closed
    if files:
        metadata["files"] = files
    return metadata


def prepare_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Agrega indicadores base requeridos por el motor."""
    prepared = calculate_bollinger(frame)
    prepared = add_bollinger_metrics(prepared)
    return add_gap_metrics(prepared)


def load_tc2000_file_bundle(
    *,
    timeframe_15m: str | Path | None = None,
    timeframe_1h: str | Path | None = None,
    timeframe_1d: str | Path | None = None,
) -> dict[str, Any]:
    """Carga archivos TC2000 locales y produce datasets canónicos."""
    candidates = {
        "15m": timeframe_15m,
        "1H": timeframe_1h,
        "1D": timeframe_1d,
    }
    datasets = {
        timeframe: prepare_market_frame(load_tc2000_txt(path))
        for timeframe, path in candidates.items()
        if path is not None
    }
    if not datasets:
        raise ValueError("Debe proveerse al menos un archivo TC2000.")
    return datasets


def load_tc2000_file_data_bundle(
    *,
    timeframe_15m: str | Path | None = None,
    timeframe_1h: str | Path | None = None,
    timeframe_1d: str | Path | None = None,
) -> DataBundle:
    """Carga archivos TC2000 locales y conserva trazabilidad de rutas."""
    paths = {
        "15m": timeframe_15m,
        "1H": timeframe_1h,
        "1D": timeframe_1d,
    }
    datasets = load_tc2000_file_bundle(
        timeframe_15m=timeframe_15m,
        timeframe_1h=timeframe_1h,
        timeframe_1d=timeframe_1d,
    )
    return DataBundle(
        provider=DataProviderKind.TC2000_TXT,
        datasets=datasets,
        metadata={
            "timeframes": tuple(datasets),
            "files": {
                timeframe: str(path)
                for timeframe, path in paths.items()
                if path is not None
            },
        },
    )


def load_tc2000_upload_bundle(
    uploads: Mapping[str, IO[bytes]],
) -> dict[str, pd.DataFrame]:
    """Carga archivos TC2000 subidos desde la interfaz."""
    datasets: dict[str, pd.DataFrame] = {}
    for timeframe in TIMEFRAME_LABELS:
        uploaded = uploads.get(timeframe)
        if uploaded is None:
            continue
        filename = str(getattr(uploaded, "name", f"{timeframe}.txt"))
        datasets[timeframe] = prepare_market_frame(
            load_tc2000_upload(uploaded, filename)
        )
    if not datasets:
        raise ValueError("Debe proveerse al menos un archivo TC2000.")
    return datasets


def load_tc2000_upload_data_bundle(
    uploads: Mapping[str, IO[bytes]],
) -> DataBundle:
    """Carga uploads TC2000 y conserva nombres de archivos recibidos."""
    datasets = load_tc2000_upload_bundle(uploads)
    return DataBundle(
        provider=DataProviderKind.TC2000_UPLOAD,
        datasets=datasets,
        metadata={
            "timeframes": tuple(datasets),
            "files": {
                timeframe: str(getattr(uploads[timeframe], "name", ""))
                for timeframe in datasets
            },
        },
    )


def build_demo_data_bundle(datasets: Mapping[str, pd.DataFrame]) -> DataBundle:
    """Prepara datasets sintéticos y marca su origen educativo."""
    prepared = {
        timeframe: prepare_market_frame(frame)
        for timeframe, frame in datasets.items()
    }
    return DataBundle(
        provider=DataProviderKind.DEMO_SYNTHETIC,
        datasets=prepared,
        metadata={"timeframes": tuple(prepared)},
    )
