"""Catálogo oficial de revisiones manuales de JJTrade AI.

Las revisiones manuales son condiciones que la metodología exige observar en el
gráfico, calendario o contexto, pero que todavía no deben automatizarse. Este
catálogo evita claves dispersas y errores silenciosos entre la app, el CLI y los
reportes de validación.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManualReviewDefinition:
    """Metadatos de una revisión humana aceptada por el motor."""

    key: str
    label: str
    group: str
    source: str
    required_for_confirmation: bool = True


MANUAL_REVIEW_CATALOG: dict[str, ManualReviewDefinition] = {
    "common.news_clear": ManualReviewDefinition(
        key="common.news_clear",
        label="Calendario sin noticia invalidante",
        group="Común",
        source="docs/strategies/INVALIDACIONES.md",
    ),
    "ct15.prior_trend": ManualReviewDefinition(
        key="ct15.prior_trend",
        label="Tendencia previa válida para CT15",
        group="CT15",
        source="docs/strategies/CT15.md",
    ),
    "ct15.trendline_drawn": ManualReviewDefinition(
        key="ct15.trendline_drawn",
        label="Línea trazada por el lado correcto",
        group="CT15",
        source="docs/strategies/CT15.md",
    ),
    "ct15.trendline_broken": ManualReviewDefinition(
        key="ct15.trendline_broken",
        label="El salto rompió la línea de tendencia",
        group="CT15",
        source="docs/strategies/CT15.md",
    ),
    "jump.path_clear": ManualReviewDefinition(
        key="jump.path_clear",
        label="Camino limpio al siguiente nivel",
        group="Primer Salto",
        source="docs/strategies/PRIMER_SALTO.md",
    ),
    "lateral_jump.path_clear": ManualReviewDefinition(
        key="lateral_jump.path_clear",
        label="Camino limpio al siguiente techo o piso",
        group="Salto Lateralidad Hora",
        source="docs/strategies/SALTO_LATERALIDAD_HORA.md",
    ),
    "return.fast_reversal": ManualReviewDefinition(
        key="return.fast_reversal",
        label="Reversión observada en los primeros minutos",
        group="Retorno Bollinger",
        source="docs/strategies/SALIENDO_BOLLINGER_VOLATILIDAD.md",
    ),
    "momentum.path_clear": ManualReviewDefinition(
        key="momentum.path_clear",
        label="Camino limpio al siguiente nivel",
        group="Momentum",
        source="docs/strategies/MOMENTUM.md",
    ),
    "magnet.worden_volume_cross": ManualReviewDefinition(
        key="magnet.worden_volume_cross",
        label="Volumen de Hora cruzó la línea roja de Worden",
        group="Efecto Imán",
        source="docs/strategies/EFECTO_IMAN.md",
    ),
    "bounce.midpoint_respected": ManualReviewDefinition(
        key="bounce.midpoint_respected",
        label="Override respeto del Punto Medio Diario en 15m",
        group="Rebote Punto Medio",
        source="docs/strategies/REBOTE_PUNTO_MEDIO.md",
    ),
    "bounce.hourly_candle_closed": ManualReviewDefinition(
        key="bounce.hourly_candle_closed",
        label="La vela de Hora evaluada está cerrada",
        group="Rebote Punto Medio",
        source="docs/strategies/REBOTE_PUNTO_MEDIO.md",
    ),
}


def is_known_review_key(key: str) -> bool:
    """Indica si una clave de revisión pertenece al contrato oficial."""
    return key in MANUAL_REVIEW_CATALOG


def format_review_catalog() -> str:
    """Devuelve una tabla Markdown con las revisiones aceptadas."""
    lines = [
        "| Clave | Grupo | Revisión | Fuente |",
        "| --- | --- | --- | --- |",
    ]
    for item in sorted(MANUAL_REVIEW_CATALOG.values(), key=lambda value: value.key):
        lines.append(
            f"| `{item.key}` | {item.group} | {item.label} | `{item.source}` |"
        )
    return "\n".join(lines)
