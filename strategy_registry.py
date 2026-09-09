"""Registro central de metadatos para las estrategias de JJTrade AI.

Este módulo no contiene lógica de detección. Su propósito es mantener la
configuración de cada estrategia separada del motor que agrega resultados.
"""

from typing import TypedDict

from strategy_categories import StrategyCategory


class StrategyMetadata(TypedDict):
    """Metadatos obligatorios para cada estrategia registrada."""

    nombre: str
    categoria: StrategyCategory
    sesgo: str
    requiere_confirmacion: bool


STRATEGY_REGISTRY: dict[str, StrategyMetadata] = {
    "EXPUESTO_BOLLINGER_INFERIOR": {
        "nombre": "Expuesto Bollinger Inferior",
        "categoria": StrategyCategory.BOLLINGER,
        "sesgo": "CALL_REBOTE",
        "requiere_confirmacion": True,
    },
    "EXPUESTO_BOLLINGER_SUPERIOR": {
        "nombre": "Expuesto Bollinger Superior",
        "categoria": StrategyCategory.BOLLINGER,
        "sesgo": "PUT_RETROCESO",
        "requiere_confirmacion": True,
    },
    "PRIMER_SALTO_RESPETADO_ALCISTA": {
        "nombre": "Primer Salto Respetado Alcista",
        "categoria": StrategyCategory.PRIMER_SALTO,
        "sesgo": "CALL_CONTINUIDAD_SALTO",
        "requiere_confirmacion": True,
    },
    "PRIMER_SALTO_RESPETADO_BAJISTA": {
        "nombre": "Primer Salto Respetado Bajista",
        "categoria": StrategyCategory.PRIMER_SALTO,
        "sesgo": "PUT_CONTINUIDAD_SALTO",
        "requiere_confirmacion": True,
    },
    "SALTO_LATERALIDAD_HORA_ALCISTA": {
        "nombre": "Salto de Lateralidad en Hora Alcista",
        "categoria": StrategyCategory.PRIMER_SALTO,
        "sesgo": "CALL_CONTINUIDAD_LATERALIDAD",
        "requiere_confirmacion": True,
    },
    "SALTO_LATERALIDAD_HORA_BAJISTA": {
        "nombre": "Salto de Lateralidad en Hora Bajista",
        "categoria": StrategyCategory.PRIMER_SALTO,
        "sesgo": "PUT_CONTINUIDAD_LATERALIDAD",
        "requiere_confirmacion": True,
    },
    "EFECTO_IMAN_TENDENCIA_ALCISTA": {
        "nombre": "Efecto Imán en Tendencia Alcista",
        "categoria": StrategyCategory.PUNTO_MEDIO,
        "sesgo": "PUT_RETROCESO_MA20_HORA",
        "requiere_confirmacion": True,
    },
    "EFECTO_IMAN_TENDENCIA_BAJISTA": {
        "nombre": "Efecto Imán en Tendencia Bajista",
        "categoria": StrategyCategory.PUNTO_MEDIO,
        "sesgo": "CALL_REBOTE_MA20_HORA",
        "requiere_confirmacion": True,
    },
    "CT15_ALCISTA": {
        "nombre": "Cambio de Tendencia en 15 Alcista",
        "categoria": StrategyCategory.CAMBIO_TENDENCIA,
        "sesgo": "CALL_CAMBIO_TENDENCIA",
        "requiere_confirmacion": True,
    },
    "CT15_BAJISTA": {
        "nombre": "Cambio de Tendencia en 15 Bajista",
        "categoria": StrategyCategory.CAMBIO_TENDENCIA,
        "sesgo": "PUT_CAMBIO_TENDENCIA",
        "requiere_confirmacion": True,
    },
    "REBOTE_PUNTO_MEDIO_ALCISTA": {
        "nombre": "Rebote Alcista en Punto Medio Diario",
        "categoria": StrategyCategory.PUNTO_MEDIO,
        "sesgo": "CALL_REBOTE",
        "requiere_confirmacion": True,
    },
    "REBOTE_PUNTO_MEDIO_BAJISTA": {
        "nombre": "Rebote Bajista en Punto Medio Diario",
        "categoria": StrategyCategory.PUNTO_MEDIO,
        "sesgo": "PUT_REBOTE",
        "requiere_confirmacion": True,
    },
    "RETORNO_BOLLINGER_LATERAL_ALCISTA": {
        "nombre": "Retorno Alcista a Bollinger desde Lateralidad",
        "categoria": StrategyCategory.BOLLINGER,
        "sesgo": "CALL_RETORNO_BOLLINGER",
        "requiere_confirmacion": True,
    },
    "RETORNO_BOLLINGER_LATERAL_BAJISTA": {
        "nombre": "Retorno Bajista a Bollinger desde Lateralidad",
        "categoria": StrategyCategory.BOLLINGER,
        "sesgo": "PUT_RETORNO_BOLLINGER",
        "requiere_confirmacion": True,
    },
    "CAMBIO_TENDENCIA_HORA_ALCISTA": {
        "nombre": "Cambio de Tendencia en Hora Alcista",
        "categoria": StrategyCategory.CAMBIO_TENDENCIA,
        "sesgo": "CALL_CAMBIO_TENDENCIA_HORA",
        "requiere_confirmacion": True,
    },
    "CAMBIO_TENDENCIA_HORA_BAJISTA": {
        "nombre": "Cambio de Tendencia en Hora Bajista",
        "categoria": StrategyCategory.CAMBIO_TENDENCIA,
        "sesgo": "PUT_CAMBIO_TENDENCIA_HORA",
        "requiere_confirmacion": True,
    },
    "MOMENTUM_ALCISTA": {
        "nombre": "Momentum Alcista",
        "categoria": StrategyCategory.MOMENTUM,
        "sesgo": "CALL_MOMENTUM",
        "requiere_confirmacion": True,
    },
    "MOMENTUM_BAJISTA": {
        "nombre": "Momentum Bajista",
        "categoria": StrategyCategory.MOMENTUM,
        "sesgo": "PUT_MOMENTUM",
        "requiere_confirmacion": True,
    },
}
