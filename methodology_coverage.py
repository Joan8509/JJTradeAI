"""Audita trazabilidad entre estrategias, detectores, documentos y fuentes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any, TypedDict

from analysis_pipeline import DETECTOR_REGISTRY, DetectorDefinition
from strategy_registry import STRATEGY_REGISTRY, StrategyMetadata


PROJECT_ROOT = Path(__file__).resolve().parent
ALLOWED_IMPLEMENTATION_STATUSES = {
    "IMPLEMENTADA",
    "IMPLEMENTACION_PARCIAL",
}
SUPPORTED_TIMEFRAMES = {"15m", "1H", "1D"}


class DetectorTraceability(TypedDict):
    documentation: str
    sources: tuple[str, ...]
    implementation_status: str
    expected_timeframes: tuple[str, ...]
    expected_minimum_rows: tuple[tuple[str, int], ...]


DETECTOR_TRACEABILITY: dict[str, DetectorTraceability] = {
    "EXPUESTO_BOLLINGER": {
        "documentation": "docs/INVESTEP_ENGINE.md",
        "sources": ("Bollinguer 1.txt", "Bollinguer2.txt"),
        "implementation_status": "IMPLEMENTADA",
        "expected_timeframes": (),
        "expected_minimum_rows": (),
    },
    "PRIMER_SALTO": {
        "documentation": "docs/strategies/PRIMER_SALTO.md",
        "sources": ("saltos.txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("1H", "1D"),
        "expected_minimum_rows": (("1H", 1), ("1D", 6)),
    },
    "SALTO_LATERALIDAD_HORA": {
        "documentation": "docs/strategies/SALTO_LATERALIDAD_HORA.md",
        "sources": ("clases de soporte(repaso).txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("1H",),
        "expected_minimum_rows": (("1H", 16),),
    },
    "CT15": {
        "documentation": "docs/strategies/CT15.md",
        "sources": ("cambio de tendencia a la baja y a la alza en 15min.txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("15m",),
        "expected_minimum_rows": (("15m", 2),),
    },
    "EFECTO_IMAN": {
        "documentation": "docs/strategies/EFECTO_IMAN.md",
        "sources": ("efecto iman.txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("15m", "1H", "1D"),
        "expected_minimum_rows": (("15m", 1), ("1H", 1), ("1D", 2)),
    },
    "REBOTE_PUNTO_MEDIO": {
        "documentation": "docs/strategies/REBOTE_PUNTO_MEDIO.md",
        "sources": ("Rebote en punto medio a la alza y baja.txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("15m", "1H", "1D"),
        "expected_minimum_rows": (("15m", 1), ("1H", 1), ("1D", 3)),
    },
    "RETORNO_BOLLINGER_LATERAL": {
        "documentation": "docs/strategies/SALIENDO_BOLLINGER_VOLATILIDAD.md",
        "sources": ("Salida de Bollinguer con Volatilidad.txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("15m",),
        "expected_minimum_rows": (("15m", 2),),
    },
    "CAMBIO_TENDENCIA_HORA": {
        "documentation": "docs/strategies/CAMBIO_TENDENCIA_HORA.md",
        "sources": (
            "cambio de tendencia en hora.txt",
            "Cambio Tendencia en hora a la baja.txt",
        ),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("15m", "1H"),
        "expected_minimum_rows": (("15m", 1), ("1H", 14)),
    },
    "MOMENTUM": {
        "documentation": "docs/strategies/MOMENTUM.md",
        "sources": ("momemntum de una empresa.txt",),
        "implementation_status": "IMPLEMENTACION_PARCIAL",
        "expected_timeframes": ("1H", "1D"),
        "expected_minimum_rows": (("1H", 1), ("1D", 1)),
    },
}


def audit_methodology_coverage(
    *,
    project_root: str | Path = PROJECT_ROOT,
    strategy_registry: Mapping[str, StrategyMetadata] = STRATEGY_REGISTRY,
    detectors: Sequence[DetectorDefinition] = DETECTOR_REGISTRY,
    traceability: Mapping[str, DetectorTraceability] = DETECTOR_TRACEABILITY,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    master_path = root / "docs" / "MASTER_STRATEGIES_INDEX.md"
    source_manifest_path = root / "docs" / "SOURCE_MANIFEST.md"
    master = _read_required(master_path)
    source_manifest = _read_required(source_manifest_path)
    issues: list[dict[str, str]] = []
    rows = []
    detector_ids = [item.detector_id for item in detectors]
    if len(detector_ids) != len(set(detector_ids)):
        _issue(issues, "DETECTOR_DUPLICADO", "Existen detector_id duplicados.")
    missing_traceability = sorted(set(detector_ids) - set(traceability))
    extra_traceability = sorted(set(traceability) - set(detector_ids))
    for detector_id in missing_traceability:
        _issue(
            issues,
            "TRAZABILIDAD_FALTANTE",
            f"{detector_id} no tiene ficha de trazabilidad.",
        )
    for detector_id in extra_traceability:
        _issue(
            issues,
            "TRAZABILIDAD_HUERFANA",
            f"{detector_id} no existe en el pipeline.",
        )

    declared_strategy_ids: list[str] = []
    declared_diagnostic_ids: list[str] = []
    for detector in detectors:
        declared_strategy_ids.extend(detector.strategy_ids)
        declared_diagnostic_ids.extend(detector.diagnostic_ids)
        trace = traceability.get(detector.detector_id)
        row_issues: list[str] = []
        if not detector.strategy_ids:
            row_issues.append("No declara strategy_ids.")
        if len(detector.strategy_ids) != len(set(detector.strategy_ids)):
            row_issues.append("Declara strategy_ids duplicados.")
        if not detector.diagnostic_ids:
            row_issues.append("No declara IDs diagnosticos neutrales.")
        if len(detector.diagnostic_ids) != len(set(detector.diagnostic_ids)):
            row_issues.append("Declara diagnostic_ids duplicados.")
        invalid_diagnostics = [
            item
            for item in detector.diagnostic_ids
            if not item.startswith("SIN_") or item in strategy_registry
        ]
        if invalid_diagnostics:
            row_issues.append(
                "IDs diagnosticos invalidos: " + ", ".join(invalid_diagnostics)
            )
        overlap = sorted(set(detector.strategy_ids) & set(detector.diagnostic_ids))
        if overlap:
            row_issues.append(
                "IDs operativos y diagnosticos solapados: " + ", ".join(overlap)
            )
        unknown = sorted(set(detector.strategy_ids) - set(strategy_registry))
        if unknown:
            row_issues.append("IDs no registrados: " + ", ".join(unknown))
        if not callable(detector.evaluate):
            row_issues.append("El evaluador no es invocable.")
        invalid_timeframes = sorted(
            set(detector.required_timeframes) - SUPPORTED_TIMEFRAMES
        )
        if invalid_timeframes:
            row_issues.append(
                "Temporalidades no admitidas: " + ", ".join(invalid_timeframes)
            )
        minimum_timeframes = [item[0] for item in detector.minimum_rows]
        if len(minimum_timeframes) != len(set(minimum_timeframes)):
            row_issues.append("Declara minimos duplicados por temporalidad.")
        invalid_minimums = [
            f"{timeframe}={minimum}"
            for timeframe, minimum in detector.minimum_rows
            if timeframe not in detector.required_timeframes or minimum <= 0
        ]
        if invalid_minimums:
            row_issues.append(
                "Minimos de historial invalidos: " + ", ".join(invalid_minimums)
            )
        document = ""
        sources: tuple[str, ...] = ()
        implementation_status = "SIN_TRAZABILIDAD"
        if trace is not None:
            document = trace["documentation"]
            sources = trace["sources"]
            implementation_status = trace["implementation_status"]
            if tuple(detector.required_timeframes) != tuple(
                trace["expected_timeframes"]
            ):
                row_issues.append("Temporalidades distintas a la ficha.")
            if tuple(detector.minimum_rows) != tuple(
                trace["expected_minimum_rows"]
            ):
                row_issues.append("Minimos de historial distintos a la ficha.")
            document_path = (root / document).resolve()
            if root not in document_path.parents or not document_path.is_file():
                row_issues.append("Documento inexistente o fuera del proyecto.")
            else:
                try:
                    master_reference = Path(document).relative_to("docs").as_posix()
                except ValueError:
                    row_issues.append("Documento fuera del directorio docs.")
                else:
                    if master_reference not in master:
                        row_issues.append("Documento ausente del indice maestro.")
            if not sources:
                row_issues.append("No declara fuentes Investep.")
            for source in sources:
                if f"`{source}`" not in source_manifest:
                    row_issues.append(f"Fuente no incluida en manifiesto: {source}")
            if implementation_status not in ALLOWED_IMPLEMENTATION_STATUSES:
                row_issues.append("Estado de implementacion no admitido.")
            if implementation_status == "IMPLEMENTACION_PARCIAL":
                unguarded = [
                    strategy_id
                    for strategy_id in detector.strategy_ids
                    if strategy_id in strategy_registry
                    and not strategy_registry[strategy_id]["requiere_confirmacion"]
                ]
                if unguarded:
                    row_issues.append(
                        "Estrategias parciales sin confirmacion: "
                        + ", ".join(unguarded)
                    )
        for detail in row_issues:
            _issue(
                issues,
                "DETECTOR_NO_CUBIERTO",
                f"{detector.detector_id}: {detail}",
            )
        rows.append(
            {
                "detector_id": detector.detector_id,
                "strategy_ids": list(detector.strategy_ids),
                "diagnostic_ids": list(detector.diagnostic_ids),
                "required_timeframes": list(detector.required_timeframes),
                "minimum_rows": {
                    timeframe: minimum
                    for timeframe, minimum in detector.minimum_rows
                },
                "documentation": document,
                "sources": list(sources),
                "implementation_status": implementation_status,
                "status": "OK" if not row_issues else "ERROR",
                "issues": row_issues,
            }
        )

    duplicates = sorted(
        {
            strategy_id
            for strategy_id in declared_strategy_ids
            if declared_strategy_ids.count(strategy_id) > 1
        }
    )
    for strategy_id in duplicates:
        _issue(
            issues,
            "ESTRATEGIA_DUPLICADA",
            f"{strategy_id} pertenece a mas de un detector.",
        )
    duplicate_diagnostics = sorted(
        {
            diagnostic_id
            for diagnostic_id in declared_diagnostic_ids
            if declared_diagnostic_ids.count(diagnostic_id) > 1
        }
    )
    for diagnostic_id in duplicate_diagnostics:
        _issue(
            issues,
            "DIAGNOSTICO_DUPLICADO",
            f"{diagnostic_id} pertenece a mas de un detector.",
        )
    orphan_registry = sorted(set(strategy_registry) - set(declared_strategy_ids))
    for strategy_id in orphan_registry:
        _issue(
            issues,
            "ESTRATEGIA_HUERFANA",
            f"{strategy_id} no pertenece a ningun detector.",
        )
    return {
        "status": "OK" if not issues else "BLOQUEADO",
        "strategy_count": len(strategy_registry),
        "declared_strategy_count": len(set(declared_strategy_ids)),
        "diagnostic_id_count": len(set(declared_diagnostic_ids)),
        "detector_count": len(detectors),
        "fully_implemented_detector_count": sum(
            row["implementation_status"] == "IMPLEMENTADA" for row in rows
        ),
        "partial_detector_count": sum(
            row["implementation_status"] == "IMPLEMENTACION_PARCIAL"
            for row in rows
        ),
        "issue_count": len(issues),
        "issues": issues,
        "detectors": rows,
        "methodology_complete": all(
            row["implementation_status"] == "IMPLEMENTADA" for row in rows
        )
        and not issues,
        "real_trading_authorized": False,
        "authority": "COBERTURA_METODOLOGICA_NO_AUTORIZA_OPERACIONES",
    }


def _read_required(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"No se pudo leer el documento requerido: {path}") from error


def _issue(issues: list[dict[str, str]], code: str, detail: str) -> None:
    issues.append({"code": code, "detail": detail})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Ruta opcional para el JSON.")
    args = parser.parse_args(argv)
    try:
        payload = audit_methodology_coverage()
    except ValueError as error:
        print(f"Cobertura metodologica BLOQUEADA: {error}")
        return 1
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
