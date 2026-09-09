"""Carga y normalización de archivos exportados desde TC2000."""

from pathlib import Path
import csv
import re
from typing import IO

import pandas as pd


REQUIRED_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "moving_average_20",
    "moving_average_40",
    "moving_average_100",
    "moving_average_200",
    "volume",
    "worden_stochastics",
)


def _clean_column_name(column_name: object) -> str:
    """Convierte un encabezado de TC2000 a formato minúsculo snake_case."""
    cleaned = str(column_name).replace("\ufeff", "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    return cleaned.strip("_")


def load_tc2000_txt(file_path: str | Path) -> pd.DataFrame:
    """Lee un TXT/CSV de TC2000 y devuelve sus datos limpios por fecha.

    El separador se detecta automáticamente para admitir tanto archivos CSV
    como archivos TXT delimitados por tabulaciones. Los datos inválidos
    producen una excepción descriptiva en lugar de continuar silenciosamente.
    """
    path = Path(file_path)
    if path.suffix.lower() not in {".txt", ".csv"}:
        raise ValueError("El archivo de TC2000 debe tener extensión .txt o .csv.")
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró el archivo de TC2000: {path}")

    df = _read_tc2000_table(path)
    return _normalize_tc2000_dataframe(df)


def load_tc2000_upload(file_object: IO[bytes], filename: str) -> pd.DataFrame:
    """Carga un archivo TC2000 recibido desde una interfaz de usuario."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".csv"}:
        raise ValueError("El archivo de TC2000 debe tener extensión .txt o .csv.")
    df = _read_tc2000_table(file_object)
    return _normalize_tc2000_dataframe(df)


def _read_tc2000_table(source: str | Path | IO[bytes]) -> pd.DataFrame:
    """Lee una tabla TC2000 y normaliza errores de parsing para el usuario."""
    try:
        return pd.read_csv(source, sep=None, engine="python")
    except (
        csv.Error,
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        raise ValueError("No se pudo leer el archivo de TC2000 como tabla.") from error


def _normalize_tc2000_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Valida y normaliza un DataFrame recién leído de TC2000."""
    df.columns = [_clean_column_name(column) for column in df.columns]

    if df.columns.duplicated().any():
        duplicates = sorted(set(df.columns[df.columns.duplicated()]))
        raise ValueError(f"Hay columnas duplicadas después de limpiarlas: {duplicates}")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(
            "Faltan columnas requeridas en el archivo de TC2000: "
            + ", ".join(missing_columns)
        )
    if df.empty:
        raise ValueError("El archivo de TC2000 no contiene filas de datos.")

    try:
        df["date"] = pd.to_datetime(df["date"], errors="raise")
    except (TypeError, ValueError) as error:
        raise ValueError("La columna Date contiene fechas inválidas.") from error
    if df["date"].isna().any():
        raise ValueError("La columna Date contiene fechas vacías.")

    numeric_columns = [column for column in REQUIRED_COLUMNS if column != "date"]
    for column in numeric_columns:
        normalized_values = df[column].astype(str).str.replace(",", "", regex=False)
        try:
            df[column] = pd.to_numeric(normalized_values, errors="raise").astype(float)
        except (TypeError, ValueError) as error:
            raise ValueError(f"La columna {column} contiene valores no numéricos.") from error
        if df[column].isna().any():
            raise ValueError(f"La columna {column} contiene valores vacíos.")
        if (df[column] < 0).any():
            raise ValueError(f"La columna {column} contiene valores negativos.")

    highest_body_value = df[["open", "low", "close"]].max(axis=1)
    lowest_body_value = df[["open", "high", "close"]].min(axis=1)
    if (df["high"] < highest_body_value).any():
        raise ValueError(
            "La columna high contiene valores menores que open, low o close."
        )
    if (df["low"] > lowest_body_value).any():
        raise ValueError(
            "La columna low contiene valores mayores que open, high o close."
        )

    return df.sort_values("date").reset_index(drop=True)
