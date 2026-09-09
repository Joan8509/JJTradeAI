"""Validación por lote de paquetes TC2000 para JJTrade AI.

Este módulo agrupa archivos por símbolo/sesión, ejecuta el validador
reproducible y genera un resumen operativo. Es una herramienta de control de
calidad para probar muchos casos PAPER sin convertirlos en señales automáticas.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from analysis_models import DirectionBias, GateStatus
from data_providers import DataBundle, load_tc2000_file_data_bundle
from report_auditor import (
    audit_report,
    audit_report_directory,
    write_audit_csv,
    write_review_queue_csv,
)
from reporting import report_to_json
from validation_runner import run_validation_bundle_assessment
from version import APP_VERSION, METHODOLOGY_VERSION


PACKAGE_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Za-z0-9.\-]+)_(?P<session>\d{4}-\d{2}-\d{2})_"
    r"(?P<timeframe>15m|1H|1D)\.(?P<extension>txt|csv)$",
    re.IGNORECASE,
)

TIMEFRAME_TO_ARG = {
    "15m": "timeframe_15m",
    "1h": "timeframe_1h",
    "1d": "timeframe_1d",
}

SUMMARY_FIELDS = (
    "package_id",
    "symbol",
    "session",
    "timeframes",
    "candle_counts",
    "data_as_of",
    "data_quality",
    "decision_data_quality",
    "panorama",
    "decision_panorama",
    "risk",
    "governance",
    "decision",
    "tentative_bias",
    "tentative_strategies",
    "readiness",
    "learning_ready",
    "missing_gate_count",
    "missing_strategy_count",
    "missing_invalidation_count",
    "blocker_gate_count",
    "blocker_invalidation_count",
    "blocker_detector_count",
    "evaluated_count",
    "detected_count",
    "confirmed_count",
    "skipped_count",
    "error_count",
    "detected_strategies",
    "skipped_detectors",
    "errors",
    "report_path",
)

INTAKE_TEMPLATE_FIELDS = (
    "symbol",
    "session",
    "timeframe_15m_file",
    "timeframe_1h_file",
    "timeframe_1d_file",
    "tc2000_export_checked",
    "chart_screenshot_or_note",
    "primary_setup_to_review",
    "manual_reviews_pending",
    "risk_review_status",
    "governance_review_status",
    "paper_trade_taken",
    "paper_trade_result",
    "operator_notes",
)

INTAKE_CHECK_FIELDS = (
    "symbol",
    "session",
    "status",
    "missing_files",
    "available_files",
)

PACKAGE_INVENTORY_FIELDS = (
    "package_id",
    "symbol",
    "session",
    "status",
    "available_timeframes",
    "missing_timeframes",
    "files",
)

OPERATOR_BOARD_FIELDS = (
    "package_id",
    "symbol",
    "session",
    "decision",
    "readiness",
    "learning_ready",
    "tentative_bias",
    "detected_count",
    "confirmed_count",
    "missing_total",
    "blocker_total",
    "first_missing_evidence",
    "first_blocker",
    "data_quality",
    "panorama",
    "risk",
    "governance",
    "timeframes",
    "report_path",
)

OUTPUT_INSPECTION_FIELDS = (
    "check",
    "status",
    "row_count",
    "details",
)

REQUIRED_TIMEFRAMES = ("15m", "1H", "1D")


@dataclass(frozen=True)
class ValidationPackage:
    """Conjunto de archivos TC2000 de un símbolo y una sesión."""

    symbol: str
    session: str
    files: dict[str, Path]

    @property
    def package_id(self) -> str:
        """Identificador estable para reportes."""
        return f"{self.symbol}_{self.session}"


def discover_validation_packages(input_dir: str | Path) -> tuple[ValidationPackage, ...]:
    """Descubre paquetes con nombres `SIMBOLO_FECHA_15m|1H|1D.txt|csv`."""
    root = Path(input_dir)
    if not root.is_dir():
        raise ValueError(f"La carpeta de entrada no existe: {root}")
    grouped: dict[tuple[str, str], dict[str, Path]] = {}
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        match = PACKAGE_FILENAME_RE.match(path.name)
        if not match:
            continue
        symbol = match.group("symbol").upper()
        session = match.group("session")
        timeframe = match.group("timeframe")
        normalized_timeframe = {
            "15M": "15m",
            "1H": "1H",
            "1D": "1D",
        }[timeframe.upper()]
        grouped.setdefault((symbol, session), {})[normalized_timeframe] = path

    return tuple(
        ValidationPackage(symbol=symbol, session=session, files=files)
        for (symbol, session), files in sorted(grouped.items())
    )


def _load_package_bundle(package: ValidationPackage) -> DataBundle:
    """Carga las temporalidades disponibles de un paquete descubierto."""
    kwargs = {
        TIMEFRAME_TO_ARG[timeframe.lower()]: path
        for timeframe, path in package.files.items()
    }
    return load_tc2000_file_data_bundle(**kwargs)


def _package_metadata(package: ValidationPackage) -> dict[str, Any]:
    """Describe el paquete fuente para trazar reportes y auditorias batch."""
    return {
        "package_id": package.package_id,
        "symbol": package.symbol,
        "session": package.session,
        "timeframes": sorted(package.files),
        "files": {
            timeframe: str(path)
            for timeframe, path in sorted(package.files.items())
        },
    }


def _join_text_values(value: Any) -> str:
    """Normaliza campos que pueden venir como texto o lista."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "|".join(str(item) for item in value if item)
    return str(value)


