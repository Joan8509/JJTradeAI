"""Validador reproducible de paquetes TC2000 para JJTrade AI.

Este módulo permite correr el motor autoritativo fuera de Streamlit usando
archivos exportados desde TC2000. Su propósito no es emitir órdenes, sino crear
reportes JSON auditables para validar la metodología con datos reales.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from analysis_models import DirectionBias, GateStatus
from analysis_pipeline import AnalysisContext
from assessment_service import MarketAssessment, assess_market
from data_providers import (
    DataBundle,
    DataProviderKind,
    data_source_metadata,
    load_tc2000_file_bundle,
    load_tc2000_file_data_bundle,
)
from reporting import build_analysis_report, report_to_json
from review_catalog import format_review_catalog, is_known_review_key
from version import APP_VERSION, METHODOLOGY_VERSION


def load_tc2000_bundle(
    *,
    timeframe_15m: str | Path | None = None,
    timeframe_1h: str | Path | None = None,
    timeframe_1d: str | Path | None = None,
) -> dict[str, Any]:
    """Carga un paquete multitemporal con las temporalidades disponibles.

    Se permite validar paquetes incompletos para inspección; el motor registrará
    detectores omitidos cuando falten temporalidades obligatorias.
    """
    return load_tc2000_file_bundle(
        timeframe_15m=timeframe_15m,
        timeframe_1h=timeframe_1h,
        timeframe_1d=timeframe_1d,
    )


def _latest_data_timestamp(datasets: dict[str, Any]) -> str:
    """Devuelve la fecha más reciente encontrada entre las temporalidades."""
    latest_values = [
        frame["date"].max()
        for frame in datasets.values()
        if "date" in frame.columns and not frame.empty
    ]
    if not latest_values:
        return "SIN_FECHA"
    return max(latest_values).isoformat()


def run_validation_assessment(
    *,
    symbol: str,
    datasets: dict[str, Any],
    reviews: dict[str, bool | None] | None = None,
    session_closed: bool = False,
    panorama_path_clear: bool | None = None,
    news_clear: bool | None = None,
    panorama_human_approval: bool | None = None,
    data_current_review: bool | None = None,
    governance_status: GateStatus = GateStatus.NO_DISPONIBLE,
    risk_status: GateStatus = GateStatus.NO_DISPONIBLE,
    risk_option_type: str | None = None,
    data_source: dict[str, Any] | None = None,
    auxiliary_datasets: dict[str, Any] | None = None,
    live_market_data: bool = False,
) -> tuple[MarketAssessment, dict[str, Any]]:
    """Ejecuta la evaluación completa y devuelve el objeto y su reporte JSONable."""
    merged_reviews = dict(reviews or {})
    if news_clear is not None and "common.news_clear" not in merged_reviews:
        merged_reviews["common.news_clear"] = news_clear
    effective_news_clear = merged_reviews.get("common.news_clear", news_clear)
    context = AnalysisContext(
        datasets=datasets,
        reviews=merged_reviews,
        session_closed=session_closed,
        auxiliary_datasets=dict(auxiliary_datasets or {}),
        live_market_data=live_market_data,
    )
    assessment = assess_market(
        context,
        panorama_path_clear=panorama_path_clear,
        news_clear=effective_news_clear,
        panorama_human_approval=panorama_human_approval,
        data_current_review=data_current_review,
        risk_status=risk_status,
        risk_option_type=risk_option_type,
        governance_status=governance_status,
    )
    report = build_analysis_report(
        symbol=symbol,
        data_as_of=_latest_data_timestamp(datasets),
        methodology_version=METHODOLOGY_VERSION,
        app_version=APP_VERSION,
        strategies={
            "evaluations": assessment.pipeline.evaluations,
            "skipped": assessment.pipeline.skipped,
            "errors": assessment.pipeline.errors,
        },
        panorama=assessment.panorama,
        invalidations=assessment.invalidations,
        levels=assessment.levels,
        data_quality=assessment.data_quality,
        risk={"status": assessment.decision.risk_status},
        governance={"status": assessment.decision.governance_status},
        decision=assessment.decision,
        data_source=data_source,
    )
    return assessment, report


def run_validation_bundle_assessment(
    *,
    symbol: str,
    bundle: DataBundle,
    **kwargs: Any,
) -> tuple[MarketAssessment, dict[str, Any]]:
    """Ejecuta una evaluación usando un bundle con trazabilidad de fuente."""
    return run_validation_assessment(
        symbol=symbol,
        datasets=dict(bundle.datasets),
        auxiliary_datasets=dict(bundle.auxiliary_datasets),
        data_source=data_source_metadata(bundle),
        live_market_data=bundle.provider is DataProviderKind.MARKET_DATA_API,
        **kwargs,
    )


def _parse_optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"si", "sí", "s", "yes", "y", "true", "1"}:
        return True
    if normalized in {"no", "n", "false", "0"}:
        return False
    if normalized in {"pendiente", "none", "null", "na", "n/a"}:
        return None
    raise argparse.ArgumentTypeError(
        f"Valor booleano no reconocido: {value}. Use si, no o pendiente."
    )


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


def _parse_review(raw: str) -> tuple[str, bool | None]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            "Cada revisión debe tener formato clave=si|no|pendiente."
        )
    key, value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("La clave de revisión no puede estar vacía.")
    if not is_known_review_key(key):
        raise argparse.ArgumentTypeError(
            f"Clave de revisión desconocida: {key}. Use --list-reviews."
        )
    return key, _parse_optional_bool(value)


def build_arg_parser() -> argparse.ArgumentParser:
    """Construye el parser CLI del validador."""
    parser = argparse.ArgumentParser(
        description="Valida un paquete TC2000 con el motor JJTrade AI."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"JJTrade AI {APP_VERSION} / {METHODOLOGY_VERSION}",
    )
    parser.add_argument("--symbol", help="Símbolo evaluado, ejemplo SPY.")
    parser.add_argument(
        "--list-reviews",
        action="store_true",
        help="Lista las claves oficiales aceptadas por --review.",
    )
    parser.add_argument("--tf15", help="Archivo TC2000 de 15 minutos.")
    parser.add_argument("--tf1h", help="Archivo TC2000 de 1 hora.")
    parser.add_argument("--tf1d", help="Archivo TC2000 diario.")
    parser.add_argument(
        "--output",
        help="Ruta donde guardar el JSON. Si se omite, se imprime en consola.",
    )
    parser.add_argument(
        "--review",
        action="append",
        default=[],
        type=_parse_review,
        help="Revisión manual en formato clave=si|no|pendiente.",
    )
    parser.add_argument(
        "--session-closed",
        action="store_true",
        help="Marca la sesión como cerrada para detectores que lo requieren.",
    )
    parser.add_argument("--path-clear", type=_parse_optional_bool)
    parser.add_argument("--news-clear", type=_parse_optional_bool)
    parser.add_argument("--panorama-approved", type=_parse_optional_bool)
    parser.add_argument("--data-current", type=_parse_optional_bool)
    parser.add_argument(
        "--risk-status",
        type=_parse_gate_status,
        default=GateStatus.NO_DISPONIBLE,
        help=(
            "Estado revisado de riesgo: APROBADO, RECHAZADO, "
            "NO_DISPONIBLE o REQUIERE_REVISION."
        ),
    )
    parser.add_argument(
        "--risk-option-type",
        type=_parse_option_type,
        help="Tipo del contrato revisado para riesgo aprobado: CALL o PUT.",
    )
    parser.add_argument(
        "--governance-status",
        type=_parse_gate_status,
        default=GateStatus.NO_DISPONIBLE,
        help=(
            "Estado revisado de gobierno operativo: APROBADO, RECHAZADO, "
            "NO_DISPONIBLE o REQUIERE_REVISION."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI para generar reportes de validación."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.list_reviews:
        print(format_review_catalog())
        return 0
    if not args.symbol:
        parser.error("--symbol es obligatorio salvo cuando se usa --list-reviews.")
    if args.risk_option_type and args.risk_status is not GateStatus.APROBADO:
        parser.error("--risk-option-type solo se usa cuando --risk-status es APROBADO.")
    try:
        bundle = load_tc2000_file_data_bundle(
            timeframe_15m=args.tf15,
            timeframe_1h=args.tf1h,
            timeframe_1d=args.tf1d,
        )
        _, report = run_validation_bundle_assessment(
            symbol=args.symbol,
            bundle=bundle,
            reviews=dict(args.review),
            session_closed=args.session_closed,
            panorama_path_clear=args.path_clear,
            news_clear=args.news_clear,
            panorama_human_approval=args.panorama_approved,
            data_current_review=args.data_current,
            risk_status=args.risk_status,
            risk_option_type=args.risk_option_type,
            governance_status=args.governance_status,
        )
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    payload = report_to_json(report)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
