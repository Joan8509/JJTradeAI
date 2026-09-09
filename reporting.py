"""Reportes portables y auditables de una evaluación JJTrade AI."""

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
import json
from typing import Any


def _strategy_summary(strategies: Any) -> dict[str, int]:
    """Calcula conteos de radar sin quitar la evidencia detallada."""
    strategy_payload = _strategy_payload(strategies)
    evaluations = tuple(strategy_payload.get("evaluations", ()))
    skipped = strategy_payload.get("skipped", {})
    errors = strategy_payload.get("errors", {})

    def _detected(item: Any) -> bool:
        if isinstance(item, dict):
            return item.get("detected") is True
        return bool(getattr(item, "detected", False))

    def _confirmed(item: Any) -> bool:
        if not _detected(item):
            return False
        if isinstance(item, dict):
            criteria = item.get("criteria", ())
            required = [
                criterion
                for criterion in criteria
                if isinstance(criterion, dict) and criterion.get("required")
            ]
            return bool(required) and all(
                getattr(criterion.get("status"), "value", criterion.get("status"))
                == "CUMPLE"
                for criterion in required
            )
        return bool(getattr(item, "required_criteria_satisfied", False))

    return {
        "evaluated": len(evaluations),
        "detected": sum(_detected(item) for item in evaluations),
        "confirmed": sum(_confirmed(item) for item in evaluations),
        "skipped": len(skipped),
        "errors": len(errors),
    }


def _strategy_payload(strategies: Any) -> dict[str, Any]:
    """Normaliza estrategias al contrato auditable del reporte."""
    if isinstance(strategies, dict):
        return {
            "evaluations": strategies.get("evaluations", ()),
            "skipped": strategies.get("skipped", {}),
            "errors": strategies.get("errors", {}),
        }
    return {
        "evaluations": tuple(strategies or ()),
        "skipped": {},
        "errors": {},
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def build_analysis_report(
    *,
    symbol: str,
    data_as_of: str,
    methodology_version: str,
    app_version: str | None = None,
    strategies: Any,
    panorama: Any,
    invalidations: Any,
    levels: Any,
    data_quality: Any,
    risk: Any,
    governance: Any,
    decision: Any,
    data_source: Any | None = None,
) -> dict[str, Any]:
    """Construye un contrato estable que conserva evidencia y fuentes."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("El símbolo del reporte es obligatorio.")
    if not str(data_as_of).strip():
        raise ValueError("data_as_of es obligatorio.")
    if not str(methodology_version).strip():
        raise ValueError("methodology_version es obligatorio.")
    if app_version is not None and not str(app_version).strip():
        raise ValueError("app_version no puede estar vacío cuando se provee.")
    return _jsonable(
        {
            "schema_version": "1.0",
            "symbol": normalized_symbol,
            "data_as_of": data_as_of,
            "app_version": app_version,
            "methodology_version": methodology_version,
            "data_source": data_source,
            "strategy_summary": _strategy_summary(strategies),
            "strategies": _strategy_payload(strategies),
            "panorama": panorama,
            "invalidations": invalidations,
            "moving_average_levels": levels,
            "data_quality": data_quality,
            "risk": risk,
            "governance": governance,
            "decision": decision,
            "disclaimer": (
                "Decisión asistida; no ejecuta órdenes ni garantiza resultados."
            ),
        }
    )


def report_to_json(report: dict[str, Any]) -> str:
    """Serializa el reporte con UTF-8 legible y orden estable."""
    if not isinstance(report, dict):
        raise ValueError("El reporte debe ser un objeto.")
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