def _package_inventory_row(package: ValidationPackage) -> dict[str, str]:
    """Resume si un paquete tiene todas las temporalidades requeridas."""
    missing_timeframes = [
        timeframe for timeframe in REQUIRED_TIMEFRAMES if timeframe not in package.files
    ]
    return {
        "package_id": package.package_id,
        "symbol": package.symbol,
        "session": package.session,
        "status": "LISTO" if not missing_timeframes else "INCOMPLETO",
        "available_timeframes": "|".join(
            timeframe for timeframe in REQUIRED_TIMEFRAMES if timeframe in package.files
        ),
        "missing_timeframes": "|".join(missing_timeframes),
        "files": "|".join(
            f"{timeframe}:{package.files[timeframe].name}"
            for timeframe in REQUIRED_TIMEFRAMES
            if timeframe in package.files
        ),
    }


def write_package_inventory(
    *,
    input_dir: str | Path,
    output_csv: str | Path,
) -> tuple[dict[str, str], ...]:
    """Escribe un inventario de paquetes descubiertos antes del batch."""
    packages = discover_validation_packages(input_dir)
    rows = [_package_inventory_row(package) for package in packages]
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PACKAGE_INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return tuple(rows)


def _incomplete_package_messages(packages: tuple[ValidationPackage, ...]) -> list[str]:
    """Describe paquetes que no tienen las tres temporalidades requeridas."""
    messages: list[str] = []
    for package in packages:
        missing = [
            timeframe for timeframe in REQUIRED_TIMEFRAMES if timeframe not in package.files
        ]
        if missing:
            messages.append(f"{package.package_id}: faltan {', '.join(missing)}")
    return messages


