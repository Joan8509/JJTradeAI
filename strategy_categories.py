"""Categorías oficiales para clasificar las estrategias de JJTrade AI."""

from enum import Enum


class StrategyCategory(str, Enum):
    """Conjunto cerrado de categorías admitidas por el registro."""

    BOLLINGER = "BOLLINGER"
    DISIPADORES = "DISIPADORES"
    PUNTO_MEDIO = "PUNTO_MEDIO"
    VOLATILIDAD = "VOLATILIDAD"
    CAMBIO_TENDENCIA = "CAMBIO_TENDENCIA"
    PRIMER_SALTO = "PRIMER_SALTO"
    PANORAMA = "PANORAMA"
    CONFIRMACION = "CONFIRMACION"
    INVALIDACION = "INVALIDACION"
    RIESGO = "RIESGO"
    MOMENTUM = "MOMENTUM"
