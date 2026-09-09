"""Indicadores técnicos utilizados por el motor de JJTrade AI."""

import pandas as pd


def calculate_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2,
    ddof: int = 0,
) -> pd.DataFrame:
    """Agrega las bandas media, superior e inferior de Bollinger.

    Devuelve una copia del DataFrame para preservar los datos recibidos. Las
    primeras filas permanecen en NaN hasta completar el período indicado.
    """
    if "close" not in df.columns:
        raise ValueError("El DataFrame debe contener la columna 'close'.")
    if period <= 0:
        raise ValueError("El período de Bollinger debe ser mayor que cero.")
    if std_dev < 0:
        raise ValueError("La desviación estándar no puede ser negativa.")
    if ddof < 0 or ddof >= period:
        raise ValueError("ddof debe estar entre cero y period - 1.")

    result = df.copy()
    rolling_close = result["close"].rolling(window=period)
    result["bollinger_mid"] = rolling_close.mean()
    rolling_std = rolling_close.std(ddof=ddof)
    result["bollinger_upper"] = result["bollinger_mid"] + std_dev * rolling_std
    result["bollinger_lower"] = result["bollinger_mid"] - std_dev * rolling_std
    return result


def add_bollinger_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega mediciones objetivas sin clasificar estrategias.

    Las columnas permiten evaluar posteriormente pendiente, ancho y apertura
    simultánea de los disipadores usando umbrales metodológicos configurables.
    """
    required = {"bollinger_mid", "bollinger_upper", "bollinger_lower"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError("Faltan columnas de Bollinger: " + ", ".join(missing))

    result = df.copy()
    result["bollinger_width"] = (
        result["bollinger_upper"] - result["bollinger_lower"]
    )
    safe_mid = result["bollinger_mid"].replace(0, float("nan"))
    result["bollinger_width_pct"] = result["bollinger_width"] / safe_mid * 100
    result["bollinger_mid_slope"] = result["bollinger_mid"].diff()
    result["bollinger_upper_change"] = result["bollinger_upper"].diff()
    result["bollinger_lower_change"] = result["bollinger_lower"].diff()
    result["bollinger_both_expanding"] = (
        (result["bollinger_upper_change"] > 0)
        & (result["bollinger_lower_change"] < 0)
    )
    return result


def add_gap_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Mide saltos entre el cierre previo y la apertura actual."""
    required = {"open", "close"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError("Faltan columnas para calcular saltos: " + ", ".join(missing))

    result = df.copy()
    previous_close = result["close"].shift(1)
    result["previous_close"] = previous_close
    result["gap"] = result["open"] - previous_close
    result["gap_pct"] = result["gap"] / previous_close.replace(0, float("nan")) * 100
    return result