def run_input_preflight(
    *,
    input_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Genera inventario, intake y verificacion de intake para una carpeta."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    inventory_path = output_root / "package_inventory.csv"
    intake_path = output_root / "case_intake.csv"
    intake_check_path = output_root / "case_intake_check.csv"

    inventory_rows = write_package_inventory(
        input_dir=input_dir,
        output_csv=inventory_path,
    )
    write_case_intake_from_input(input_dir=input_dir, output_csv=intake_path)
    intake_rows = check_case_intake(
        intake_csv=intake_path,
        input_dir=input_dir,
        output_csv=intake_check_path,
    )
    inventory_incomplete = sum(
        1 for row in inventory_rows if row["status"] != "LISTO"
    )
    intake_incomplete = sum(1 for row in intake_rows if row["status"] != "LISTO")
    return {
        "package_count": len(inventory_rows),
        "inventory_incomplete": inventory_incomplete,
        "intake_incomplete": intake_incomplete,
        "inventory_path": str(inventory_path),
        "intake_path": str(intake_path),
        "intake_check_path": str(intake_check_path),
    }


def _summarize_report(
    package: ValidationPackage,
    report: dict[str, Any],
    report_path: Path,
) -> dict[str, str]:
    """Extrae una fila compacta para revisar muchas validaciones."""
    evaluations = report["strategies"]["evaluations"]
    detected = [
        item["strategy_id"]
        for item in evaluations
        if item.get("detected") is True
    ]
    strategy_summary = report.get("strategy_summary", {})
    auditable_report = dict(report)
    if not isinstance(auditable_report.get("symbol"), str) or not auditable_report[
        "symbol"
    ].strip():
        auditable_report["symbol"] = package.symbol
    if not isinstance(auditable_report.get("data_as_of"), str) or not auditable_report[
        "data_as_of"
    ].strip():
        auditable_report["data_as_of"] = package.session
    audit = audit_report(auditable_report, report_path=str(report_path))

    def _summary_count(key: str, fallback: int = 0) -> str:
        try:
            return str(int(strategy_summary.get(key, fallback)))
        except (AttributeError, TypeError, ValueError):
            return str(fallback)

    return {
        "package_id": package.package_id,
        "symbol": package.symbol,
        "session": package.session,
        "timeframes": ",".join(sorted(package.files)),
        "candle_counts": "|".join(
            f"{timeframe}:{count}"
            for timeframe, count in sorted(
                report.get("data_quality", {}).get("candle_counts", {}).items()
            )
        ),
        "data_as_of": str(report["data_as_of"]),
        "data_quality": report["data_quality"]["status"],
        "decision_data_quality": report["decision"].get(
            "data_quality_status", report["data_quality"]["status"]
        ),
        "panorama": report["panorama"]["status"],
        "decision_panorama": report["decision"].get(
            "panorama_status", report["panorama"]["status"]
        ),
        "risk": report["decision"].get(
            "risk_status", report.get("risk", {}).get("status", "NO_DISPONIBLE")
        ),
        "governance": report["decision"].get(
            "governance_status",
            report.get("governance", {}).get("status", "NO_DISPONIBLE"),
        ),
        "decision": report["decision"]["decision"],
        "tentative_bias": str(report["decision"].get("tentative_bias") or ""),
        "tentative_strategies": _join_text_values(
            report["decision"].get("tentative_strategies", [])
        ),
        "readiness": audit.readiness,
        "learning_ready": "SI" if audit.learning_ready else "NO",
        "missing_gate_count": str(audit.missing_gate_count),
        "missing_strategy_count": str(audit.missing_strategy_count),
        "missing_invalidation_count": str(audit.missing_invalidation_count),
        "blocker_gate_count": str(audit.blocker_gate_count),
        "blocker_invalidation_count": str(audit.blocker_invalidation_count),
        "blocker_detector_count": str(audit.blocker_detector_count),
        "evaluated_count": _summary_count("evaluated", len(evaluations)),
        "detected_count": _summary_count("detected", len(detected)),
        "confirmed_count": _summary_count("confirmed"),
        "skipped_count": _summary_count(
            "skipped", len(report["strategies"]["skipped"])
        ),
        "error_count": _summary_count(
            "errors", len(report["strategies"]["errors"])
        ),
        "detected_strategies": "|".join(detected),
        "skipped_detectors": "|".join(sorted(report["strategies"]["skipped"])),
        "errors": "|".join(sorted(report["strategies"]["errors"])),
        "report_path": str(report_path),
    }


def _build_error_report(
    package: ValidationPackage,
    error: Exception,
) -> dict[str, Any]:
    """Conserva fallos de carga/evaluación como reporte auditable."""
    error_message = str(error)
    return {
        "schema_version": "1.0",
        "symbol": package.symbol,
        "data_as_of": package.session,
        "app_version": APP_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "validation_package": _package_metadata(package),
        "strategy_summary": {
            "evaluated": 0,
            "detected": 0,
            "confirmed": 0,
            "skipped": 0,
            "errors": 1,
        },
        "strategies": {
            "evaluations": [],
            "skipped": {},
            "errors": {"package": error_message},
        },
        "panorama": {"status": "ERROR"},
        "invalidations": [],
        "moving_average_levels": [],
        "data_quality": {"status": "ERROR", "candle_counts": {}},
        "risk": {"status": "ERROR"},
        "governance": {"status": "ERROR"},
        "decision": {
            "decision": "NO_OPERAR",
            "data_quality_status": "ERROR",
            "panorama_status": "ERROR",
            "risk_status": "ERROR",
            "governance_status": "ERROR",
            "tentative_bias": "",
            "tentative_strategies": [],
        },
        "disclaimer": "Error de validación por lote; no emite señales.",
    }


def _parse_gate_status(value: str) -> GateStatus:
    normalized = value.strip().upper()
    try:
        return GateStatus(normalized)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in GateStatus)
        raise argparse.ArgumentTypeError(
            f"Estado de compuerta no reconocido: {value}. Use {allowed}."
        ) from exc


def _parse_option_type(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in {DirectionBias.CALL.value, DirectionBias.PUT.value}:
        raise argparse.ArgumentTypeError("Tipo de opción no reconocido. Use CALL o PUT.")
    return normalized


def write_case_intake_template(output_csv: str | Path) -> Path:
    """Escribe una plantilla CSV para registrar evidencia humana por caso."""
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "symbol": "SPY",
                "session": "2026-06-24",
                "timeframe_15m_file": "SPY_2026-06-24_15m.txt",
                "timeframe_1h_file": "SPY_2026-06-24_1H.txt",
                "timeframe_1d_file": "SPY_2026-06-24_1D.txt",
                "tc2000_export_checked": "PENDIENTE",
                "chart_screenshot_or_note": "",
                "primary_setup_to_review": "",
                "manual_reviews_pending": "",
                "risk_review_status": "NO_DISPONIBLE",
                "governance_review_status": "NO_DISPONIBLE",
                "paper_trade_taken": "NO",
                "paper_trade_result": "",
                "operator_notes": "",
            }
        )
    return output_path


def write_case_intake_from_input(
    *,
    input_dir: str | Path,
    output_csv: str | Path,
) -> Path:
    """Crea una hoja de intake con los paquetes descubiertos en la carpeta."""
    packages = discover_validation_packages(input_dir)
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INTAKE_TEMPLATE_FIELDS)
        writer.writeheader()
        for package in packages:
            writer.writerow(
                {
                    "symbol": package.symbol,
                    "session": package.session,
                    "timeframe_15m_file": package.files.get("15m", Path()).name,
                    "timeframe_1h_file": package.files.get("1H", Path()).name,
                    "timeframe_1d_file": package.files.get("1D", Path()).name,
                    "tc2000_export_checked": "PENDIENTE",
                    "chart_screenshot_or_note": "",
                    "primary_setup_to_review": "",
                    "manual_reviews_pending": "",
                    "risk_review_status": "NO_DISPONIBLE",
                    "governance_review_status": "NO_DISPONIBLE",
                    "paper_trade_taken": "NO",
                    "paper_trade_result": "",
                    "operator_notes": "",
                }
            )
    return output_path


def check_case_intake(
    *,
    intake_csv: str | Path,
    input_dir: str | Path,
    output_csv: str | Path | None = None,
) -> tuple[dict[str, str], ...]:
    """Valida que los archivos declarados en la plantilla existan."""
    intake_path = Path(intake_csv)
    root = Path(input_dir)
    if not intake_path.is_file():
        raise ValueError(f"La plantilla de intake no existe: {intake_path}")
    if not root.is_dir():
        raise ValueError(f"La carpeta de entrada no existe: {root}")

    rows: list[dict[str, str]] = []
    with intake_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "symbol",
            "session",
            "timeframe_15m_file",
            "timeframe_1h_file",
            "timeframe_1d_file",
        }
        missing_columns = required.difference(reader.fieldnames or ())
        if missing_columns:
            raise ValueError(
                "La plantilla de intake no contiene columnas obligatorias: "
                + ", ".join(sorted(missing_columns))
            )
        for raw_row in reader:
            expected_by_column = {
                "timeframe_15m_file": raw_row.get("timeframe_15m_file", "").strip(),
                "timeframe_1h_file": raw_row.get("timeframe_1h_file", "").strip(),
                "timeframe_1d_file": raw_row.get("timeframe_1d_file", "").strip(),
            }
            missing_files = []
            available_files = []
            for column, filename in expected_by_column.items():
                if not filename:
                    missing_files.append(f"{column}:NO_DECLARADO")
                elif not (root / filename).is_file():
                    missing_files.append(filename)
                else:
                    available_files.append(filename)
            rows.append(
                {
                    "symbol": raw_row.get("symbol", "").strip().upper(),
                    "session": raw_row.get("session", "").strip(),
                    "status": "LISTO" if not missing_files else "INCOMPLETO",
                    "missing_files": "|".join(missing_files),
                    "available_files": "|".join(available_files),
                }
            )

    if output_csv is not None:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=INTAKE_CHECK_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    return tuple(rows)


def run_batch_validation(
    *,
    input_dir: str | Path,
    output_dir: str | Path,
    risk_status: GateStatus = GateStatus.NO_DISPONIBLE,
    risk_option_type: str | None = None,
    governance_status: GateStatus = GateStatus.NO_DISPONIBLE,
    audit_output_csv: str | Path | None = None,
    review_output_csv: str | Path | None = None,
    operator_board_output_csv: str | Path | None = None,
    require_complete_packages: bool = False,
) -> tuple[dict[str, str], ...]:
    """Ejecuta validación conservadora para todos los paquetes encontrados."""
    packages = discover_validation_packages(input_dir)
    if require_complete_packages:
        incomplete = _incomplete_package_messages(packages)
        if incomplete:
            raise ValueError(
                "Hay paquetes incompletos. Ejecute preflight o complete archivos: "
                + " | ".join(incomplete)
            )
    output_root = Path(output_dir)
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for package in packages:
        report_path = reports_dir / f"{package.package_id}.json"
        try:
            bundle = _load_package_bundle(package)
            _, report = run_validation_bundle_assessment(
                symbol=package.symbol,
                bundle=bundle,
                risk_status=risk_status,
                risk_option_type=risk_option_type,
                governance_status=governance_status,
            )
            report["validation_package"] = _package_metadata(package)
            report_path.write_text(report_to_json(report), encoding="utf-8")
            rows.append(_summarize_report(package, report, report_path))
        except Exception as error:  # pragma: no cover - exercised through output
            error_report = _build_error_report(package, error)
            report_path.write_text(report_to_json(error_report), encoding="utf-8")
            rows.append(
                {
                    "package_id": package.package_id,
                    "symbol": package.symbol,
                    "session": package.session,
                    "timeframes": ",".join(sorted(package.files)),
                    "candle_counts": "",
                    "data_as_of": "",
                    "data_quality": "ERROR",
                    "decision_data_quality": "ERROR",
                    "panorama": "ERROR",
                    "decision_panorama": "ERROR",
                    "risk": "ERROR",
                    "governance": "ERROR",
                    "decision": "NO_OPERAR",
                    "tentative_bias": "",
                    "tentative_strategies": "",
                    "readiness": "BLOQUEADO",
                    "learning_ready": "NO",
                    "missing_gate_count": "0",
                    "missing_strategy_count": "0",
                    "missing_invalidation_count": "0",
                    "blocker_gate_count": "0",
                    "blocker_invalidation_count": "0",
                    "blocker_detector_count": "1",
                    "evaluated_count": "0",
                    "detected_count": "0",
                    "confirmed_count": "0",
                    "skipped_count": "0",
                    "error_count": "1",
                    "detected_strategies": "",
                    "skipped_detectors": "",
                    "errors": str(error),
                    "report_path": str(report_path),
                }
            )

    summary_path = output_root / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    if (
        audit_output_csv is not None
        or review_output_csv is not None
        or operator_board_output_csv is not None
    ):
        audits = audit_report_directory(reports_dir)
        if audit_output_csv is not None:
            write_audit_csv(audits, audit_output_csv)
        if review_output_csv is not None:
            write_review_queue_csv(audits, review_output_csv)
        if operator_board_output_csv is not None:
            write_operator_board_csv(rows, audits, operator_board_output_csv)
    return tuple(rows)


def _as_int(value: str) -> int:
    """Convierte conteos CSV a entero sin romper reportes heredados."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_operator_board_rows(
    summary_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    audits: tuple[Any, ...],
) -> tuple[dict[str, str], ...]:
    """Combina resumen y auditoria en una fila operativa por paquete."""
    audits_by_package = {audit.package_id: audit for audit in audits if audit.package_id}
    rows: list[dict[str, str]] = []
    for summary in summary_rows:
        package_id = summary.get("package_id", "")
        audit = audits_by_package.get(package_id)
        missing_total = (
            _as_int(summary.get("missing_gate_count", "0"))
            + _as_int(summary.get("missing_strategy_count", "0"))
            + _as_int(summary.get("missing_invalidation_count", "0"))
        )
        blocker_total = (
            _as_int(summary.get("blocker_gate_count", "0"))
            + _as_int(summary.get("blocker_invalidation_count", "0"))
            + _as_int(summary.get("blocker_detector_count", "0"))
        )
        rows.append(
            {
                "package_id": package_id,
                "symbol": summary.get("symbol", ""),
                "session": summary.get("session", ""),
                "decision": summary.get("decision", ""),
                "readiness": summary.get("readiness", ""),
                "learning_ready": summary.get("learning_ready", ""),
                "tentative_bias": summary.get("tentative_bias", ""),
                "detected_count": summary.get("detected_count", "0"),
                "confirmed_count": summary.get("confirmed_count", "0"),
                "missing_total": str(missing_total),
                "blocker_total": str(blocker_total),
                "first_missing_evidence": (
                    audit.first_missing_evidence if audit is not None else ""
                ),
                "first_blocker": audit.first_blocker if audit is not None else "",
                "data_quality": summary.get("decision_data_quality", ""),
                "panorama": summary.get("decision_panorama", ""),
                "risk": summary.get("risk", ""),
                "governance": summary.get("governance", ""),
                "timeframes": summary.get("timeframes", ""),
                "report_path": summary.get("report_path", ""),
            }
        )
    return tuple(rows)


def write_operator_board_csv(
    summary_rows: list[dict[str, str]] | tuple[dict[str, str], ...],
    audits: tuple[Any, ...],
    output_csv: str | Path,
) -> None:
    """Escribe un tablero por paquete para priorizar revision humana."""
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = build_operator_board_rows(summary_rows, audits)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OPERATOR_BOARD_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    """Lee filas CSV como diccionarios UTF-8."""
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(csv.DictReader(handle))


def _package_ids(rows: tuple[dict[str, str], ...]) -> set[str]:
    """Extrae package_id ignorando filas sin identificador."""
    return {row.get("package_id", "") for row in rows if row.get("package_id", "")}


def inspect_validation_output(
    *,
    output_dir: str | Path,
    output_csv: str | Path | None = None,
) -> tuple[dict[str, str], ...]:
    """Inspecciona artefactos batch generados para detectar faltantes obvios."""
    root = Path(output_dir)
    expected_files = {
        "summary": root / "summary.csv",
        "audit": root / "audit.csv",
        "review_queue": root / "review_queue.csv",
        "operator_board": root / "operator_board.csv",
    }
    rows: list[dict[str, str]] = []
    loaded: dict[str, tuple[dict[str, str], ...]] = {}

    for name, path in expected_files.items():
        if not path.is_file():
            rows.append(
                {
                    "check": name,
                    "status": "FALTA",
                    "row_count": "0",
                    "details": str(path),
                }
            )
            continue
        csv_rows = _read_csv_rows(path)
        loaded[name] = csv_rows
        rows.append(
            {
                "check": name,
                "status": "LISTO",
                "row_count": str(len(csv_rows)),
                "details": str(path),
            }
        )

    reports_dir = root / "reports"
    report_count = len(tuple(reports_dir.glob("*.json"))) if reports_dir.is_dir() else 0
    rows.append(
        {
            "check": "reports",
            "status": "LISTO" if report_count else "FALTA",
            "row_count": str(report_count),
            "details": str(reports_dir),
        }
    )

    reference_ids = _package_ids(loaded.get("summary", ()))
    for name in ("audit", "operator_board"):
        if name not in loaded or not reference_ids:
            continue
        ids = _package_ids(loaded[name])
        missing = sorted(reference_ids - ids)
        extra = sorted(ids - reference_ids)
        rows.append(
            {
                "check": f"package_ids_{name}",
                "status": "LISTO" if not missing and not extra else "INCOMPLETO",
                "row_count": str(len(ids)),
                "details": (
                    f"faltan={','.join(missing)} extra={','.join(extra)}"
                    if missing or extra
                    else "package_id alineados"
                ),
            }
        )

    if "review_queue" in loaded and reference_ids:
        queue_ids = _package_ids(loaded["review_queue"])
        missing_from_queue = sorted(
            package_id for package_id in reference_ids if package_id not in queue_ids
        )
        rows.append(
            {
                "check": "package_ids_review_queue",
                "status": "LISTO" if not missing_from_queue else "REVISION",
                "row_count": str(len(queue_ids)),
                "details": (
                    "sin filas para paquetes="
                    + ",".join(missing_from_queue)
                    if missing_from_queue
                    else "package_id presentes en cola"
                ),
            }
        )

    if output_csv is not None:
        output_path = Path(output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_INSPECTION_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    return tuple(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    """Construye el parser CLI del validador por lote."""
    parser = argparse.ArgumentParser(
        description="Valida por lote paquetes TC2000 de JJTrade AI."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"JJTrade AI {APP_VERSION} / {METHODOLOGY_VERSION}",
    )
    parser.add_argument(
        "--input-dir",
        help="Carpeta con archivos SIMBOLO_FECHA_15m|1H|1D.txt|csv.",
    )
    parser.add_argument(
        "--output-dir",
        help="Carpeta donde guardar reportes y summary.csv.",
    )
    parser.add_argument(
        "--risk-status",
        type=_parse_gate_status,
        default=GateStatus.NO_DISPONIBLE,
        help=(
            "Estado de riesgo a aplicar a todos los paquetes: APROBADO, "
            "RECHAZADO, NO_DISPONIBLE o REQUIERE_REVISION."
        ),
    )
    parser.add_argument(
        "--risk-option-type",
        type=_parse_option_type,
        help="Tipo de contrato revisado para riesgo aprobado: CALL o PUT.",
    )
    parser.add_argument(
        "--governance-status",
        type=_parse_gate_status,
        default=GateStatus.NO_DISPONIBLE,
        help=(
            "Estado de gobierno operativo a aplicar a todos los paquetes: "
            "APROBADO, RECHAZADO, NO_DISPONIBLE o REQUIERE_REVISION."
        ),
    )
    parser.add_argument(
        "--audit-output-csv",
        help="Ruta CSV opcional para auditar los reportes generados en la misma corrida.",
    )
    parser.add_argument(
        "--review-output-csv",
        help="Ruta CSV opcional para guardar la cola de revision del lote.",
    )
    parser.add_argument(
        "--operator-board-output-csv",
        help="Ruta CSV opcional para guardar tablero operativo por paquete.",
    )
    parser.add_argument(
        "--standard-output-dir",
        action="store_true",
        help=(
            "Escribe audit.csv, review_queue.csv y operator_board.csv dentro "
            "de --output-dir."
        ),
    )
    parser.add_argument(
        "--require-complete-packages",
        action="store_true",
        help="Rechaza el lote si algun paquete no tiene 15m, 1H y 1D.",
    )
    parser.add_argument(
        "--write-intake-template",
        help="Escribe una plantilla CSV para registrar evidencia humana por caso y termina.",
    )
    parser.add_argument(
        "--write-intake-from-input",
        help="Escribe una hoja de intake con los paquetes descubiertos en --input-dir y termina.",
    )
    parser.add_argument(
        "--write-package-inventory",
        help="Escribe un CSV de paquetes descubiertos, temporalidades presentes y faltantes.",
    )
    parser.add_argument(
        "--preflight-output-dir",
        help=(
            "Genera package_inventory.csv, case_intake.csv y "
            "case_intake_check.csv para --input-dir y termina."
        ),
    )
    parser.add_argument(
        "--run-after-preflight",
        action="store_true",
        help=(
            "Con --preflight-output-dir, continua con el batch estricto solo "
            "si el preflight no detecta incompletos."
        ),
    )
    parser.add_argument(
        "--check-intake-csv",
        help="Valida que los archivos declarados en una plantilla de intake existan.",
    )
    parser.add_argument(
        "--intake-check-output-csv",
        help="Ruta CSV opcional para guardar el resultado de --check-intake-csv.",
    )
    parser.add_argument(
        "--inspect-output-dir",
        help="Inspecciona artefactos generados en una carpeta de salida batch y termina.",
    )
    parser.add_argument(
        "--inspection-output-csv",
        help="Ruta CSV opcional para guardar el resultado de --inspect-output-dir.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI del validador por lote."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.standard_output_dir:
        if not args.output_dir:
            parser.error("--output-dir es obligatorio con --standard-output-dir.")
        output_root = Path(args.output_dir)
        if not args.audit_output_csv:
            args.audit_output_csv = str(output_root / "audit.csv")
        if not args.review_output_csv:
            args.review_output_csv = str(output_root / "review_queue.csv")
        if not args.operator_board_output_csv:
            args.operator_board_output_csv = str(output_root / "operator_board.csv")
    if args.write_intake_template:
        output_path = write_case_intake_template(args.write_intake_template)
        print(f"Plantilla de intake escrita: {output_path}")
        return 0
    if args.inspect_output_dir:
        rows = inspect_validation_output(
            output_dir=args.inspect_output_dir,
            output_csv=args.inspection_output_csv,
        )
        incomplete = sum(1 for row in rows if row["status"] not in {"LISTO", "REVISION"})
        print(f"Inspecciones: {len(rows)} incompletas: {incomplete}")
        return 1 if incomplete else 0
    if args.preflight_output_dir:
        if not args.input_dir:
            parser.error("--input-dir es obligatorio con --preflight-output-dir.")
        result = run_input_preflight(
            input_dir=args.input_dir,
            output_dir=args.preflight_output_dir,
        )
        incomplete = int(result["inventory_incomplete"]) + int(
            result["intake_incomplete"]
        )
        print(
            "Preflight generado: "
            f"paquetes={result['package_count']} "
            f"inventario_incompleto={result['inventory_incomplete']} "
            f"intake_incompleto={result['intake_incomplete']}"
        )
        if incomplete:
            return 1
        if not args.run_after_preflight:
            return 0
        if not args.output_dir:
            parser.error("--output-dir es obligatorio con --run-after-preflight.")
        if args.risk_option_type and args.risk_status is not GateStatus.APROBADO:
            parser.error("--risk-option-type solo se usa cuando --risk-status es APROBADO.")
        try:
            rows = run_batch_validation(
                input_dir=args.input_dir,
                output_dir=args.output_dir,
                risk_status=args.risk_status,
                risk_option_type=args.risk_option_type,
                governance_status=args.governance_status,
                audit_output_csv=args.audit_output_csv,
                review_output_csv=args.review_output_csv,
                operator_board_output_csv=args.operator_board_output_csv,
                require_complete_packages=True,
            )
        except ValueError as error:
            parser.error(str(error))
        print(f"Paquetes validados: {len(rows)}")
        return 0
    if args.write_intake_from_input:
        if not args.input_dir:
            parser.error("--input-dir es obligatorio con --write-intake-from-input.")
        output_path = write_case_intake_from_input(
            input_dir=args.input_dir,
            output_csv=args.write_intake_from_input,
        )
        print(f"Intake generado desde carpeta: {output_path}")
        return 0
    if args.write_package_inventory:
        if not args.input_dir:
            parser.error("--input-dir es obligatorio con --write-package-inventory.")
        rows = write_package_inventory(
            input_dir=args.input_dir,
            output_csv=args.write_package_inventory,
        )
        incomplete = sum(1 for row in rows if row["status"] != "LISTO")
        print(f"Paquetes inventariados: {len(rows)} incompletos: {incomplete}")
        return 1 if incomplete else 0
    if args.check_intake_csv:
        if not args.input_dir:
            parser.error("--input-dir es obligatorio con --check-intake-csv.")
        rows = check_case_intake(
            intake_csv=args.check_intake_csv,
            input_dir=args.input_dir,
            output_csv=args.intake_check_output_csv,
        )
        incomplete = sum(1 for row in rows if row["status"] != "LISTO")
        print(f"Casos intake revisados: {len(rows)} incompletos: {incomplete}")
        return 1 if incomplete else 0
    if not args.input_dir or not args.output_dir:
        parser.error("--input-dir y --output-dir son obligatorios salvo con --write-intake-template.")
    if args.risk_option_type and args.risk_status is not GateStatus.APROBADO:
        parser.error("--risk-option-type solo se usa cuando --risk-status es APROBADO.")
    try:
        rows = run_batch_validation(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            risk_status=args.risk_status,
            risk_option_type=args.risk_option_type,
            governance_status=args.governance_status,
            audit_output_csv=args.audit_output_csv,
            review_output_csv=args.review_output_csv,
            operator_board_output_csv=args.operator_board_output_csv,
            require_complete_packages=args.require_complete_packages,
        )
    except ValueError as error:
        parser.error(str(error))
    print(f"Paquetes validados: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
