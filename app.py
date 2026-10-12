"""Interfaz local de decisión asistida para JJTrade AI."""

from collections.abc import Mapping, Sequence
import base64
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import html
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from analysis_pipeline import AnalysisContext
from analysis_models import GateStatus
from assessment_service import assess_market
from data_quality import evaluate_data_quality
from data_providers import (
    build_demo_data_bundle,
    data_source_metadata,
    load_tc2000_upload_data_bundle,
)
from alpaca_market_data import (
    AlpacaMarketConfig,
    AlpacaMarketDataProvider,
    build_alpaca_data_bundle,
)
from market_store import MarketBarStore, MarketContinuityService
from market_calendar import AlpacaMarketCalendarProvider, MarketSessionRepository, session_close_map
from live_preflight import recent_live_preflights
from live_bollinger_preview import LiveBollingerPreviewRepository
from operational_monitor import evaluate_operational_status
from market_reconciliation import MarketReconciliationRepository
from scanner_control import build_scanner_arguments, start_scanner, stop_scanner
from scanner_instance import read_instance_status
from scanner_incident import ScannerIncidentRepository
from paper_readiness import evaluate_paper_readiness
from paper_session_evidence import build_paper_session_evidence
from price_ranges import calculate_price_range, load_option_price_ranges
from option_market_data import (
    AlpacaOptionDataProvider,
    OptionSelectionPolicy,
    select_option_candidates,
)
from demo_data import generate_demo_datasets
from governance import (
    GovernanceLimits,
    GovernanceRequest,
    OperationWorkflow,
    TradingMode,
    evaluate_governance,
)
from investep_engine import evaluate_expuesto_bollinger
from journal import JournalRepository
from live_strategy_service import AlertRepository
from live_service_runtime import ServiceHealthRepository
from visual_evidence import VisualEvidenceRepository
from worden_review import WordenReviewRepository
from minute_gap_audit import recover_session_gaps
from safe_diagnostics import sanitize_diagnostic_detail
from paper_entry_validation import entry_evidence, validate_paper_entry
from alert_reevaluation import reevaluate_alert
from learning_engine import audit_learning_advisory, evaluate_temporal_stability, summarize_alert_feedback, summarize_context_performance, summarize_strategy_performance
from risk_engine import OptionQuote, RiskLimits, evaluate_option_risk
from reporting import build_analysis_report, report_to_json
from report_auditor import REVIEW_QUEUE_FIELDS, audit_report, build_review_queue
from strategy_registry import STRATEGY_REGISTRY
from strategy_scanner import build_strategy_scan_rows
from strategies.efecto_iman import evaluate_efecto_iman
from strategies.ct15 import evaluate_ct15
from strategies.cambio_tendencia_hora import evaluate_cambio_tendencia_hora
from strategies.momentum import evaluate_momentum
from strategies.primer_salto import evaluate_first_jump_setup
from strategies.rebote_punto_medio import evaluate_rebote_punto_medio
from strategies.retorno_bollinger_lateral import evaluate_retorno_bollinger_lateral
from strategies.salto_lateralidad_hora import evaluate_salto_lateralidad_hora
from validation_batch import INTAKE_TEMPLATE_FIELDS, OPERATOR_BOARD_FIELDS
from version import APP_VERSION, METHODOLOGY_VERSION
from watchlist_config import DEFAULT_SYMBOLS_TEXT, load_watchlist
from setup_timing import evaluate_setup_timing
from alert_event import setup_signature


st.set_page_config(page_title="JJTrade AI", page_icon="📈", layout="wide")


def _status_label(value: object) -> str:
    """Convierte enums y valores simples a texto para la interfaz."""
    return str(getattr(value, "value", value))


def _strategy_evaluation_label(evaluation: object) -> str:
    """Etiqueta una evaluación multitemporal para interfaz y diario."""
    strategy_id = str(getattr(evaluation, "strategy_id", ""))
    timeframe = str(getattr(evaluation, "timeframe", ""))
    return f"{strategy_id}@{timeframe}" if timeframe else strategy_id


def _criteria_table(evaluation: object) -> pd.DataFrame:
    """Prepara criterios auditables para su presentación."""
    criteria = getattr(evaluation, "criteria", evaluation)
    return pd.DataFrame(
        [
            {
                "Criterio": item.name,
                "Estado": _status_label(item.status),
                "Obligatorio": "Sí" if item.required else "No",
                "Detalle": item.detail,
                "Fuente": item.source,
            }
            for item in criteria
        ]
    )


def _strategy_radar_table(evaluations: object) -> pd.DataFrame:
    """Resume todos los detectores ejecutados sin esconder pendientes."""
    def next_required_item(evaluation: object) -> str:
        for criterion in evaluation.criteria:
            if criterion.required and _status_label(criterion.status) != "CUMPLE":
                return f"{criterion.name} ({_status_label(criterion.status)})"
        return ""

    return pd.DataFrame(
        [
            {
                "Estrategia": item.name,
                "ID": item.strategy_id,
                "Temporalidad": item.timeframe or "N/D",
                "Categoria": (
                    STRATEGY_REGISTRY[item.strategy_id]["categoria"].value
                    if item.strategy_id in STRATEGY_REGISTRY
                    else "DIAGNOSTICO"
                    if item.strategy_id.startswith("SIN_")
                    else ""
                ),
                "Detectada": "SI" if item.detected else "NO",
                "Sesgo": item.bias.value,
                "Requiere confirmacion": (
                    "SI"
                    if item.strategy_id in STRATEGY_REGISTRY
                    and STRATEGY_REGISTRY[item.strategy_id]["requiere_confirmacion"]
                    else "NO"
                ),
                "Cumplimiento": f"{item.compliance_percentage:.2f}%",
                "Requisitos completos": (
                    "SI" if item.required_criteria_satisfied else "NO"
                ),
                "Pendientes": sum(
                    criterion.required
                    and _status_label(criterion.status)
                    in {"NO_DISPONIBLE", "REQUIERE_REVISION"}
                    for criterion in item.criteria
                ),
                "Fallidos": sum(
                    criterion.required
                    and _status_label(criterion.status) == "NO_CUMPLE"
                    for criterion in item.criteria
                ),
                "Siguiente revision": next_required_item(item),
            }
            for item in evaluations
        ]
    )


def _strategy_scan_table(rows: object) -> pd.DataFrame:
    """Presenta filas multi-activo del scanner en orden accionable."""
    state_order = {
        "CONFIRMADA": 0,
        "CANDIDATA": 1,
        "FALLIDA": 2,
        "NO_DETECTADA": 3,
    }
    columns = [
        "Simbolo", "Fecha", "Estrategia", "ID", "Temporalidad", "Sesgo",
        "Estado", "Cumplimiento %", "Requisitos", "Pendientes", "Fallidos",
        "Siguiente revision", "Decision final", "Readiness",
    ]
    table = pd.DataFrame(
        [
            {
                "Simbolo": item["symbol"],
                "Fecha": item["data_as_of"],
                "Estrategia": item["strategy_name"],
                "ID": item["strategy_id"],
                "Temporalidad": item["timeframe"] or "N/D",
                "Sesgo": item["bias"],
                "Estado": item["state"],
                "Cumplimiento %": item["compliance_percentage"],
                "Requisitos": item["required_count"],
                "Pendientes": item["pending_count"],
                "Fallidos": item["failed_count"],
                "Siguiente revision": item["next_required"] or "N/D",
                "Decision final": item["final_decision"],
                "Readiness": item["readiness"],
            }
            for item in rows
        ],
        columns=columns,
    )
    if table.empty:
        return table
    table["_orden_estado"] = table["Estado"].map(state_order).fillna(99)
    return (
        table.sort_values(
            ["_orden_estado", "Cumplimiento %", "Simbolo"],
            ascending=[True, False, True],
        )
        .drop(columns="_orden_estado")
        .reset_index(drop=True)
    )


def _skipped_detectors_table(skipped: object) -> pd.DataFrame:
    """Presenta detectores omitidos por falta de temporalidades."""
    return pd.DataFrame(
        [
            {"Detector": detector_id, "Motivo": reason}
            for detector_id, reason in skipped.items()
        ]
    )


def _data_source_table(data_source: Mapping[str, object]) -> pd.DataFrame:
    """Presenta la trazabilidad de datos usada por el analisis."""
    timeframes = data_source.get("timeframes", ())
    if not isinstance(timeframes, (list, tuple)):
        timeframes = ()
    files = data_source.get("files", {})
    if not isinstance(files, Mapping):
        files = {}
    closed_through = data_source.get("closed_through", {})
    if not isinstance(closed_through, Mapping):
        closed_through = {}
    return pd.DataFrame(
        [
            {
                "Fuente": str(data_source.get("provider") or "N/D"),
                "Proveedor": str(data_source.get("vendor") or "N/D"),
                "Símbolo": str(data_source.get("symbol") or "N/D"),
                "Feed": str(data_source.get("feed") or "N/D"),
                "Temporalidades": ", ".join(str(item) for item in timeframes) or "N/D",
                "Archivos": ", ".join(
                    f"{timeframe}: {path}"
                    for timeframe, path in sorted(files.items())
                )
                or "N/D",
                "Cierres confirmados": ", ".join(
                    f"{timeframe}: {closed_through[timeframe]}"
                    for timeframe in ("15m", "1H", "1D")
                    if timeframe in closed_through
                )
                or "N/D",
            }
        ]
    )


def _live_alerts_table(alerts: object) -> pd.DataFrame:
    """Resume alertas automáticas sin convertirlas en órdenes."""
    rows = []
    for item in alerts:
        report = item.get("report", {})
        option_selection = (
            report.get("option_selection", {}) if isinstance(report, Mapping) else {}
        )
        if not isinstance(option_selection, Mapping):
            option_selection = {}
        freshness = (
            report.get("live_data_freshness", {})
            if isinstance(report, Mapping)
            else {}
        )
        if not isinstance(freshness, Mapping):
            freshness = {}
        rows.append(
            {
                "ID": item["id"],
                "Creada": item["created_at"],
                "Símbolo": item["symbol"],
                "Vela": item["trigger_timestamp"],
                "Feed": item["feed"],
                "Decisión": item["decision"],
                "Evento": item.get("event_type", "LEGACY"),
                "Prioridad": item.get("event_priority", "INFO"),
                "Detectadas": item["detected_count"],
                "Confirmadas": item["confirmed_count"],
                "Frescura": freshness.get("status", "NO_EVALUADA"),
                "Edad (s)": freshness.get("age_seconds", "N/D"),
                "Huecos recientes": int(freshness.get("recent_gap_count", 0)),
                "Opciones": option_selection.get("status", "NO_EVALUADAS"),
                "Contratos elegibles": int(option_selection.get("eligible_count", 0)),
            }
        )
    return pd.DataFrame(rows)


def _simple_alert_summary(alert: Mapping[str, object]) -> dict[str, object]:
    """Reduce una alerta auditable a la informacion necesaria para decidir."""
    report = alert.get("report", {})
    if not isinstance(report, Mapping):
        report = {}
    decision = report.get("decision", {})
    if not isinstance(decision, Mapping):
        decision = {}
    strategies = report.get("strategies", {})
    if not isinstance(strategies, Mapping):
        strategies = {}
    evaluations = strategies.get("evaluations", ())
    if not isinstance(evaluations, (list, tuple)):
        evaluations = ()

    detected = [
        item for item in evaluations
        if isinstance(item, Mapping) and item.get("detected") is True
    ]
    supporting = [str(item) for item in decision.get("supporting_strategies", ())]
    supporting_ids = {item.split("@", 1)[0] for item in supporting}
    confirmed_names = [
        str(item.get("name") or item.get("strategy_id"))
        for item in detected
        if str(item.get("strategy_id")) in supporting_ids
    ]
    forming_names = [
        str(item.get("name") or item.get("strategy_id"))
        for item in detected
        if str(item.get("strategy_id")) not in supporting_ids
    ]
    detected_biases = {
        str(item.get("bias", "")).upper()
        for item in detected
        if str(item.get("bias", "")).upper() in {"CALL", "PUT"}
    }
    confirmed_biases = {
        str(item.get("bias", "")).upper()
        for item in detected
        if str(item.get("strategy_id")) in supporting_ids
        and str(item.get("bias", "")).upper() in {"CALL", "PUT"}
    }
    biases = confirmed_biases or detected_biases
    direction = next(iter(biases)) if len(biases) == 1 else "MIXTO" if biases else "SIN_SESGO"
    final_decision = str(decision.get("decision") or alert.get("decision") or "NO_OPERAR")
    data_source = report.get("data_source", {})
    if not isinstance(data_source, Mapping):
        data_source = {}
    feed = str(data_source.get("feed") or alert.get("feed") or "NO_DISPONIBLE").lower()
    reasons = decision.get("reasons", ())
    if not isinstance(reasons, (list, tuple)):
        reasons = ()
    timing = report.get("setup_timing", {})
    if not isinstance(timing, Mapping) or not timing:
        timing = evaluate_setup_timing(report)
    if confirmed_names:
        setup_status = "CONFIRMADA"
        strategy_label = ", ".join(confirmed_names)
        relevant_evaluations = [
            item for item in detected
            if str(item.get("strategy_id")) in supporting_ids
        ]
    elif forming_names:
        setup_status = "EN_FORMACION"
        strategy_label = ", ".join(forming_names)
        relevant_evaluations = detected
    else:
        setup_status = "SIN_ESTRATEGIA"
        strategy_label = "Ninguna"
        relevant_evaluations = []
    technical_pending = []
    for evaluation in relevant_evaluations:
        criteria = evaluation.get("criteria", ())
        if not isinstance(criteria, (list, tuple)):
            continue
        technical_pending.extend(
            str(criterion.get("name") or criterion.get("criterion_id"))
            for criterion in criteria
            if isinstance(criterion, Mapping)
            and criterion.get("required") is True
            and str(criterion.get("status")) != "CUMPLE"
        )
    timeframes = tuple(dict.fromkeys(
        str(item.get("timeframe") or "N/D") for item in relevant_evaluations
    ))
    return {
        "alert_id": int(alert.get("id", 0) or 0),
        "symbol": str(alert.get("symbol") or report.get("symbol") or "N/D"),
        "trigger_timestamp": str(alert.get("trigger_timestamp") or report.get("data_as_of") or "N/D"),
        "setup_status": setup_status,
        "strategy": strategy_label,
        "timeframe": ", ".join(timeframes) if timeframes else "N/D",
        "forming_strategies": forming_names,
        "direction": direction,
        "decision": final_decision,
        "can_operate": final_decision in {"CALL", "PUT"},
        "feed": feed,
        "paper_only": True,
        "feed_scope": (
            "MERCADO_CONSOLIDADO" if feed == "sip"
            else "RETRASADO" if feed == "delayed_sip"
            else "RADAR_PARCIAL" if feed == "iex"
            else "NO_VALIDADO"
        ),
        "timing_status": str(timing.get("status", "NO_EVALUADA")),
        "timing_reason": str(timing.get("reason", "Vigencia no evaluada.")),
        "technical_pending": technical_pending,
        "next_requirement": (
            str(timing.get("reason"))
            if timing.get("status") == "VENCIDA"
            else technical_pending[0]
            if setup_status == "EN_FORMACION" and technical_pending
            else str(reasons[0])
            if final_decision not in {"CALL", "PUT"} and reasons
            else "Ninguno; lista para simulacion PAPER."
        ),
        "main_reason": str(reasons[0]) if reasons else "Sin explicacion disponible.",
    }


def _current_strategy_certainty(report: Mapping[str, object]) -> dict[str, object]:
    """Resume la estrategia dominante y su certidumbre histórica para la alerta seleccionada."""
    if not isinstance(report, Mapping):
        return {"strategy": "SIN_ESTRATEGIA", "confidence": 0.0, "priority": "MINIMA", "direction": "SIN_SESGO", "status": "MUESTRA_INSUFICIENTE"}

    combined_sources = []
    for key in ("automatic_learning_signal", "directional_learning_signal"):
        signal = report.get(key, {})
        if not isinstance(signal, Mapping):
            continue
        rows = signal.get("rows", []) if isinstance(signal, Mapping) else []
        if not rows:
            continue
        source_priority = 1 if key == "automatic_learning_signal" else 0
        best = max(rows, key=lambda row: float(row.get("confidence_score") or 0.0))
        combined_sources.append({
            "source_priority": source_priority,
            "strategy": str(best.get("strategy_id") or "SIN_ESTRATEGIA"),
            "confidence": float(best.get("confidence_score") or 0.0),
            "priority": str(best.get("priority") or "MINIMA"),
            "direction": str(best.get("historical_direction") or "NO_CALIBRADA"),
            "status": str(signal.get("status") or "MUESTRA_INSUFICIENTE"),
            "summary_score": float(signal.get("summary_score") or 0.0),
        })

    if not combined_sources:
        return {"strategy": "SIN_ESTRATEGIA", "confidence": 0.0, "priority": "MINIMA", "direction": "SIN_SESGO", "status": "MUESTRA_INSUFICIENTE"}

    preferred = max(
        combined_sources,
        key=lambda item: (
            item["confidence"],
            1 if item["priority"].upper() == "ALTA" else 0 if item["priority"].upper() == "MEDIA" else -1 if item["priority"].upper() == "BAJA" else -2,
            item["source_priority"],
        ),
    )
    return {
        "strategy": preferred["strategy"],
        "confidence": preferred["confidence"],
        "priority": preferred["priority"],
        "direction": preferred["direction"],
        "status": preferred["status"],
    }


def _preview_confidence_badge(report: Mapping[str, object] | None, *, direction_status: str | None = None) -> dict[str, object]:
    """Devuelve la cara visible de la certeza histórica para un resumen live."""
    if not isinstance(report, Mapping):
        report = {}
    combined_sources = []
    for key in ("automatic_learning_signal", "directional_learning_signal"):
        signal = report.get(key, {})
        if not isinstance(signal, Mapping):
            continue
        rows = signal.get("rows", []) if isinstance(signal, Mapping) else []
        if not rows:
            continue
        best = max(rows, key=lambda row: float(row.get("confidence_score") or 0.0))
        confidence = float(best.get("confidence_score") or 0.0)
        priority = str(best.get("priority") or "MINIMA").upper()
        combined_sources.append((confidence, priority))
    if combined_sources:
        confidence, priority = max(
            combined_sources,
            key=lambda item: (
                item[0],
                1 if item[1] == "ALTA" else 0 if item[1] == "MEDIA" else -1 if item[1] == "BAJA" else -2,
            ),
        )
        if confidence >= 80 or priority == "ALTA":
            label, tone = "ALTA", "high"
        elif confidence >= 60 or priority == "MEDIA":
            label, tone = "MEDIA", "medium"
        elif confidence > 0 or priority == "BAJA":
            label, tone = "BAJA", "low"
        else:
            label, tone = "SIN_CERTIDUMBRE", "none"
        return {
            "label": label,
            "priority": priority,
            "confidence_pct": int(round(confidence)),
            "tone": tone,
        }
    status_text = str(direction_status or "").upper()
    if "DIRECCIONES EN CONFLICTO" in status_text or "SIN DIRECCIÓN CONFIRMADA" in status_text:
        return {"label": "BAJA", "priority": "BAJA", "confidence_pct": 25, "tone": "low"}
    if "EN FORMACION" in status_text or "REQUIERE CONFIRMACION" in status_text or "PRELIMINAR" in status_text:
        return {"label": "MEDIA", "priority": "MEDIA", "confidence_pct": 55, "tone": "medium"}
    return {"label": "SIN_CERTIDUMBRE", "priority": "MINIMA", "confidence_pct": 0, "tone": "none"}


def _live_direction_guidance(report: Mapping[str, object]) -> dict[str, object]:
    """Devuelve la orientación de dirección probable para una alerta en vivo."""
    if not isinstance(report, Mapping):
        return {"direction": "SIN_SESGO", "status": "SIN_EVIDENCIA", "confidence_pct": 0, "priority": "MINIMA"}

    automatic = report.get("automatic_learning_signal", {})
    if isinstance(automatic, Mapping):
        status = str(automatic.get("status", "MUESTRA_INSUFICIENTE"))
        direction = str(automatic.get("recommended_direction") or "").upper()
        confidence = float(automatic.get("summary_score") or 0.0)
        if direction in {"CALL", "PUT"}:
            if status == "APRENDIZAJE_ALINEADO":
                if confidence >= 80:
                    return {"direction": direction, "status": "CONFIRMADA", "confidence_pct": int(round(confidence)), "priority": "ALTA"}
                if confidence >= 60:
                    return {"direction": direction, "status": "PROBABLE", "confidence_pct": int(round(confidence)), "priority": "MEDIA"}
            if status == "APRENDIZAJE_CONTRARIO":
                return {"direction": direction, "status": "CONTRARIA", "confidence_pct": int(round(confidence)), "priority": "MINIMA"}

    signal = report.get("directional_learning_signal", {})
    if isinstance(signal, Mapping):
        rows = signal.get("rows", []) if isinstance(signal, Mapping) else []
        if rows:
            best = max(rows, key=lambda row: float(row.get("confidence_score") or 0.0))
            direction = str(best.get("historical_direction") or "").upper()
            confidence = float(best.get("confidence_score") or 0.0)
            priority = str(best.get("priority") or "MINIMA").upper()
            if direction in {"CALL", "PUT"}:
                if confidence >= 80 or priority == "ALTA":
                    return {"direction": direction, "status": "CONFIRMADA", "confidence_pct": int(round(confidence)), "priority": priority}
                if confidence >= 60 or priority == "MEDIA":
                    return {"direction": direction, "status": "PROBABLE", "confidence_pct": int(round(confidence)), "priority": priority}
                return {"direction": direction, "status": "PENDIENTE", "confidence_pct": int(round(confidence)), "priority": priority}

    decision = report.get("decision", {})
    if isinstance(decision, Mapping):
        direction = str(decision.get("decision") or "").upper()
        if direction in {"CALL", "PUT"}:
            return {"direction": direction, "status": "PENDIENTE", "confidence_pct": 0, "priority": "MINIMA"}

    return {"direction": "SIN_SESGO", "status": "SIN_EVIDENCIA", "confidence_pct": 0, "priority": "MINIMA"}


def _lead_live_signal(alerts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Devuelve la señal principal más fuerte para destacar en la UI."""
    if not alerts:
        return {"direction": "SIN_SESGO", "status": "SIN_EVIDENCIA", "confidence_pct": 0, "priority": "MINIMA", "strategy": "SIN_ESTRATEGIA"}

    status_rank = {"CONFIRMADA": 5, "PROBABLE": 4, "PENDIENTE": 3, "CONTRARIA": -5, "SIN_EVIDENCIA": -10}
    priority_rank = {"ALTA": 3, "MEDIA": 2, "BAJA": 1, "MINIMA": 0}

    def ranking_key(item: Mapping[str, object]) -> tuple[int, int, int]:
        status = str(item.get("status", "SIN_EVIDENCIA")).upper()
        priority = str(item.get("priority", "MINIMA")).upper()
        confidence = int(item.get("confidence_pct", 0))
        return (
            status_rank.get(status, -99),
            priority_rank.get(priority, -1),
            confidence,
        )

    best = max(
        (
            {
                **_live_direction_guidance(item.get("report", {})),
                "strategy": str(_current_strategy_certainty(item.get("report", {})).get("strategy", "SIN_ESTRATEGIA")),
            }
            for item in alerts
            if isinstance(item, Mapping)
        ),
        key=ranking_key,
        default={"direction": "SIN_SESGO", "status": "SIN_EVIDENCIA", "confidence_pct": 0, "priority": "MINIMA", "strategy": "SIN_ESTRATEGIA"},
    )
    return best


def _alert_live_certainty_rank(item: Mapping[str, object]) -> tuple[float, int, int]:
    """Ordena alertas por certidumbre real del movimiento aprendido y la fuerza histórica."""
    report = item.get("report", {}) if isinstance(item, Mapping) else {}
    if not isinstance(report, Mapping):
        return (0.0, 0, int(item.get("id", 0)))

    priority_rank = {"ALTA": 3, "MEDIA": 2, "BAJA": 1, "MINIMA": 0}
    status_rank = {"CONFIRMADA": 3, "PROBABLE": 2, "PENDIENTE": 1, "CONTRARIA": -1, "SIN_EVIDENCIA": 0}

    automatic = report.get("automatic_learning_signal", {})
    auto_score = 0.0
    auto_priority = "MINIMA"
    auto_status = "SIN_EVIDENCIA"
    if isinstance(automatic, Mapping):
        auto_status = str(automatic.get("status", "SIN_EVIDENCIA")).upper()
        auto_score = float(automatic.get("summary_score") or 0.0)
        rows = automatic.get("rows", []) if isinstance(automatic, Mapping) else []
        if rows:
            best_auto_row = max(rows, key=lambda row: float(row.get("confidence_score") or 0.0))
            auto_score = max(auto_score, float(best_auto_row.get("confidence_score") or 0.0))
            auto_priority = str(best_auto_row.get("priority") or automatic.get("priority") or "MINIMA").upper()

    directional = report.get("directional_learning_signal", {})
    best_score = 0.0
    best_priority = "MINIMA"
    best_status = "SIN_EVIDENCIA"
    if isinstance(directional, Mapping):
        rows = directional.get("rows", []) if isinstance(directional, Mapping) else []
        if rows:
            best_row = max(rows, key=lambda row: float(row.get("confidence_score") or 0.0))
            best_score = float(best_row.get("confidence_score") or 0.0)
            best_priority = str(best_row.get("priority") or "MINIMA").upper()
            best_status = str(directional.get("status", "SIN_EVIDENCIA")).upper()

    confidence_score = max(best_score, auto_score)
    confidence_priority = max(
        (best_priority, auto_priority),
        key=lambda name: priority_rank.get(name.upper(), 0),
        default="MINIMA",
    )
    confidence_status = max(
        (best_status, auto_status),
        key=lambda name: status_rank.get(name.upper(), -99),
        default="SIN_EVIDENCIA",
    )
    if confidence_status == "CONTRARIA":
        confidence_score *= 0.4
    return (
        confidence_score,
        priority_rank.get(confidence_priority.upper(), 0) + status_rank.get(confidence_status.upper(), 0),
        int(item.get("id", 0)),
    )


def _operating_signal_status(report: Mapping[str, object]) -> dict[str, object]:
    """Clasifica una alerta para PAPER sin autorizar ejecucion real."""
    if not isinstance(report, Mapping):
        return {"status": "BLOQUEADA", "label": "BLOQUEADA", "reasons": ["Reporte no disponible."]}

    reasons: list[str] = []
    decision_payload = report.get("decision", {})
    decision = str(decision_payload.get("decision", "NO_OPERAR")) if isinstance(decision_payload, Mapping) else "NO_OPERAR"
    if decision not in {"CALL", "PUT"}:
        reasons.append("La decision final no es operable.")

    freshness = report.get("live_data_freshness", {})
    if isinstance(freshness, Mapping) and freshness.get("status") not in {None, "APROBADO"}:
        reasons.append("La frescura de datos no esta aprobada.")
    reconciliation = report.get("market_data_reconciliation", {})
    if isinstance(reconciliation, Mapping) and reconciliation.get("status") not in {None, "APROBADO", "OMITIDO"}:
        reasons.append("La reconciliacion de mercado no esta aprobada.")

    timing = report.get("setup_timing", {})
    if isinstance(timing, Mapping) and str(timing.get("status", "")).upper() in {"VENCIDA", "BLOQUEADA"}:
        reasons.append("La vigencia del setup esta vencida o bloqueada.")

    automatic = report.get("automatic_learning_signal", {})
    automatic_status = str(automatic.get("status", "MUESTRA_INSUFICIENTE")) if isinstance(automatic, Mapping) else "MUESTRA_INSUFICIENTE"
    automatic_direction = str(automatic.get("recommended_direction") or "") if isinstance(automatic, Mapping) else ""
    automatic_score = float(automatic.get("summary_score") or 0.0) if isinstance(automatic, Mapping) else 0.0
    automatic_contradiction = automatic_status == "APRENDIZAJE_CONTRARIO" or (
        automatic_direction in {"CALL", "PUT"} and automatic_direction != decision
    )
    if automatic_status != "APRENDIZAJE_ALINEADO" or automatic_direction != decision or automatic_score < 80.0:
        reasons.append("La validacion automatica aun no confirma la direccion con umbral >= 80%.")

    if reasons:
        if automatic_contradiction:
            reasons[-1] = "La validacion automatica contradice la direccion actual."
        waiting_only = reasons == ["La validacion automatica aun no confirma la direccion con umbral >= 80%."]
        return {
            "status": "ESPERAR_VALIDACION" if waiting_only else "BLOQUEADA",
            "label": "ESPERAR VALIDACION" if waiting_only else "BLOQUEADA",
            "reasons": reasons,
            "paper_only": True,
            "real_trading_authorized": False,
        }
    return {
        "status": "PAPER_APTA_REVISION",
        "label": "PAPER APTA PARA REVISION",
        "reasons": ["Compuertas de senal y validacion automatica superadas; requiere revision antes de cualquier accion."],
        "paper_only": True,
        "real_trading_authorized": False,
    }


def _parse_alert_time(value: object) -> datetime | None:
    """Interpreta timestamps ISO de alertas y exige una zona horaria real."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _market_event_local_time(value: object) -> str:
    """Muestra el cierre efectivo del bloque que produjo la evaluacion."""
    timestamp = _parse_alert_time(value)
    if timestamp is None:
        return "Hora no disponible"
    local = timestamp.astimezone(ZoneInfo("America/New_York"))
    # Alpaca rotula el bloque con su ultimo minuto: 15:59 corresponde al
    # cierre/evaluacion de las 16:00.
    if local.minute % 15 == 14:
        local += timedelta(minutes=1)
    return local.strftime("%Y-%m-%d %I:%M %p ET")


def _simple_moment_status(
    summary: Mapping[str, object], *, scanner_active: bool,
    now: datetime | None = None, market_open: bool = True,
) -> dict[str, object]:
    """Determina si una alerta se revisa ahora o es solo historica."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now debe incluir zona horaria.")
    triggered = _parse_alert_time(summary.get("trigger_timestamp"))
    age_minutes = (
        max(0.0, (current - triggered.astimezone(timezone.utc)).total_seconds() / 60)
        if triggered else None
    )
    valid_until = None
    if triggered:
        trigger_utc = triggered.astimezone(timezone.utc)
        minutes_to_boundary = (15 - (trigger_utc.minute % 15)) % 15
        if minutes_to_boundary == 0:
            minutes_to_boundary = 15
        valid_until = trigger_utc.replace(second=0, microsecond=0) + timedelta(
            minutes=minutes_to_boundary
        )
        # Alpaca identifica el bloque con su ultimo minuto (por ejemplo 09:59
        # para la evaluacion de 10:00). Esa lectura sigue vigente hasta el
        # siguiente cierre, no solo durante el segundo en que se persiste.
        if trigger_utc.minute % 15 == 14:
            valid_until += timedelta(minutes=15)
    if not market_open or not scanner_active:
        status, label = "HISTORICA", "SESION FINALIZADA"
    elif valid_until is None or current.astimezone(timezone.utc) >= valid_until:
        status, label = "VENCIDA", "SENAL VENCIDA"
    elif summary.get("timing_status") == "VENCIDA":
        status, label = "FUERA_DE_VENTANA", "ESTRATEGIA VENCIDA"
    elif bool(summary.get("can_operate")) and bool(summary.get("paper_only", True)):
        status = "SIMULAR"
        label = f"SIMULAR {summary.get('decision')} EN PAPER"
    elif bool(summary.get("can_operate")):
        status = "OPERAR"
        label = f"OPERAR {summary.get('decision')} AHORA"
    elif summary.get("setup_status") == "CONFIRMADA":
        status, label = "REVISAR", "REVISAR AHORA"
    elif summary.get("setup_status") == "EN_FORMACION":
        status, label = "ESPERAR", "ESPERAR CONFIRMACION"
    else:
        status, label = "SIN_SETUP", "SIN OPORTUNIDAD"
    local_time = _market_event_local_time(summary.get("trigger_timestamp"))
    return {
        "status": status,
        "label": label,
        "age_minutes": age_minutes,
        "local_time": local_time,
    }


def _next_quarter_hour(now: datetime | None = None) -> datetime:
    """Calcula el siguiente cierre de vela de 15 minutos en Nueva York."""
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    minutes = 15 - (local.minute % 15)
    return (local + timedelta(minutes=minutes)).replace(second=0, microsecond=0)


def _current_live_previews(
    previews: list[dict[str, object]], *, now: datetime | None = None,
    maximum_age: timedelta = timedelta(minutes=3),
) -> list[dict[str, object]]:
    """Excluye estados de sesiones anteriores y previews atrasados."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now debe incluir zona horaria.")
    market_zone = ZoneInfo("America/New_York")
    current_local = current.astimezone(market_zone)
    fresh = []
    for item in previews:
        timestamp = _parse_alert_time(item.get("as_of"))
        if timestamp is None:
            continue
        local = timestamp.astimezone(market_zone)
        age = current.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)
        if local.date() == current_local.date() and timedelta(0) <= age <= maximum_age:
            fresh.append(item)
    return fresh


def _compact_operational_card(
    summary: Mapping[str, object], moment: Mapping[str, object],
) -> dict[str, str]:
    """Texto breve y no ambiguo para una tarjeta del radar."""
    state = str(summary.get("setup_status", "SIN_ESTRATEGIA")).replace("_", " ")
    if summary.get("timing_status") == "VENCIDA" or moment.get("status") == "FUERA_DE_VENTANA":
        state = "VENCIDA"
    elif moment.get("status") == "HISTORICA":
        state = f"{state} · HISTORICA"
    action = str(moment.get("label", "NO OPERAR"))
    if moment.get("status") in {"HISTORICA", "VENCIDA", "FUERA_DE_VENTANA"}:
        action = "NO OPERAR"
    return {
        "title": (
            f"{summary.get('symbol', 'N/D')} · "
            f"{summary.get('strategy', 'Ninguna')} · "
            f"{summary.get('timeframe', 'N/D')}"
        ),
        "state": state,
        "direction": str(summary.get("direction", "SIN_SESGO")),
        "action": action,
        "reason": str(summary.get("next_requirement", "Sin detalle.")),
    }


def _operational_notification(
    summary: Mapping[str, object], moment: Mapping[str, object],
) -> dict[str, str] | None:
    """Construye una alerta breve solo para oportunidades vigentes."""
    if str(moment.get("status")) in {
        "HISTORICA", "VENCIDA", "FUERA_DE_VENTANA", "SIN_SETUP",
    }:
        return None
    symbol = str(summary.get("symbol", "N/D"))
    strategy = str(summary.get("strategy", "Estrategia"))
    direction = str(summary.get("direction", "SIN_SESGO"))
    if bool(summary.get("can_operate")) and direction in {"CALL", "PUT"}:
        level = direction
        title = f"{direction} PAPER · {symbol}"
        icon = "✅" if direction == "CALL" else "📉"
    elif str(summary.get("setup_status")) == "EN_FORMACION":
        level, title, icon = "ESPERAR", f"ESPERAR · {symbol}", "⏳"
    else:
        level, title, icon = "NO_OPERAR", f"NO OPERAR · {symbol}", "⛔"
    return {
        "level": level,
        "title": title,
        "body": f"{strategy}. {summary.get('next_requirement', '')}".strip(),
        "icon": icon,
    }


def _desktop_notification_controls() -> None:
    """Permite habilitar notificaciones del navegador sin audio."""
    st.html(
        """
        <button id="jj-enable" style="padding:8px 12px;border:1px solid #bbb;"
                >Activar notificaciones de escritorio</button>
        <span id="jj-status" style="margin-left:8px;font-family:sans-serif;"></span>
        <script>
        const button = document.getElementById('jj-enable');
        const status = document.getElementById('jj-status');
        function refresh() {
          if (!("Notification" in window)) {
            status.textContent = "No disponibles en este navegador";
            button.disabled = true;
          } else {
            status.textContent = Notification.permission === "granted"
              ? "Activadas" : Notification.permission === "denied"
              ? "Bloqueadas por el navegador" : "Pendientes";
          }
        }
        button.addEventListener('click', async () => {
          await Notification.requestPermission();
          refresh();
        });
        refresh();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _send_desktop_notification(payload: Mapping[str, str]) -> None:
    """Emite una notificacion silenciosa si el usuario dio permiso."""
    title = json.dumps(str(payload.get("title", "JJTrade AI"))).replace("</", "<\\/")
    body = json.dumps(str(payload.get("body", ""))).replace("</", "<\\/")
    st.html(
        f"""
        <script>
        if (("Notification" in window) && Notification.permission === "granted") {{
          new Notification({title}, {{body: {body}, silent: true, tag: "jjtrade-alert"}});
        }}
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _render_alert_banner(payload: Mapping[str, str]) -> None:
    """Diferencia visualmente CALL, PUT, espera y bloqueo."""
    message = f"{payload['icon']} {payload['level']} · {payload['body']}"
    if payload["level"] == "CALL":
        st.success(message)
    elif payload["level"] == "PUT":
        st.warning(message)
    elif payload["level"] == "ESPERAR":
        st.info(message)
    else:
        st.error(message)


def _feed_comparison_summary(payload: object) -> dict[str, object]:
    """Resume la comparacion de feeds sin convertirla en permiso operativo."""
    if not isinstance(payload, Mapping):
        return {"status": "PENDIENTE", "label": "NO EJECUTADA", "rows": []}
    results = payload.get("results", ())
    if not isinstance(results, list) or not results:
        return {
            "status": "PENDIENTE",
            "label": "SIN RESULTADOS",
            "rows": [],
            "evaluated_at": payload.get("evaluated_at", ""),
        }
    rows = []
    total_differences = 0
    replay_evaluated = 0
    replay_divergent = 0
    replay_episodes = 0
    for item in results:
        if not isinstance(item, Mapping):
            continue
        count = int(item.get("detector_difference_count", 0) or 0)
        total_differences += count
        replay = item.get("historical_replay", {})
        if not isinstance(replay, Mapping):
            replay = {}
        evaluated = int(replay.get("evaluated_close_count", 0) or 0)
        divergent = int(replay.get("divergent_close_count", 0) or 0)
        replay_evaluated += evaluated
        replay_divergent += divergent
        episodes = int(replay.get("unique_divergence_episode_count", 0) or 0)
        replay_episodes += episodes
        rows.append({
            "Compania": str(item.get("symbol", "N/D")),
            "Resultado": "COINCIDE" if count == 0 else "DIVERGE",
            "Detectores diferentes": count,
            "Cierres historicos": evaluated,
            "Cierres divergentes": divergent,
            "Episodios unicos": episodes,
            "Divergencia historica %": float(replay.get("divergence_rate_pct", 0.0) or 0.0),
        })
    has_divergence = total_differences > 0 or replay_divergent > 0
    if replay_evaluated:
        label = "HISTORIAL RECIENTE COINCIDE" if not has_divergence else "DIVERGENCIA HISTORICA"
    else:
        label = "ULTIMA EVALUACION COINCIDE" if not has_divergence else "REQUIERE REVISION"
    return {
        "status": "COINCIDE" if rows and not has_divergence else "DIVERGE",
        "label": label,
        "rows": rows,
        "evaluated_at": payload.get("evaluated_at", ""),
        "detector_difference_count": total_differences,
        "historical_evaluated_close_count": replay_evaluated,
        "historical_divergent_close_count": replay_divergent,
        "historical_unique_episode_count": replay_episodes,
    }


def _load_feed_comparison(path: str | Path = "exports/feed_comparison.json") -> dict[str, object]:
    """Lee el ultimo reporte local; un archivo ausente queda pendiente."""
    target = Path(path)
    if not target.exists():
        return _feed_comparison_summary(None)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "ERROR", "label": "REPORTE INVALIDO", "rows": []}
    return _feed_comparison_summary(payload)


def _render_bollinger_study() -> None:
    from bollinger_phone_worker import STRATEGY_VERSION
    st.subheader("Bollinger con volatilidad · ¿Continúa en la dirección de salida?")
    st.caption("Estudio exclusivo de 15 minutos. Superior: continuación al alza; inferior: continuación a la baja. No envía órdenes.")
    path = Path(__file__).resolve().parent / "exports" / "bollinger_study" / "latest.json"
    try:
        study = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.info("Se está preparando el primer estudio de esta estrategia.")
        return
    if study.get("version") != STRATEGY_VERSION:
        st.info("Recalculando el estudio para excluir aperturas que saltan fuera de Bollinger. Los resultados anteriores no se mezclan con esta regla.")
        return
    st.caption("Actualizado: " + _market_event_local_time(study.get("generated_at")) + " · últimos 30 días de datos locales.")
    if datetime.now(timezone.utc) - datetime.fromisoformat(study["generated_at"]) > timedelta(minutes=10):
        st.warning("El estudio lleva más de diez minutos sin actualizarse.")
    origin_label = st.radio("Qué resultados quieres revisar", ["Detecciones en vivo", "Reconstrucción histórica"], horizontal=True, key="bollinger_study_origin")
    origin = "RECONSTRUIDA" if origin_label == "Reconstrucción histórica" else "EN_VIVO"
    st.caption("La reconstrucción reproduce cada minuto con barras guardadas. No demuestra que esos avisos se hayan enviado ni reproduce demoras o revisiones del proveedor." if origin == "RECONSTRUIDA" else "Solo detecciones guardadas por el radar desde que se habilitó este registro, con su hora real de observación.")
    horizon = st.selectbox("¿Cuántos minutos después de la detección?", [5, 15, 30, 60], index=1, key="bollinger_study_horizon")
    rows = [r for r in study["summary"] if r["origin"] == origin and r["horizon"] == horizon]
    if rows:
        st.dataframe(pd.DataFrame([
            {"Compañía": r["symbol"], "Fuente": f"{r['provider']} / {r['feed']}",
             "Salida": "Superior · alza" if r["side"] == "SUPERIOR" else "Inferior · baja",
             "Detecciones": r["detected"], "Casos sin solapamiento": r["sample"], "Sesiones": r["sessions"],
             "Continuó a favor": r["positive"], "Terminó en contra": r["negative"], "Sin cambio": r["unchanged"],
             "% a favor": r["positive_pct"], "Movimiento medio a favor %": r["average_return_pct"],
             "Evidencia": "Faltan casos o sesiones" if r["status"] == "MUESTRA_INSUFICIENTE" else "Historial descriptivo · sin certeza calibrada"}
            for r in rows]), width="stretch", hide_index=True)
    else:
        st.info("Todavía no hay detecciones registradas para este grupo.")
    st.caption("Positivo significa que el precio terminó a favor respecto al precio observado, aunque el avance sea pequeño. No significa que un CALL o PUT ganara dinero ni que alcanzara el 20%.")
    observations = [r for r in study["observations"] if r["origin"] == origin and r["horizon"] == horizon]
    totals = st.columns(4)
    totals[0].metric("Salidas registradas", len(observations))
    totals[1].metric("Recorridos evaluados", sum(r["status"] == "EVALUADA" for r in observations))
    totals[2].metric("Esperando recorrido", sum(r["status"] == "PENDIENTE" for r in observations))
    totals[3].metric("Sin datos o sin tiempo antes del cierre", sum(r["status"] not in {"EVALUADA", "PENDIENTE"} for r in observations))
    st.caption("Estos totales cuentan detecciones individuales. La tabla de porcentajes excluye ventanas solapadas; sus cantidades pueden ser menores.")
    with st.expander("Ver movimientos individuales y casos pendientes"):
        if observations:
            st.dataframe(pd.DataFrame([
                {"Compañía": r["symbol"], "Salida": r["side"], "Observada": _market_event_local_time(r["detected_at"]),
                 "Precio observado": r["price"], "Estado": r["status"], "Resultado": r.get("result", "Pendiente / no evaluable"),
                 "Movimiento a favor %": r.get("directional_return_pct"), "Máximo avance a favor %": r.get("favorable_excursion_pct"),
                 "Máximo recorrido en contra %": r.get("adverse_excursion_pct")}
                for r in sorted(observations, key=lambda r:r["detected_at"], reverse=True)[:100]]), width="stretch", hide_index=True)
        st.caption("Minutos faltantes, recorridos pendientes y ventanas que exceden el cierre se separan de positivos y negativos. No se rellenan datos ausentes.")
    st.info("Las reglas permanecen fijas mientras reunimos evidencia. Una tasa histórica alta no garantiza el siguiente movimiento; este estudio no habilita compras automáticas.")


@st.fragment(run_every="30s")
def _render_strategy_research() -> None:
    _render_bollinger_study()


def _render_all_strategy_research() -> None:
    report_path = Path(__file__).resolve().parent / "exports" / "strategy_research" / "latest.json"
    st.subheader("Seguimiento de resultados de estrategias")
    with st.container():
        if not report_path.is_file():
            st.info("El seguimiento todavía no ha generado su primer informe.")
            return
        try:
            research = json.loads(report_path.read_text(encoding="utf-8"))
            generated_at = datetime.fromisoformat(research["generated_at"])
        except (OSError, ValueError, KeyError):
            st.info("El informe de seguimiento todavía no está disponible.")
            return
        st.caption(
            "Actualizado: " + generated_at.astimezone(ZoneInfo("America/New_York")).strftime("%d/%m/%Y %I:%M %p ET")
            + ". Resultados del subyacente sin costos; las tasas históricas no son probabilidades de la próxima señal."
        )
        if datetime.now(timezone.utc) - generated_at > timedelta(minutes=10):
            st.warning("El informe lleva más de 10 minutos sin actualizarse.")
        coverage = research.get("detector_coverage", [])
        gap_audit = research.get("minute_gap_audit", {})
        if gap_audit:
            st.markdown("**Cobertura de minutos por sesión**")
            st.caption("Compara minutos cerrados con el calendario guardado, incluidos cierres anticipados. Un minuto sin barra no demuestra pérdida de datos ni ausencia de operaciones.")
            gaps = gap_audit.get("rows", [])
            st.dataframe(pd.DataFrame([
                {"Símbolo": item["symbol"], "Feed": item["feed"], "Sesión": item["session_date"],
                 "Minutos revisados": item["expected_minutes"], "Barras locales": item["observed_minutes"],
                 "Minutos sin barra": item["missing_minutes"], "Cobertura %": item["coverage_pct"], "Estado": item["status"]}
                for item in gaps
            ]), width="stretch", hide_index=True)
            recoverable = {f"{item['symbol']} · {item['session_date']} · {item['feed']} · {item['missing_minutes']} minutos sin barra": item
                           for item in gaps if item["missing_minutes"] > 0 and item["provider"] == "ALPACA"}
            if recoverable:
                with st.form("recover_minute_gaps"):
                    selected_gap = st.selectbox("Sesión a consultar en Alpaca", list(recoverable))
                    recovery_key = st.text_input("Alpaca API key para recuperación", type="password")
                    recovery_secret = st.text_input("Alpaca API secret para recuperación", type="password")
                    st.caption("Consulta una sesión con el mismo feed e inserta únicamente barras faltantes. Las credenciales no se guardan en archivos.")
                    recover_requested = st.form_submit_button("Consultar y recuperar barras disponibles")
                if recover_requested:
                    if not recovery_key.strip() or not recovery_secret.strip():
                        st.info("Introduce las credenciales en estos campos para consultar el proveedor.")
                    else:
                        try:
                            audit = recoverable[selected_gap]
                            provider = AlpacaMarketDataProvider(AlpacaMarketConfig(recovery_key.strip(), recovery_secret.strip(), feed=audit["feed"]))
                            recovered = recover_session_gaps(MarketBarStore(), provider, audit=audit, provider_name="ALPACA", feed=audit["feed"])
                        except Exception as error:
                            st.error("No se completó la recuperación: " + sanitize_diagnostic_detail(str(error)))
                        else:
                            st.success(f"Se insertaron {recovered['inserted']} barras. Quedan {recovered['remaining']} minutos sin barra en ese período.")
                            st.caption("El informe reflejará la nueva cobertura en su próxima actualización. Si quedan minutos ausentes, la causa continúa sin determinar.")
        if coverage:
            st.markdown("**Cobertura de las ocho estrategias y Expuesto Bollinger**")
            st.dataframe(pd.DataFrame([
                {
                    "Estrategia": item["name"], "Escaneos evaluados": item["evaluated_scans"],
                    "Detectados": item["detected_scans"], "Confirmados": item["confirmed_scans"],
                    "Omitidos": item["skipped_scans"], "Errores": item["error_scans"],
                    "Último escaneo por símbolo": ", ".join(f"{status}: {count}" for status, count in item["latest_status_counts"].items()),
                    "Pendientes frecuentes en detecciones": "; ".join(f"{blocker['criterion']} ({blocker['status']})" for blocker in item["blockers"][:2]),
                    "Datos o revisiones faltantes": "; ".join(f"{requirement['name']} ({requirement['status']})" for requirement in item.get("unavailable_requirements", [])[:2]),
                }
                for item in coverage
            ]), width="stretch", hide_index=True)
            st.caption("Los escaneos incluyen todos los registros históricos. Sin detección significa que el detector corrió y no encontró su configuración; una omisión o un error se muestran por separado.")
        cohort = st.radio("Resultados posteriores", ["Estrategias confirmadas", "Candidatas pendientes"],
                          horizontal=True, key="research_cohort")
        candidate_mode = cohort == "Candidatas pendientes"
        entry_mode = st.radio("Precio de referencia", ["Posterior a la emisión", "Cierre de la vela de señal"],
                              horizontal=True, key="research_entry_basis") == "Posterior a la emisión"
        if entry_mode:
            st.caption("Estudio del subyacente: apertura del minuto posterior a la disponibilidad de la señal y cierre tras el horizonte elegido. Exige todas las barras del recorrido; no representa una ejecución real ni incluye costos.")
        if candidate_mode:
            st.info("Observaciones de configuraciones detectadas sin todos sus requisitos. Sirven para investigar; conservan su estado pendiente y no alteran las señales.")
        horizon = st.selectbox("Movimiento posterior (minutos)", [15, 30, 60], index=2, key="research_horizon")
        table = []
        research_key = ("entry_candidate_strategies" if candidate_mode else "entry_strategies") if entry_mode else ("candidate_strategies" if candidate_mode else "strategies")
        for row in research.get(research_key, []):
            if row["horizon_minutes"] != horizon:
                continue
            stats = row["non_overlapping"]
            table.append({
                "Estrategia": row["strategy_id"], "Dirección": row["bias"],
                "Versión": row["methodology_version"], "Muestra sin solapamiento": stats["sample_size"],
                "Sesiones": stats["session_count"], "Positivos %": stats["positive_rate_pct"],
                "Retorno medio %": stats["average_directional_return_pct"],
                "Período anterior positivos %": row["prior_period"]["positive_rate_pct"],
                "Período reciente positivos %": row["recent_period"]["positive_rate_pct"],
                "Sesiones recientes": row["recent_period"]["session_count"],
            })
        if table:
            st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
        else:
            st.info("Todavía no hay resultados para este horizonte.")
        st.caption("Positivo: movimiento a favor mayor que cero. Las ventanas superpuestas del mismo símbolo se excluyen; distintos símbolos todavía pueden estar correlacionados.")
        if entry_mode:
            cohort_key = "CANDIDATAS" if candidate_mode else "CONFIRMADAS"
            entry_states = [item for item in research.get("entry_status_counts", []) if item["cohort"] == cohort_key]
            st.caption("Estado de las observaciones, sumando 15, 30 y 60 minutos: " + "; ".join(f"{item['status']}: {item['count']}" for item in entry_states))
            observations = [item for item in research.get("entry_observations", {}).get(cohort_key, []) if item["horizon_minutes"] == horizon]
            if observations:
                st.markdown("**Entradas y salidas estudiadas más recientes**")
                st.dataframe(pd.DataFrame([
                    {"Alerta": item["alert_id"], "Símbolo": item["symbol"], "Estrategia": item["strategy_id"],
                     "Señal disponible ET": datetime.fromisoformat(item["signal_available_at"]).astimezone(ZoneInfo("America/New_York")).strftime("%d/%m %H:%M:%S"),
                     "Entrada ET": datetime.fromisoformat(item["entry_timestamp"]).astimezone(ZoneInfo("America/New_York")).strftime("%d/%m %H:%M"),
                     "Precio entrada": item["entry_price"],
                     "Salida ET": datetime.fromisoformat(item["exit_timestamp"]).astimezone(ZoneInfo("America/New_York")).strftime("%d/%m %H:%M"),
                     "Precio salida": item["exit_price"], "Movimiento a favor %": item["directional_return_pct"]}
                    for item in sorted(observations, key=lambda item: item["entry_timestamp"], reverse=True)[:20]
                ]), width="stretch", hide_index=True)
        experiments = [item for item in research.get("filter_experiments", [])
                       if not entry_mode and item["horizon_minutes"] == horizon
                       and item["cohort"] == ("CANDIDATAS" if candidate_mode else "CONFIRMADAS")]
        if experiments:
            st.markdown("**Pruebas de posibles mejoras**")
            st.caption("Las hipótesis y su evaluación inicial quedan fijadas. La prueba futura usa sesiones posteriores al registro; mejora descriptiva no significa precisión demostrada.")
            st.dataframe(pd.DataFrame([
                {
                    "Estrategia": item["strategy_id"], "Filtro en prueba": item["name"],
                    "Versión": item["methodology_version"],
                    "Muestra histórica filtrada": item["historical_test"]["filtered"]["sample_size"],
                    "Sesiones históricas filtradas": item["historical_test"]["filtered"]["session_count"],
                    "Prueba histórica": item["historical_test"]["status"],
                    "Cambio positivos (puntos)": item["historical_test"]["positive_rate_delta_points"],
                    "Cambio retorno medio %": item["historical_test"]["average_return_delta_pct"],
                    "Oportunidades retenidas %": item["historical_test"]["retained_pct"],
                    "Muestra futura filtrada": item["forward_test"]["filtered"]["sample_size"],
                    "Prueba futura": item["forward_test"]["status"],
                }
                for item in experiments
            ]), width="stretch", hide_index=True)
        st.download_button("Descargar investigación JSON", data=json.dumps(research, ensure_ascii=False, indent=2),
                           file_name="investigacion_estrategias.json", mime="application/json", key="download_strategy_research")


def _render_scanner_controls(process_status: Mapping[str, object]) -> None:
    """Controla el buscador desde la pantalla principal."""
    with st.expander(
        "Iniciar o detener buscador",
        expanded=not bool(process_status.get("active")),
    ):
        scanner_active = bool(process_status.get("active"))
        configured_symbols = load_watchlist()["symbols"]
        configured_text = ",".join(configured_symbols)
        running_health = ServiceHealthRepository().get("live_strategy_scanner") if scanner_active else {}
        running_symbols = set((running_health or {}).get("symbols", []))
        pending_symbols = sorted(set(configured_symbols) - running_symbols) if scanner_active else []
        if pending_symbols:
            st.warning("Agregados a la lista, pendientes de reiniciar el buscador: " + ", ".join(pending_symbols))
            st.caption("Todavía no reciben datos ni avisos. Para aplicarlos, detén el buscador y vuelve a iniciarlo con la lista guardada y tus credenciales de Alpaca.")
        existing_text = st.session_state.get("control_scanner_symbols")
        if not scanner_active and existing_text and set(existing_text.split(",")).issubset(set(configured_symbols)):
            st.session_state["control_scanner_symbols"] = configured_text
        scanner_symbols = st.text_input(
            "Compañías a vigilar", value=configured_text,
            key="control_scanner_symbols", disabled=scanner_active,
        )
        scanner_days = st.number_input(
            "Días de historial", min_value=1, value=365, step=1,
            key="control_scanner_days", disabled=scanner_active,
        )
        process_key = os.environ.get("ALPACA_API_KEY", "").strip()
        process_secret = os.environ.get("ALPACA_API_SECRET", "").strip()
        if scanner_active:
            st.success(
                f"Buscador activo para todos los dispositivos (PID {process_status.get('pid')})."
            )
            alpaca_key = ""
            alpaca_secret = ""
        elif process_key and process_secret:
            alpaca_key = process_key
            alpaca_secret = process_secret
        else:
            st.info(
                "Para activar el buscador tras reiniciar la PC, introduce tus "
                "credenciales de datos Alpaca. Se pasan al scanner y no se guardan en disco."
            )
            alpaca_key = st.text_input(
                "Alpaca API key", type="password", key="control_alpaca_api_key",
            ).strip()
            alpaca_secret = st.text_input(
                "Alpaca API secret", type="password", key="control_alpaca_api_secret",
            ).strip()
        credentials_ready = scanner_active or bool(alpaca_key and alpaca_secret)
        action_columns = st.columns(2)
        if action_columns[0].button(
            "Buscador activo" if scanner_active else "Encontrar Movimientos",
            disabled=scanner_active or not credentials_ready,
            key="control_start_scanner",
        ):
            try:
                arguments = build_scanner_arguments(
                    symbols=scanner_symbols, days=int(scanner_days),
                    database=AlertRepository().database_path,
                    option_policy=None,
                )
                result = start_scanner(
                    arguments,
                    environment={
                        "ALPACA_API_KEY": alpaca_key,
                        "ALPACA_API_SECRET": alpaca_secret,
                        "ALPACA_DATA_FEED": os.environ.get("ALPACA_DATA_FEED", "iex"),
                    },
                )
            except (ValueError, RuntimeError, OSError) as error:
                st.error(str(error))
            else:
                st.success(f"Buscador iniciando con PID {result['pid']}.")
        if action_columns[1].button(
            "Detener Buscador", disabled=not bool(process_status.get("active")),
            key="control_stop_scanner",
        ):
            try:
                result = stop_scanner()
            except (RuntimeError, OSError) as error:
                st.error(str(error))
            else:
                st.success(f"Parada solicitada al PID {result['scanner_pid']}.")


def _render_price_ranges() -> None:
    """Compara la referencia de opciones con el rango dinámico de la acción."""
    option_ranges = load_option_price_ranges()
    with st.expander("Rangos de precios actuales", expanded=False):
        symbol = st.selectbox(
            "Selecciona una compañía",
            tuple(option_ranges),
            key="price_range_symbol",
            format_func=lambda ticker: (
                f"{ticker} · {option_ranges[ticker]['name']}"
            ),
        )
        reference = option_ranges[symbol]
        st.markdown("#### Referencia de precios de opciones")
        st.markdown(
            f"""<div class="jj-range-grid jj-range-reference">
            <div class="jj-range-card featured"><span>Rango óptimo</span>
            <b>${reference['optimal_low']:,.0f} – ${reference['optimal_high']:,.0f}</b></div>
            <div class="jj-range-card"><span>Mínimo y máximo</span>
            <b>${reference['minimum']:,.0f} – ${reference['maximum']:,.0f}</b></div>
            <div class="jj-range-card"><span>Bloque</span><b>{html.escape(reference['block'])}</b></div>
            <div class="jj-range-card"><span>Fecha del análisis</span><b>{reference['analysis_date']}</b></div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.caption(
            f"{reference['sector']} · {reference['industry']} · "
            f"{reference['exchange']}. Valores suministrados en el listado; "
            "se mantienen separados del precio de la acción."
        )
        st.markdown("#### Rango dinámico de la acción")
        store = MarketBarStore(AlertRepository().database_path)
        bars = pd.DataFrame()
        for feed in ("iex", "sip", "delayed_sip"):
            candidate = store.load_frame(symbol=symbol, provider="ALPACA", feed=feed)
            if not candidate.empty:
                bars = candidate
                break
        summary = calculate_price_range(
            bars,
            current_market_date=datetime.now(ZoneInfo("America/New_York")).date(),
        )
        if summary is None:
            st.info(
                "Todavía no hay historial suficiente para calcular este rango. "
                "Inicia el buscador para actualizar los datos."
            )
            return
        st.markdown(
            f"""<div class="jj-range-grid">
            <div class="jj-range-card"><span>Precio actual</span><b>${summary['current']:,.2f}</b></div>
            <div class="jj-range-card featured"><span>Rango estimado</span><b>${summary['expected_low']:,.2f} – ${summary['expected_high']:,.2f}</b></div>
            <div class="jj-range-card"><span>Soporte 20 sesiones</span><b>${summary['support']:,.2f}</b></div>
            <div class="jj-range-card"><span>Resistencia 20 sesiones</span><b>${summary['resistance']:,.2f}</b></div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.caption(
            f"{summary['position']} · ATR(14): ${summary['atr']:,.2f} · "
            f"Actualizado: {_market_event_local_time(summary['as_of'])}. "
            "Rango estadístico informativo; no garantiza el movimiento futuro."
        )


@st.cache_data(show_spinner=False)
def _dashboard_background_data_uri() -> str:
    """Incrusta el fondo para que funcione igual en localhost y Tailscale."""
    image_path = Path(__file__).resolve().parent / "static" / "trading-bull-candles-bg.png"
    if not image_path.exists():
        return ""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _bollinger_state_is_current(item, *, now, market_open):
    stamp = _parse_alert_time(item.get("source_timestamp"))
    return bool(market_open and stamp is not None and timedelta(minutes=1) <= now-stamp <= timedelta(minutes=3))


@st.fragment(run_every="15s")
def render_bollinger_dashboard() -> None:
    from bollinger_phone_worker import STRATEGY_VERSION
    st.subheader("Salida de Bollinger con volatilidad · 15 minutos")
    st.caption("Un solo enfoque: detectar el comienzo de una salida y medir si el precio continúa en esa dirección. Avisos tempranos, sin órdenes automáticas.")
    now = datetime.now(timezone.utc)
    database = AlertRepository().database_path
    session = MarketSessionRepository(database).session(now.astimezone(ZoneInfo("America/New_York")).date())
    market_open = session is not None and session.opens_at <= now < session.closes_at
    process_status = read_instance_status("exports/live_scanner.lock")
    configured = load_watchlist()["symbols"]
    columns = st.columns(3)
    columns[0].metric("Estrategia", "Bollinger 15m")
    columns[1].metric("Símbolos configurados", len(configured))
    columns[2].metric("Sesión regular", "Abierta" if market_open else "Cerrada / sin calendario")
    _render_scanner_controls(process_status)
    st.caption("Salida superior → movimiento alcista / CALL. Salida inferior → movimiento bajista / PUT. La vela debe abrir dentro de las bandas anteriores y después salir con volatilidad. Una apertura ya expuesta queda excluida.")
    states, events = [], []
    try:
        with closing(sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=ro", uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "bollinger_radar_state" in tables:
                states = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM bollinger_radar_state")]
            if "bollinger_live_events" in tables:
                events = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM bollinger_live_events ORDER BY detected_at DESC LIMIT 50")]
    except (sqlite3.Error, OSError, ValueError):
        st.warning("No se pudieron consultar los estados del radar. Revisa el buscador.")
    current = [item for item in states if item.get("version") == STRATEGY_VERSION and _bollinger_state_is_current(item, now=now, market_open=market_open)]
    events = [event for event in events if event.get("version") == STRATEGY_VERSION]
    detected = [item for item in current if item.get("signal")]
    st.markdown("### Qué está ocurriendo ahora")
    if not market_open:
        st.info("El radar espera la sesión regular. Las detecciones anteriores son historial y no entradas vigentes.")
    elif not current:
        st.warning("Esperando datos recientes del radar de Bollinger. Comprueba que el buscador y el servicio de avisos estén activos.")
    elif not detected:
        st.info(f"Se están revisando {len(current)} símbolos con datos recientes. Todavía no hay una salida nueva que cumpla la regla.")
    for item in detected:
        signal = item["signal"]
        direction = "ALCISTA · CALL" if signal["side"] == "SUPERIOR" else "BAJISTA · PUT"
        with st.container(border=True):
            st.markdown(f"**{item['symbol']} · {direction} · Salida en formación**")
            st.write(f"Disipador {signal['side'].lower()} · Precio observado: {signal['price']:.2f}")
            if signal.get('ma_context'):
                from bollinger_ma_context import context_text
                st.caption(context_text(signal['ma_context']))
                reference_levels=signal['ma_context'].get('price_levels',{}).get('levels',[])
                if reference_levels:
                    with st.expander('Cierre anterior y máximo del historial'):
                        st.dataframe(pd.DataFrame([{'Nivel':level['label'],'Precio':level['value'],
                            'Distancia %':level['distance_pct'],'Delante del movimiento':level['ahead'],
                            'Papel posible':level['role'],'Sesión de referencia':level['source_date'],
                            'Cobertura':level['quality']} for level in reference_levels]),hide_index=True,width='stretch')
                        st.caption('El máximo disponible no confirma el all-time high real. Los niveles son referencias posibles, no garantizan un freno al precio.')
                with st.expander('Ver medias, cruces y cierres de Hora'):
                    context = signal['ma_context']
                    pairs = []
                    for frame in context.get('frames', []):
                        for pair in frame.get('pairs', []):
                            pairs.append({'Temporalidad':frame['timeframe'], 'Par':'/'.join(map(str,pair['periods'])),
                                          'Orden':pair['direction'], 'Sesiones desde cruce':pair.get('sessions_since_cross'),
                                          'Estado':pair.get('phase'), 'Separación %':pair.get('separation_pct'),
                                          'Cruces últimas 20 velas':pair.get('crosses_last_20')})
                    if pairs:
                        st.dataframe(pd.DataFrame(pairs), hide_index=True, width='stretch')
                    levels = [{'Temporalidad':level['timeframe'], 'SMA':level['period'], 'Valor':level['value'],
                               'Distancia %':level['distance_pct'], 'Papel':level.get('role'),
                               'Delante del movimiento':level['ahead'], 'Último cierre de Hora':level.get('hour_confirmation'),
                               'Hora de la observación':level.get('confirmation_hour_at'),
                               'Contactos separados últimas 20 horas':level.get('touch_episodes_last_20_hours')}
                              for level in context.get('levels', [])]
                    if levels:
                        st.dataframe(pd.DataFrame(levels), hide_index=True, width='stretch')
                    st.caption('Un cierre observado de Hora corresponde a la hora indicada; no confirma la salida actual de 15 minutos. Los contactos y la separación se miden, pero todavía no tienen umbrales validados para bloquear avisos.')
            st.caption("Barra: " + _market_event_local_time(item["source_timestamp"]) + ". Revisa el gráfico: esta salida puede revertirse.")
    with st.expander("Compañías y estado del radar"):
        latest = {item["symbol"]: item for item in states}
        fresh = {item["symbol"] for item in current}
        st.dataframe(pd.DataFrame([
            {"Símbolo": symbol, "Estado": "Salida detectada" if symbol in fresh and latest[symbol].get("signal") else "Vigilando · sin salida nueva" if symbol in fresh else "Esperando sesión" if not market_open else "Sin datos recientes / pendiente de activar",
             "Última barra": _market_event_local_time(latest[symbol]["source_timestamp"]) if symbol in latest else "Sin registro"}
            for symbol in configured]), width="stretch", hide_index=True)
    with st.expander("Últimas detecciones guardadas · historial"):
        if events:
            st.dataframe(pd.DataFrame([
                {"Compañía": e["symbol"], "Salida": e["side"], "Detectada": _market_event_local_time(e["detected_at"]),
                 "Precio observado": e["price"], "Estado": "Observación guardada · consultar resultado"}
                for e in events]), width="stretch", hide_index=True)
        else:
            st.caption("Todavía no hay detecciones en vivo guardadas. La reconstrucción histórica está en Seguimiento de resultados.")
    st.markdown("### Cómo comprobamos su efectividad")
    st.write("En Seguimiento de resultados verás si cada salida continuó a favor o terminó en contra a 5, 15, 30 y 60 minutos. Los casos pendientes y los datos incompletos se muestran separados.")
    st.caption("La observación continúa aunque pauses Telegram. El PC, el buscador y el radar deben permanecer encendidos.")


@st.fragment(run_every="15s")
def render_operational_dashboard() -> None:
    """Vista principal: estado de la app y oportunidades que requieren accion."""
    st.markdown(
        """
        <style>
        html, body, [class*="css"] {font-family:Inter,"Segoe UI",Roboto,Arial,sans-serif}
        .stApp {background:
          radial-gradient(circle at 88% 3%,rgba(59,130,246,.12),transparent 25%),
          #08111f;color:#e8eef7}
        [data-testid="stAppViewContainer"],[data-testid="stMain"] {background:transparent}
        header[data-testid="stHeader"] {background:rgba(8,17,31,.92);backdrop-filter:blur(12px)}
        [data-testid="stSidebar"] {background:#0b1626;border-right:1px solid #20304a}
        h1,h2,h3,h4 {color:#f4f7fb;letter-spacing:-.022em;font-weight:650}
        p,[data-testid="stCaptionContainer"] {color:#a9b7ca}
        div[data-testid="stTabs"] button {font-weight:600;color:#91a1b8;padding:.7rem .85rem}
        div[data-testid="stTabs"] button[aria-selected="true"] {color:#78a7ff}
        div[data-baseweb="tab-highlight"] {background-color:#4f83ff!important}
        div[data-testid="stExpander"] {background:#101d30;border:1px solid #263a57;border-radius:12px;
          box-shadow:none;overflow:hidden}
        div[data-testid="stExpander"] details,div[data-testid="stExpander"] summary {background:#101d30;color:#e8eef7}
        div[data-testid="stExpanderDetails"] {background:#101d30}
        div[data-baseweb="input"] {background:#16263d!important;border-color:#304663!important}
        div[data-baseweb="input"] input {background:#16263d!important;color:#f1f5f9!important;-webkit-text-fill-color:#f1f5f9!important}
        div[data-baseweb="input"] button {background:#20314a!important;color:#c2cede!important}
        div[data-baseweb="select"] > div {background:#16263d!important;border-color:#304663!important;color:#f1f5f9!important}
        label[data-testid="stWidgetLabel"] p,div[data-testid="stExpander"] p {color:#c2cede!important}
        div[data-testid="stAlert"] {background:#111f33;color:#dbe7f5;border:1px solid #2a405f;
          border-radius:11px;box-shadow:none}
        div[data-testid="stAlert"] p {color:#dbe7f5!important}
        div.stButton > button {border:0;border-radius:10px;font-weight:700;min-height:2.65rem;
          background:linear-gradient(135deg,#172554,#2563eb);color:#fff!important;
          box-shadow:0 7px 16px rgba(37,99,235,.22);transition:transform .15s ease,box-shadow .15s ease}
        div.stButton > button p {color:#fff!important;font-weight:750}
        div.stButton > button:hover {color:#fff;border:0;transform:translateY(-1px);
          background:linear-gradient(135deg,#1e3a8a,#3b82f6);
          box-shadow:0 10px 22px rgba(37,99,235,.3)}
        div.stButton > button:disabled {background:#1a2940!important;color:#72839a!important;
          opacity:1;border:1px solid #2a3c57;box-shadow:none;transform:none}
        div.stButton > button:disabled p {color:#72839a!important}
        .jj-hero {position:relative;overflow:hidden;padding:1.75rem 1.8rem;border:1px solid #294266;
          border-radius:16px;background-image:linear-gradient(90deg,rgba(8,17,31,.98) 0%,rgba(8,17,31,.90) 40%,rgba(8,17,31,.28) 100%),
          url('/app/static/trading-bull-candles-bg.png');background-size:cover,auto 155%;
          background-position:center,right center;background-repeat:no-repeat;
          margin-bottom:1.2rem;box-shadow:0 18px 42px rgba(0,0,0,.22)}
        .jj-hero:after {content:"";position:absolute;width:240px;height:240px;border-radius:50%;
          right:-70px;top:-120px;display:none}
        .jj-eyebrow {position:relative;z-index:1;font-size:.7rem;font-weight:800;letter-spacing:.17em;color:#93c5fd}
        .jj-title {position:relative;z-index:1;font-size:1.85rem;font-weight:800;color:#fff;margin:.35rem 0;
          letter-spacing:-.025em}
        .jj-subtitle {position:relative;z-index:1;color:#cbd5e1;font-size:.94rem;max-width:760px}
        .jj-status-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.8rem;margin:1rem 0}
        .jj-status-card {background:#101d30;border:1px solid #263a57;border-radius:12px;
          padding:.85rem 1rem;box-shadow:none}
        .jj-status-label {font-size:.69rem;font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:#8393aa}
        .jj-status-value {font-size:1.15rem;font-weight:700;color:#f1f5f9;margin-top:.18rem;line-height:1.2}
        .jj-status-value.active {color:#34d399}.jj-status-value.stopped {color:#fb7185}
        .jj-range-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.65rem;margin:.75rem 0}
        .jj-range-card {background:#15243a;border:1px solid #2a405f;border-radius:10px;padding:.75rem .8rem}
        .jj-range-card span {display:block;color:#8999af;font-size:.7rem;font-weight:700;margin-bottom:.25rem}
        .jj-range-card b {display:block;color:#edf3fb;font-size:1rem}
        .jj-range-card.featured {background:#18325c;border-color:#3764a7}
        .jj-range-card.featured b {color:#8cb4ff}
        .jj-card {padding:1.05rem 1.15rem;border:1px solid #2a405f;border-left:4px solid #64748b;
          border-radius:11px;background:#121f33;margin:.7rem 0;box-shadow:none;
          transition:transform .15s ease,border-color .15s ease}
        .jj-card:hover {transform:translateY(-1px);border-color:#42618b}
        .jj-card.call {border-left-color:#34d399;background:#112a2b}
        .jj-card.put {border-left-color:#fb7185;background:#2b1c2a}
        .jj-card.high {border-left-color:#34d399;background:linear-gradient(135deg,#112a2b,#10302c)}
        .jj-card.medium {border-left-color:#fbbf24;background:linear-gradient(135deg,#2b2517,#1a2837)}
        .jj-card.low {border-left-color:#fb7185;background:linear-gradient(135deg,#2b1c2a,#1b2441)}
        .jj-card.featured {box-shadow:0 0 0 1px rgba(96,165,250,.45),0 12px 24px rgba(96,165,250,.12);border-color:#5bb7ff}
        .jj-card-title {font-size:1.03rem;font-weight:680;color:#edf3fb}
        .jj-badge {display:inline-block;padding:.22rem .55rem;border-radius:999px;background:#20314a;
          font-size:.7rem;font-weight:750;margin-left:.35rem;color:#b5c2d3;letter-spacing:.02em}
        .jj-badge.call {background:#123b35;color:#6ee7b7}.jj-badge.put {background:#442230;color:#fda4af}
        .jj-badge.high {background:#123b35;color:#6ee7b7}.jj-badge.medium {background:#3d3316;color:#f8d977}
        .jj-badge.low {background:#45212b;color:#fda4af}.jj-badge.none {background:#20314a;color:#dfeaf8}
        .jj-top-signal {display:inline-block;padding:.18rem .52rem;border-radius:999px;background:#0f4a7a;color:#dbeafe;
          font-size:.64rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin-left:.35rem;border:1px solid rgba(147,197,253,.5)}
        .jj-meta {font-size:.79rem;color:#8999af;margin-top:.5rem}
        .jj-pending {font-size:.88rem;color:#c2cede;margin-top:.55rem}
        .jj-step {display:inline-block;font-size:.69rem;font-weight:750;letter-spacing:.12em;color:#91b5ff;
          background:#142a4c;border:1px solid #294e85;border-radius:7px;padding:.3rem .65rem;margin-top:1.5rem;margin-bottom:.25rem}
        .jj-top-banner {background:linear-gradient(135deg,#11253d 0%,#162f4f 100%);border:1px solid #31588b;border-radius:14px;
          padding:1rem 1.1rem;margin:1rem 0 1.2rem;box-shadow:0 12px 24px rgba(37,99,235,.06)}
        .jj-top-banner .title {font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:#7cc0ff;font-weight:800}
        .jj-top-banner .value {font-size:1.45rem;font-weight:800;color:#f8fbff;letter-spacing:-.02em;margin-top:.25rem}
        .jj-top-banner .meta {display:flex;flex-wrap:wrap;gap:.55rem;margin-top:.55rem}
        .jj-top-banner .chip {display:inline-block;padding:.35rem .6rem;border-radius:999px;background:#20314a;color:#d7e7ff;
          font-size:.72rem;font-weight:700;border:1px solid rgba(148,163,184,.3)}
        .jj-top-banner .chip.high {background:#123b35;color:#6ee7b7;border-color:rgba(52,211,153,.45)}
        .jj-top-banner .chip.medium {background:#3d3316;color:#f8d977;border-color:rgba(251,191,36,.5)}
        .jj-top-banner .chip.low {background:#45212b;color:#fda4af;border-color:rgba(251,113,133,.45)}
        @media (max-width: 640px) {
          .block-container {padding-left:1rem!important;padding-right:1rem!important;padding-top:1.15rem!important}
          div[data-testid="stTabs"] {overflow-x:auto}
          div[data-testid="stTabs"] button {font-size:.78rem;white-space:nowrap;padding:.55rem .65rem}
          .jj-hero {padding:1.25rem 1.1rem;border-radius:15px;background-size:cover,auto 135%;
            background-position:center,72% center}
          .jj-title {font-size:1.42rem}.jj-subtitle {font-size:.82rem}
          .jj-status-grid {grid-template-columns:1fr 1fr;gap:.55rem}
          .jj-status-card {padding:.72rem .78rem;border-radius:12px;box-shadow:0 4px 14px rgba(15,23,42,.05)}
          .jj-status-card:last-child {grid-column:1/-1}
          .jj-status-value {font-size:.98rem}
          .jj-range-grid {grid-template-columns:1fr 1fr;gap:.5rem}
          .jj-range-card {padding:.65rem}.jj-range-card b {font-size:.9rem}
          .jj-card {padding:.85rem .9rem}.jj-card-title {font-size:.94rem}
          .jj-badge {margin:.3rem .2rem 0 0}
          div.stButton > button {width:100%}
          div[data-testid="stHorizontalBlock"] {gap:.55rem}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    hero_background = _dashboard_background_data_uri()
    if hero_background:
        st.markdown(
            f"""<style>.jj-hero {{background-image:
            linear-gradient(90deg,rgba(8,17,31,.98) 0%,rgba(8,17,31,.90) 40%,rgba(8,17,31,.28) 100%),
            url('{hero_background}') !important;}}</style>""",
            unsafe_allow_html=True,
        )
    st.markdown(
        """<div class="jj-hero"><div class="jj-eyebrow">JJTRADE AI · MARKET INTELLIGENCE</div>
        <div class="jj-title">Movimientos y Estrategias en Tiempo Real</div>
        <div class="jj-subtitle">Mira el estado, revisa lo que se está formando y actúa solo cuando aparezca una señal confirmada.</div></div>""",
        unsafe_allow_html=True,
    )
    process_status = read_instance_status("exports/live_scanner.lock")
    scanner_active = bool(process_status.get("active"))
    dashboard_now = datetime.now(timezone.utc)
    dashboard_session = MarketSessionRepository(AlertRepository().database_path).session(
        dashboard_now.astimezone(ZoneInfo("America/New_York")).date()
    )
    session_open = dashboard_session is not None and dashboard_session.opens_at <= dashboard_now < dashboard_session.closes_at
    next_evaluation = _next_quarter_hour().strftime("%I:%M %p ET") if scanner_active and session_open else "Esperando apertura" if scanner_active else "N/D"
    status_tone = "active" if scanner_active else "stopped"
    st.markdown(
        f"""<div class="jj-status-grid">
        <div class="jj-status-card"><div class="jj-status-label">Estado</div>
        <div class="jj-status-value {status_tone}">{'CORRIENDO' if scanner_active else 'DETENIDA'}</div></div>
        <div class="jj-status-card"><div class="jj-status-label">Radar</div>
        <div class="jj-status-value">{'Cada minuto' if scanner_active else 'Inactivo'}</div></div>
        <div class="jj-status-card"><div class="jj-status-label">Próxima confirmación</div>
        <div class="jj-status-value">{next_evaluation}</div></div></div>""",
        unsafe_allow_html=True,
    )
    if not scanner_active:
        st.error("Inicia el scanner con el control que aparece debajo.")
    _render_scanner_controls(process_status)
    _render_price_ranges()
    stored_previews = LiveBollingerPreviewRepository(
        AlertRepository().database_path
    ).current()
    previews = _current_live_previews(stored_previews, now=dashboard_now) if session_open else []
    active_previews = [item for item in previews if item.get("strategies")]
    st.markdown('<div class="jj-step">1 · QUÉ SE ESTÁ FORMANDO</div>', unsafe_allow_html=True)
    st.markdown("### Estrategias en vivo")
    preview_cards: list[tuple[dict[str, object], str]] = []
    for item in active_previews:
        base_report = item.get("report", {}) if isinstance(item, Mapping) else {}
        for strategy in item.get("strategies", []):
            bias = str(strategy.get("bias", "SIN_SESGO"))
            probable_bias = str(strategy.get("potential_bias") or bias)
            display_bias = probable_bias if probable_bias in {"CALL", "PUT"} else bias
            tone = bias.lower() if bias in {"CALL", "PUT"} else ""
            tone = display_bias.lower() if display_bias in {"CALL", "PUT"} else tone
            symbol = html.escape(str(item.get("symbol", "N/D")))
            name = html.escape(str(strategy.get("name", strategy.get("strategy_id", "Estrategia"))))
            timeframe = html.escape(str(strategy.get("timeframe", "N/D")))
            direction_status = str(strategy.get("direction_status", "DIRECCIÓN PRELIMINAR"))
            signal_badge = _preview_confidence_badge(base_report, direction_status=direction_status)
            pending = html.escape(str(strategy.get("next_requirement", "Confirmar al cierre")))
            event_time = html.escape(_market_event_local_time(item.get("as_of")))
            preview_cards.append((
                {
                    "symbol": symbol,
                    "name": name,
                    "bias": display_bias,
                    "signal_kind": "PROBABLE" if probable_bias != bias and display_bias in {"CALL", "PUT"} else "DIRECCIÓN",
                    "timeframe": timeframe,
                    "direction_status": html.escape(direction_status),
                    "pending": pending,
                    "event_time": event_time,
                    "tone": tone,
                    "badge": signal_badge,
                },
                signal_badge["confidence_pct"],
            ))
    ranked_preview_cards = sorted(preview_cards, key=lambda entry: entry[1], reverse=True)
    if ranked_preview_cards:
        top_payload = ranked_preview_cards[0][0]
        top_badge = top_payload["badge"]
        st.markdown(
            f"""<div class="jj-top-banner">
            <div class="title">Top signal actual</div>
            <div class="value">{top_payload['symbol']} · {top_payload['name']}</div>
            <div class="meta">
                <span class="chip {top_badge['tone']}">Certeza: {top_badge['label']} · {top_badge['confidence_pct']}%</span>
                <span class="chip">Dirección: {top_payload['direction_status']}</span>
                <span class="chip">Tiempo: {top_payload['timeframe']}</span>
            </div>
            </div>""",
            unsafe_allow_html=True,
        )
    if not session_open:
        st.info("La sesión regular está cerrada o su calendario no está disponible. Las últimas detecciones se conservan abajo como historial; no son señales activas para entrar.")
    elif scanner_active and not previews:
        st.warning("El buscador figura encendido, pero el dashboard no tiene datos de los últimos tres minutos. Revisa la conexión del buscador.")
    elif scanner_active and not active_previews:
        st.info(f"Radar actualizado: {len(previews)} compañías con datos recientes. En este momento ninguna cumple las condiciones para mostrar una estrategia en formación.")
    with st.expander("Últimas estrategias observadas · historial"):
        history_rows = [
            {"Compañía": item.get("symbol"), "Estrategia": strategy.get("name", strategy.get("strategy_id")),
             "Temporalidad": strategy.get("timeframe"), "Última observación": _market_event_local_time(item.get("as_of")),
             "Estado": "Registro anterior · revisar vigencia"}
            for item in stored_previews for strategy in item.get("strategies", [])
        ]
        if history_rows:
            st.dataframe(pd.DataFrame(history_rows), width="stretch", hide_index=True)
        else:
            st.caption("Los últimos estados del radar no contienen estrategias detectadas. Las señales anteriores permanecen en el historial de alertas del dashboard.")
        st.caption("Esta lista muestra el último estado guardado por compañía, no todas las detecciones del día. Los avisos de Telegram funcionan en un servicio separado.")
    ranked_preview_cards = sorted(preview_cards, key=lambda entry: entry[1], reverse=True)
    for index, (payload, _) in enumerate(ranked_preview_cards):
        featured = " featured" if index == 0 else ""
        certainty_class = payload["badge"]["tone"] if payload["badge"]["tone"] in {"high", "medium", "low"} else "none"
        top_label = '<span class="jj-top-signal">TOP SIGNAL</span>' if index == 0 else ""
        st.markdown(
            f"""<div class="jj-card {payload['tone']} {certainty_class}{featured}"><div class="jj-card-title">{payload['symbol']} · {payload['name']}
            <span class="jj-badge {payload['tone']}">{html.escape(payload['bias'])}</span>
            <span class="jj-badge">{html.escape(payload['signal_kind'])}</span>
            <span class="jj-badge">{payload['timeframe']}</span>
            <span class="jj-badge {payload['badge']['tone']}">{payload['badge']['label']} · {payload['badge']['confidence_pct']}%</span>
            <span class="jj-badge">{payload['direction_status']}</span>{top_label}</div>
            <div class="jj-meta">Actualizada {payload['event_time']}</div>
            <div class="jj-pending"><b>Pendiente:</b> {payload['pending']}</div></div>""",
            unsafe_allow_html=True,
        )
    alerts = [
        item for item in AlertRepository().recent(limit=100)
        if item.get("event_type") != "SIN_SETUP"
    ]
    latest_by_symbol: dict[str, Mapping[str, object]] = {}
    alerts_by_symbol: dict[str, list[Mapping[str, object]]] = {}
    for item in alerts:
        symbol = str(item.get("symbol") or "N/D")
        alerts_by_symbol.setdefault(symbol, []).append(item)
        if symbol not in latest_by_symbol:
            latest_by_symbol[symbol] = item
    cards = []
    for alert in latest_by_symbol.values():
        summary = _simple_alert_summary(alert)
        signature = setup_signature(alert.get("report", {}))
        episode_start = alert
        if signature:
            for previous in alerts_by_symbol[str(summary["symbol"])][1:]:
                if setup_signature(previous.get("report", {})) != signature:
                    break
                episode_start = previous
        summary["first_detected_timestamp"] = episode_start.get("trigger_timestamp")
        moment = _simple_moment_status(summary, scanner_active=scanner_active, market_open=session_open, now=dashboard_now)
        cards.append((summary, moment))
    priority = {
        "SIMULAR": 0, "REVISAR": 1, "ESPERAR": 2,
        "FUERA_DE_VENTANA": 3, "VENCIDA": 4, "HISTORICA": 5,
    }
    cards.sort(key=lambda item: (priority.get(str(item[1]["status"]), 9), str(item[0]["symbol"])))
    current_cards = [
        item for item in cards
        if str(item[1].get("status")) not in {
            "HISTORICA", "VENCIDA", "FUERA_DE_VENTANA", "SIN_SETUP",
        }
    ]
    actionable_cards = [
        item for item in current_cards
        if bool(item[0].get("can_operate"))
        and str(item[0].get("direction")) in {"CALL", "PUT"}
    ]
    observation_cards = [item for item in current_cards if item not in actionable_cards]
    st.markdown('<div class="jj-step">2 · QUÉ HACER AHORA</div>', unsafe_allow_html=True)
    st.markdown("### Señal para operar")
    if not session_open:
        st.info("NO OPERAR · Sesión regular cerrada o calendario no disponible. El buscador puede seguir conectado, pero no hay señales activas ni aprobaciones vigentes para entrar.")
    elif not scanner_active:
        st.warning("NO OPERAR · La app no esta recibiendo mercado en vivo.")
    elif not actionable_cards:
        st.info(
            "NO OPERAR AHORA · No hay ninguna estrategia confirmada con todas "
            "las compuertas aprobadas. El radar en vivo continua evaluando cada "
            f"minuto. Proxima confirmacion al cierre: {next_evaluation}."
        )
    for summary, moment in actionable_cards:
        compact = _compact_operational_card(summary, moment)
        notification = _operational_notification(summary, moment)
        alert_id = int(summary.get("alert_id", 0) or 0)
        notified_ids = list(st.session_state.get("operational_notified_alert_ids", ()))
        if scanner_active and notification and alert_id not in notified_ids:
            st.toast(notification["title"], icon=notification["icon"])
            _send_desktop_notification(notification)
            notified_ids.append(alert_id)
            st.session_state["operational_notified_alert_ids"] = notified_ids[-200:]
        with st.container(border=True):
            st.markdown(f"#### {compact['title']}")
            if notification:
                _render_alert_banner(notification)
            st.markdown(
                f"**{compact['state']}** · **{compact['direction']}** · "
                f"**{compact['action']}**"
            )
            st.write(f"**Temporalidad evaluada:** {summary.get('timeframe', 'N/D')}")
            st.write(f"**Motivo:** {compact['reason']}")
            detected_time = _market_event_local_time(summary.get("first_detected_timestamp"))
            st.caption(
                f"Detectada: {detected_time} · Ultima evaluacion: {moment['local_time']}"
            )
            with st.expander("Detalles"):
                st.write(f"Feed: {str(summary['feed']).upper()} · {summary['feed_scope']}")
                st.write(f"Alerta: #{summary['alert_id']}")
                st.write(f"Vela: {summary['trigger_timestamp']}")
                if moment["age_minutes"] is not None:
                    st.write(f"Antiguedad: {moment['age_minutes']:.0f} minutos")

    if observation_cards:
        with st.expander(
            f"Otras estrategias esperando confirmación ({len(observation_cards)})",
            expanded=False,
        ):
            st.caption("Son contexto adicional; todavía no autorizan una entrada.")
            for summary, moment in observation_cards:
                compact = _compact_operational_card(summary, moment)
                st.markdown(f"**{compact['title']}**")
                st.write(
                    f"{compact['direction']} preliminar · {compact['reason']}"
                )
                st.caption(
                    f"{_market_event_local_time(summary.get('first_detected_timestamp'))} "
                    f"· última evaluación {moment['local_time']}"
                )
                st.divider()

    with st.expander("Información técnica y configuración", expanded=False):
        st.caption(
            "La app se actualiza cada 15 segundos y evalua estrategias al cierre "
            "de cada bloque de 15 minutos."
        )
        _desktop_notification_controls()
        feed_summary = _load_feed_comparison()
        st.write(f"Calidad de datos: **{feed_summary['label']}**")
        if feed_summary.get("rows"):
            st.dataframe(pd.DataFrame(feed_summary["rows"]), width="stretch", hide_index=True)
        if cards:
            st.write(f"Resultados historicos disponibles: **{len(cards)}**")


def _option_candidates_table(candidates: object) -> pd.DataFrame:
    """Presenta contratos candidatos con sus compuertas explícitas."""
    return pd.DataFrame(
        [
            {
                "Contrato": item.snapshot.symbol,
                "Tipo": item.snapshot.option_type,
                "Strike": item.snapshot.strike,
                "Vencimiento": item.snapshot.expiration.isoformat(),
                "Bid": item.snapshot.bid,
                "Ask": item.snapshot.ask,
                "Spread %": item.risk.spread_pct,
                "Delta": item.snapshot.delta,
                "IV": item.snapshot.implied_volatility,
                "Bid size": item.snapshot.bid_size,
                "Ask size": item.snapshot.ask_size,
                "Riesgo": item.risk.status.value,
                "Liquidez": "APROBADA" if item.liquidity_approved else "RECHAZADA",
                "Delta válido": "SÍ" if item.delta_approved else "NO",
                "Feed": item.snapshot.feed,
                "Elegible": "SÍ" if item.eligible else "NO",
            }
            for item in candidates
        ]
    )


def _service_health_table(health: Mapping[str, object]) -> pd.DataFrame:
    """Presenta el heartbeat persistido del scanner continuo."""
    symbols = health.get("symbols", ())
    if not isinstance(symbols, (list, tuple)):
        symbols = ()
    return pd.DataFrame(
        [{
            "Estado": health.get("status", "NO_INICIADO"),
            "Proveedor": health.get("provider", "N/D"),
            "Feed": health.get("feed", "N/D"),
            "Símbolos": ", ".join(str(item) for item in symbols) or "N/D",
            "Última conexión": health.get("last_connected_at") or "N/D",
            "Última vela": health.get("last_bar_at") or "N/D",
            "Reconexiones": int(health.get("reconnect_count", 0)),
            "Último error": health.get("last_error") or "",
        }]
    )


def _paper_evidence_checks_table(
    evidence: Mapping[str, object],
) -> pd.DataFrame:
    """Presenta checks de evidencia real sin exponer payloads sensibles."""
    checks = evidence.get("checks", ())
    if not isinstance(checks, (list, tuple)):
        checks = ()
    return pd.DataFrame(
        [
            {
                "Check": str(item.get("name", "")),
                "Estado": str(item.get("status", "")),
                "Detalle": str(item.get("detail", "")),
            }
            for item in checks
            if isinstance(item, Mapping)
        ],
        columns=("Check", "Estado", "Detalle"),
    )


def _reevaluation_outcome_mode(
    reevaluation: Mapping[str, object],
    governance_reviews: object,
) -> str:
    """Deriva el modo del resultado desde el gobierno versionado."""
    governance_id = int(reevaluation.get("governance_review_id", 0) or 0)
    if governance_id == 0:
        return "PAPER"
    if not isinstance(governance_reviews, (list, tuple)):
        raise ValueError("No existe historial de gobierno para la reevaluacion.")
    match = next(
        (
            item
            for item in governance_reviews
            if isinstance(item, Mapping)
            and int(item.get("id", 0) or 0) == governance_id
        ),
        None,
    )
    if match is None:
        raise ValueError("La revision de gobierno vinculada no esta disponible.")
    mode = str(match.get("mode", "")).upper()
    if mode not in {"PAPER", "REAL"}:
        raise ValueError("La revision de gobierno tiene un modo invalido.")
    return mode


def _alert_reviews_table(reviews: object) -> pd.DataFrame:
    """Presenta el historial humano sin confundir pendiente con rechazo."""
    def label(value: bool | None) -> str:
        return "SÍ" if value is True else "NO" if value is False else "PENDIENTE"
    return pd.DataFrame(
        [
            {
                "ID": item["id"],
                "Fecha": item["created_at"],
                "Camino libre": label(item["path_clear"]),
                "Noticias revisadas": label(item["news_clear"]),
                "Panorama aprobado": label(item["panorama_approved"]),
                "Notas": item["notes"],
            }
            for item in reviews
        ]
    )


@st.fragment(run_every="15s")
def render_live_alerts() -> None:
    """Muestra evaluaciones generadas por el proceso continuo."""
    st.subheader("Alertas de mercado")
    st.caption("Evaluaciones al cierre de 15 minutos; nunca son órdenes.")
    process_status = read_instance_status("exports/live_scanner.lock")
    health = ServiceHealthRepository().get("live_strategy_scanner")
    preflight_history = recent_live_preflights(AlertRepository().database_path, limit=20)
    if process_status.get("active"):
        active_preflight = next(
            (item for item in preflight_history if item["payload"].get("status") == "LISTO"),
            None,
        )
    else:
        active_preflight = preflight_history[0] if preflight_history else None
    latest_preflight = active_preflight["payload"] if active_preflight else None
    now = datetime.now(timezone.utc)
    official_session = MarketSessionRepository(AlertRepository().database_path).session(
        now.astimezone(ZoneInfo("America/New_York")).date()
    )
    reconciliation_history = MarketReconciliationRepository(AlertRepository().database_path).recent(limit=20)
    latest_reconciliation = reconciliation_history[0] if reconciliation_history else None
    target_symbols = tuple(str(item) for item in (latest_preflight or {}).get("symbols", ()))
    reconciliations_by_symbol = MarketReconciliationRepository(
        AlertRepository().database_path
    ).latest_by_symbol(target_symbols)
    incident_repository = ScannerIncidentRepository(
        AlertRepository().database_path
    )
    open_processing_incidents = incident_repository.unresolved_count(
        symbols=target_symbols
    )
    operational = evaluate_operational_status(
        preflight=latest_preflight, health=health, session=official_session, now=now,
        reconciliation=latest_reconciliation if not target_symbols else None,
        reconciliations=reconciliations_by_symbol,
        expected_symbols=target_symbols,
        open_processing_incident_count=open_processing_incidents,
    )
    st.metric("Estado operativo", operational["status"])
    if operational["reasons"]:
        st.caption(" · ".join(operational["reasons"]))
    coverage_details = operational.get("reconciliation_coverage", {}).get("details", [])
    if coverage_details:
        st.dataframe(pd.DataFrame(coverage_details), width="stretch", hide_index=True)
    if reconciliation_history:
        with st.expander("Historial WebSocket–REST"):
            st.dataframe(pd.DataFrame([
                {"ID": item["id"], "Símbolo": item["symbol"], "Vela": item["trigger_timestamp"], "Estado": item["status"], "Diferencias": item["difference_count"]}
                for item in reconciliation_history
            ]), width="stretch", hide_index=True)
    if health:
        st.dataframe(_service_health_table(health), width="stretch", hide_index=True)
    else:
        st.caption("Servicio en vivo: todavía no iniciado.")
    st.metric("Incidentes de procesamiento abiertos", open_processing_incidents)
    incident_history = incident_repository.recent(limit=50)
    if incident_history:
        with st.expander("Historial de incidentes del scanner"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ID": item["id"],
                            "Simbolo": item["symbol"],
                            "Vela": item["bar_timestamp"],
                            "Etapa": item["stage"],
                            "Tipo": item["error_type"],
                            "Detalle seguro": item["error_detail"],
                            "Resuelto": item["resolved_at"] or "",
                            "Vela de recuperacion": (
                                item["resolution_bar_timestamp"] or ""
                            ),
                        }
                        for item in incident_history
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
    alerts = AlertRepository().recent(limit=100)
    pending_alerts = AlertRepository().recent_unacknowledged(limit=100)
    new_alert_count = AlertRepository().unacknowledged_count()
    st.metric("Alertas nuevas sin acuse", new_alert_count)
    if alerts:
        latest_report = alerts[0].get("report", {}) if isinstance(alerts[0], Mapping) else {}
        latest_signal = _current_strategy_certainty(latest_report)
        latest_guidance = _live_direction_guidance(latest_report)
        lead_signal = _lead_live_signal(alerts)
        confidence_pct = float(latest_signal["confidence"])
        priority = str(latest_signal["priority"])
        if confidence_pct >= 80:
            status_color = "success"
            status_label = "ALTA"
        elif confidence_pct >= 60:
            status_color = "warning"
            status_label = "MEDIA"
        elif confidence_pct > 0:
            status_color = "info"
            status_label = "BAJA"
        else:
            status_color = "secondary"
            status_label = "SIN_CERTIDUMBRE"
        if lead_signal["direction"] in {"CALL", "PUT"}:
            if lead_signal["status"] == "CONFIRMADA":
                tone = "#103d34" if lead_signal["direction"] == "CALL" else "#3f1d2b"
                accent = "#34d399" if lead_signal["direction"] == "CALL" else "#fb7185"
                label = "ALTA CERTEZA"
            elif lead_signal["status"] == "PROBABLE":
                tone = "#2d2f43" if lead_signal["direction"] == "CALL" else "#38293a"
                accent = "#fbbf24" if lead_signal["direction"] == "CALL" else "#fda4af"
                label = "PROBABLE"
            else:
                tone = "#2b2b36"
                accent = "#a78bfa"
                label = "SEGUIMIENTO"
            st.markdown(
                f"<div style='padding:14px 18px;border-radius:12px;background:{tone};border-left:8px solid {accent};color:#f8fafc;font-weight:800;font-size:1.05rem;line-height:1.4;'>"
                f"{lead_signal['direction']} · {label} · {lead_signal['confidence_pct']}% · {lead_signal['strategy']}</div>",
                unsafe_allow_html=True,
            )
        if latest_signal["status"] == "APRENDIZAJE_ALINEADO":
            st.success(f"Estrategia en vivo: {latest_signal['strategy']} · certeza histórica {confidence_pct:.1f}% · prioridad {priority} · estado {status_label}")
        elif latest_signal["status"] == "APRENDIZAJE_CONTRARIO":
            st.warning(f"Estrategia en vivo: {latest_signal['strategy']} · evidencia contraria · certeza {confidence_pct:.1f}% · prioridad {priority}")
        elif latest_signal["strategy"] != "SIN_ESTRATEGIA":
            st.info(f"Estrategia en vivo: {latest_signal['strategy']} · certeza histórica {confidence_pct:.1f}% · prioridad {priority} · requiere revisión")
        else:
            st.info("Estrategia en vivo: SIN_ESTRATEGIA · aún no hay evidencia histórica suficiente para certificar la operación.")
        st.caption(
            f"Dirección probable: {latest_guidance['direction']} · estado {latest_guidance['status']} · certeza {latest_guidance['confidence_pct']}% · prioridad {latest_guidance['priority']}"
        )
        live_summary_cols = st.columns(4)
        live_summary_cols[0].metric("Estrategia en vivo", latest_signal["strategy"])
        live_summary_cols[1].metric("Certeza histórica", f"{latest_signal['confidence']:.1f}%")
        live_summary_cols[2].metric("Prioridad", latest_signal["priority"])
        live_summary_cols[3].metric("Dirección probable", latest_guidance["direction"])
    paper_readiness = evaluate_paper_readiness(
        preflight=latest_preflight, process=process_status,
        operational=operational, pending_alert_count=new_alert_count,
    )
    readiness_columns = st.columns(3)
    readiness_columns[0].metric("Preparación PAPER", paper_readiness["status"])
    readiness_columns[1].metric("Bloqueos", len(paper_readiness["blockers"]))
    readiness_columns[2].metric("Advertencias", len(paper_readiness["warnings"]))
    if paper_readiness["blockers"]:
        st.error(" · ".join(paper_readiness["blockers"]))
    if paper_readiness["next_actions"]:
        st.caption("Siguiente: " + " · ".join(paper_readiness["next_actions"]))
    st.download_button(
        "Descargar preparación PAPER JSON",
        data=json.dumps(paper_readiness, ensure_ascii=False, indent=2),
        file_name="paper_readiness.json", mime="application/json",
        key="download_paper_readiness",
    )
    paper_evidence = build_paper_session_evidence(
        AlertRepository().database_path,
        symbols=target_symbols,
        lock_file="exports/live_scanner.lock",
        now=now,
    )
    evidence_columns = st.columns(3)
    evidence_columns[0].metric(
        "Validacion mercado real",
        paper_evidence["status"],
    )
    evidence_columns[1].metric(
        "Simbolos con evidencia",
        len(paper_evidence.get("symbols", ())),
    )
    evidence_columns[2].metric(
        "Incidentes abiertos en evidencia",
        int(
            paper_evidence.get("processing_incidents", {}).get(
                "open_count",
                0,
            )
        ),
    )
    if paper_evidence["status"] == "APROBADO":
        st.success(
            "La sesion PAPER tiene evidencia real aprobada; esto no autoriza "
            "operaciones reales."
        )
    elif paper_evidence["status"] == "BLOQUEADO":
        st.error("Evidencia PAPER bloqueada: revisa los checks y recuperaciones.")
    else:
        st.info(
            "La validacion con mercado real aun no esta completa. "
            "Codigo sano no equivale a sesion aprobada."
        )
    with st.expander("Checks de evidencia PAPER real"):
        st.dataframe(
            _paper_evidence_checks_table(paper_evidence),
            width="stretch",
            hide_index=True,
        )
        if paper_evidence.get("next_actions"):
            st.caption(
                "Siguiente: "
                + " · ".join(str(item) for item in paper_evidence["next_actions"])
            )
    st.download_button(
        "Descargar evidencia PAPER real JSON",
        data=json.dumps(paper_evidence, ensure_ascii=False, indent=2),
        file_name="paper_session_evidence.json",
        mime="application/json",
        key="download_paper_session_evidence",
    )
    visual_milestone = VisualEvidenceRepository(
        AlertRepository().database_path
    ).overall_audit()
    visual_columns = st.columns(3)
    visual_columns[0].metric(
        "Auditoria visual posterior (opcional)",
        visual_milestone["status"],
    )
    visual_columns[1].metric(
        "Capturas TC2000",
        visual_milestone["evidence_count"],
    )
    visual_columns[2].metric(
        "Casos 15m + 1H + 1D completos",
        visual_milestone["complete_alert_count"],
    )
    if visual_milestone["status"] != "APROBADO":
        st.caption(
            "No bloquea ni retrasa alertas. Si se audita un caso despues del "
            "movimiento, el conjunto completo usa 15m, 1H y 1D con revision COINCIDE."
        )
    st.download_button(
        "Descargar hito visual TC2000 JSON",
        data=json.dumps(visual_milestone, ensure_ascii=False, indent=2),
        file_name="visual_evidence_status.json",
        mime="application/json",
        key="download_visual_evidence_status",
    )
    if not alerts:
        st.info("Todavía no existen alertas del scanner continuo.")
        return
    show_no_setup = st.checkbox("Mostrar escaneos sin setup", value=False, key="show_live_no_setup")
    informational_events = {"SIN_SETUP", "SETUP_SIN_CAMBIO", "SETUP_FINALIZADO", "SETUP_VENCIDO"}
    visible_alerts = alerts if show_no_setup else [
        item for item in alerts if item.get("event_type") not in informational_events
    ]
    visible_alerts = sorted(
        visible_alerts,
        key=_alert_live_certainty_rank,
        reverse=True,
    )
    if not visible_alerts:
        st.info("Existen escaneos guardados, pero ninguno requiere atención.")
        return
    latest_pending = pending_alerts[0] if pending_alerts else None
    latest_alert_id = int(latest_pending["id"]) if latest_pending else 0
    previous_notified = int(st.session_state.get("latest_notified_live_alert", 0))
    if latest_alert_id > previous_notified and new_alert_count:
        st.toast(f"Nueva alerta #{latest_alert_id}: {latest_pending['symbol']}", icon="🔔")
    st.session_state["latest_notified_live_alert"] = max(previous_notified, latest_alert_id)
    st.dataframe(_live_alerts_table(visible_alerts), width="stretch", hide_index=True)
    labels = {
        f"#{item['id']} · {item['symbol']} · {item['trigger_timestamp']}": item
        for item in visible_alerts
    }
    selected = st.selectbox("Detalle de alerta", list(labels))
    report = labels[selected]["report"]
    current_signal = _current_strategy_certainty(report)
    operating_signal = _operating_signal_status(report)
    live_guidance = _live_direction_guidance(report)
    strategy_cols = st.columns(4)
    strategy_cols[0].metric("Estrategia actual", current_signal["strategy"])
    strategy_cols[1].metric("Certeza histórica", f"{current_signal['confidence']:.1f}%")
    strategy_cols[2].metric("Prioridad", current_signal["priority"])
    strategy_cols[3].metric("Dirección probable", live_guidance["direction"])
    if live_guidance["status"] == "CONFIRMADA":
        st.success(f"Dirección probable confirmada: {live_guidance['direction']} · certeza {live_guidance['confidence_pct']}% · prioridad {live_guidance['priority']}")
    elif live_guidance["status"] == "PROBABLE":
        st.info(f"Dirección probable: {live_guidance['direction']} · certeza {live_guidance['confidence_pct']}% · prioridad {live_guidance['priority']}")
    elif live_guidance["status"] == "CONTRARIA":
        st.warning(f"La dirección probable del mercado contradice la señal actual: {live_guidance['direction']} · prioridad {live_guidance['priority']}")
    elif live_guidance["status"] == "PENDIENTE":
        st.warning(f"Dirección aún pendiente: {live_guidance['direction']} · requiere seguimiento del movimiento")
    if operating_signal["status"] == "PAPER_APTA_REVISION":
        st.success("Estado operativo: PAPER APTA PARA REVISION. " + str(operating_signal["reasons"][0]))
    elif operating_signal["status"] == "ESPERAR_VALIDACION":
        st.info("Estado operativo: ESPERAR VALIDACION. " + str(operating_signal["reasons"][0]))
    else:
        st.error("Estado operativo: BLOQUEADA. " + " ".join(str(reason) for reason in operating_signal["reasons"]))
    if current_signal["status"] == "APRENDIZAJE_ALINEADO":
        st.success(f"Aprendizaje histórico alineado para {current_signal['strategy']}.")
    elif current_signal["status"] == "APRENDIZAJE_CONTRARIO":
        st.warning(f"El historial para {current_signal['strategy']} apunta en sentido contrario; requiere revisión.")
    elif current_signal["status"] == "HISTORIAL_CONFLICTIVO":
        st.warning(f"Hay conflicto histórico en la estrategia {current_signal['strategy']}; revisar antes de operar.")
    elif current_signal["strategy"] == "SIN_ESTRATEGIA":
        st.info("Todavía no hay evidencia histórica suficiente para certificar la estrategia en vivo.")
    st.json(report)
    reconciliation = report.get("market_data_reconciliation", {})
    if reconciliation:
        status = reconciliation.get("status", "NO_DISPONIBLE")
        message = f"Reconciliación WebSocket–REST: {status} · diferencias: {reconciliation.get('difference_count', 0)}"
        if status == "APROBADO":
            st.success(message)
        elif status == "OMITIDO":
            st.info(message)
        else:
            st.error(message)
    advisory = report.get("learning_advisory", {})
    advisory_rows = advisory.get("rows", []) if isinstance(advisory, Mapping) else []
    if advisory_rows:
        st.markdown("### Evidencia histórica disponible al emitir la alerta")
        st.caption(str(advisory.get("disclaimer", "Evidencia descriptiva; no modifica la decisión.")))
        st.dataframe(pd.DataFrame(advisory_rows), width="stretch", hide_index=True)
        detected_for_advisory = [
            str(item.get("strategy_id"))
            for item in report.get("strategies", {}).get("evaluations", [])
            if item.get("detected") is True
        ]
        advisory_audit = audit_learning_advisory(
            advisory, AlertRepository().alert_learning_records(),
            strategy_ids=detected_for_advisory, context=report.get("learning_context", {}),
        )
        if advisory_audit["status"] == "REPRODUCIBLE":
            st.success("Asesoría histórica reproducible con el historial actual.")
        elif advisory_audit["status"] == "HISTORIAL_CAMBIO":
            st.info("El historial fue ampliado o corregido después de esta alerta. La asesoría original permanece congelada.")
        else:
            st.warning("Esta asesoría antigua no contiene metadatos suficientes para auditoría.")
    directional_signal = report.get("directional_learning_signal", {})
    if isinstance(directional_signal, Mapping):
        signal_status = str(directional_signal.get("status", "MUESTRA_INSUFICIENTE"))
        if signal_status == "APRENDIZAJE_ALINEADO":
            st.success(
                "Aprendizaje histórico alineado con la dirección confirmada: "
                f"{directional_signal.get('recommended_direction')}."
            )
        elif signal_status == "APRENDIZAJE_CONTRARIO":
            st.warning(
                "El historial suficiente apunta en dirección contraria; "
                "requiere revisión humana antes de operar."
            )
        elif signal_status == "HISTORIAL_CONFLICTIVO":
            st.warning("Las estrategias confirmadas muestran patrones históricos en conflicto.")
        elif signal_status == "MUESTRA_INSUFICIENTE":
            st.info("Aún no hay suficientes resultados confirmados para calibrar CALL/PUT.")
        signal_rows = directional_signal.get("rows", [])
        if signal_rows:
            st.markdown("### Aprendizaje direccional por estrategia")
            st.caption(str(directional_signal.get("disclaimer", "Evidencia histórica descriptiva.")))
            if directional_signal.get("summary_score") is not None:
                st.info(
                    f"Certeza histórica agregada: {directional_signal.get('summary_score')}% · "
                    f"prioridad {directional_signal.get('priority', 'MINIMA')}"
                )
            st.dataframe(pd.DataFrame([
                {
                    "Estrategia": row.get("strategy_id"),
                    "Fuente": row.get("source"),
                    "Dirección histórica": row.get("historical_direction") or "NO CALIBRADA",
                    "Muestra": row.get("sample_size"),
                    "Tasa positiva %": row.get("positive_rate"),
                    "Límite inferior 95 %": row.get("interval_95_low"),
                    "Certeza histórica %": row.get("confidence_score"),
                    "Prioridad": row.get("priority", "MINIMA"),
                }
                for row in signal_rows
            ]), width="stretch", hide_index=True)
    automatic_signal = report.get("automatic_learning_signal", {})
    if isinstance(automatic_signal, Mapping):
        automatic_status = str(automatic_signal.get("status", "MUESTRA_INSUFICIENTE"))
        if automatic_status == "APRENDIZAJE_ALINEADO":
            st.success(
                "Aprendizaje automático del movimiento posterior alineado con: "
                f"{automatic_signal.get('recommended_direction')}."
            )
        elif automatic_status == "APRENDIZAJE_CONTRARIO":
            st.warning("El movimiento histórico posterior contradice la dirección actual; requiere revisión.")
        elif automatic_status == "HISTORIAL_CONFLICTIVO":
            st.warning("El aprendizaje automático encuentra direcciones históricas conflictivas.")
        elif automatic_status == "MUESTRA_INSUFICIENTE":
            st.info("El aprendizaje automático todavía necesita más cierres posteriores de esta estrategia.")
    st.download_button(
        "Descargar alerta JSON",
        data=json.dumps(report, ensure_ascii=False, indent=2),
        file_name=f"alert_{labels[selected]['id']}_{labels[selected]['symbol']}.json",
        mime="application/json",
    )
    alert = labels[selected]
    st.markdown("### Auditoria visual posterior TC2000 (opcional)")
    st.caption(
        "La señal en vivo ya fue emitida con datos API. Adjunta capturas solo "
        "despues del movimiento si deseas auditar el caso; nunca modifica la "
        "decision original ni es requisito para recibir alertas."
    )
    visual_repository = VisualEvidenceRepository(
        AlertRepository().database_path
    )
    visual_columns = st.columns(2)
    visual_timeframe = visual_columns[0].selectbox(
        "Temporalidad de la captura",
        ["15m", "1H", "1D"],
        key=f"visual_timeframe_{alert['id']}",
    )
    visual_upload = visual_columns[1].file_uploader(
        "Captura PNG o JPEG",
        type=["png", "jpg", "jpeg"],
        key=f"visual_upload_{alert['id']}",
    )
    visual_indicators = st.multiselect(
        "Indicadores visibles declarados",
        ["MA20", "MA40", "MA100", "MA200", "BOLLINGER", "VOLUME", "STOCHASTICS", "WORDEN"],
        key=f"visual_indicators_{alert['id']}",
    )
    visual_notes = st.text_input(
        "Notas de la captura",
        key=f"visual_notes_{alert['id']}",
    )
    if st.button(
        "Guardar evidencia visual",
        disabled=visual_upload is None,
        key=f"save_visual_{alert['id']}",
    ):
        try:
            evidence_id = visual_repository.record(
                alert["id"],
                timeframe=visual_timeframe,
                filename=visual_upload.name,
                content=visual_upload.getvalue(),
                indicators_visible=tuple(visual_indicators),
                notes=visual_notes,
            )
        except (OSError, ValueError) as error:
            st.error(str(error))
        else:
            st.success(
                f"Evidencia visual #{evidence_id} guardada sin alterar la decision."
            )
    visual_evidence = visual_repository.recent(alert["id"])
    visual_audit = visual_repository.audit(alert["id"])
    if visual_evidence:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ID": item["id"],
                        "Fecha": item["created_at"],
                        "Temporalidad": item["timeframe"],
                        "Tamano": f"{item['width']}x{item['height']}",
                        "Indicadores": ", ".join(item["indicators_visible"]),
                        "SHA-256": item["content_hash"][:16],
                    }
                    for item in visual_evidence
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        visual_labels = {
            f"#{item['id']} · {item['timeframe']} · {item['original_filename']}": item
            for item in visual_evidence
        }
        selected_visual_label = st.selectbox(
            "Captura para revisar",
            list(visual_labels),
            key=f"selected_visual_{alert['id']}",
        )
        selected_visual = visual_labels[selected_visual_label]
        try:
            selected_visual_path = visual_repository.image_path(selected_visual)
        except ValueError as error:
            st.error(str(error))
        else:
            st.image(
                str(selected_visual_path),
                caption=(
                    f"{selected_visual['symbol']} · "
                    f"{selected_visual['timeframe']} · evidencia complementaria"
                ),
            )
        visual_review_columns = st.columns(2)
        visual_review_status = visual_review_columns[0].selectbox(
            "Resultado de revision visual",
            ["PENDIENTE", "COINCIDE", "DIFIERE", "NO_EVALUABLE"],
            key=f"visual_review_status_{selected_visual['id']}",
        )
        visual_review_notes = visual_review_columns[1].text_input(
            "Notas de revision visual",
            key=f"visual_review_notes_{selected_visual['id']}",
        )
        if st.button(
            "Guardar revision visual",
            key=f"save_visual_review_{selected_visual['id']}",
        ):
            try:
                visual_review_id = visual_repository.record_review(
                    selected_visual["id"],
                    status=visual_review_status,
                    notes=visual_review_notes,
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.success(f"Revision visual #{visual_review_id} guardada.")
        visual_reviews = visual_repository.reviews(selected_visual["id"])
        if visual_reviews:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ID": item["id"],
                            "Fecha": item["created_at"],
                            "Estado": item["status"],
                            "Notas": item["notes"],
                        }
                        for item in visual_reviews
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        visual_audit_columns = st.columns(4)
        visual_audit_columns[0].metric(
            "Integridad visual", visual_audit["status"]
        )
        visual_audit_columns[1].metric(
            "Capturas", visual_audit["evidence_count"]
        )
        visual_audit_columns[2].metric(
            "Revisiones pendientes", visual_audit["pending_review_count"]
        )
        visual_audit_columns[3].metric(
            "Discrepancias", visual_audit["disagreement_count"]
        )
        if visual_audit["status"] == "BLOQUEADO_ARCHIVOS":
            st.error(
                "Una o mas capturas faltan o no coinciden con su registro."
            )
        elif visual_audit["status"] == "INTEGRO":
            st.success("Archivos visuales verificados mediante SHA-256.")
        st.download_button(
            "Descargar manifiesto visual JSON",
            data=json.dumps(visual_audit, ensure_ascii=False, indent=2),
            file_name=f"visual_evidence_alert_{alert['id']}.json",
            mime="application/json",
            key=f"download_visual_manifest_{alert['id']}",
        )
    if any(str(item.get("strategy_id", "")).startswith("EFECTO_IMAN_")
           for item in report.get("strategies", {}).get("evaluations", [])):
        with st.expander("Revisión visual de Worden en Hora"):
            st.caption("Registra lo que viste en TC2000. Esta observación conserva la señal original; no confirma automáticamente la estrategia.")
            observed_default = datetime.fromisoformat(alert["trigger_timestamp"]).astimezone(ZoneInfo("America/New_York"))
            observation_date = st.date_input("Fecha observada (ET)", value=observed_default.date(), key=f"worden_date_{alert['id']}")
            observation_time = st.time_input("Hora observada (ET)", value=observed_default.time().replace(tzinfo=None), key=f"worden_time_{alert['id']}")
            statuses = {"No puedo evaluarlo": "NO_EVALUABLE", "Observé el cruce de la línea roja": "CRUCE_OBSERVADO", "No observé el cruce": "SIN_CRUCE"}
            observation_status = st.selectbox("Resultado visual", list(statuses), key=f"worden_status_{alert['id']}")
            evidence_options = {"Sin captura": None}
            evidence_options.update({f"Captura #{item['id']} de Hora": item["id"] for item in visual_evidence
                                     if item["timeframe"] == "1H" and "WORDEN" in item["indicators_visible"]})
            observation_evidence = st.selectbox("Captura de Hora con Worden", list(evidence_options), key=f"worden_evidence_{alert['id']}")
            observation_notes = st.text_input("Notas de Worden", key=f"worden_notes_{alert['id']}")
            worden_repository = WordenReviewRepository(AlertRepository().database_path)
            if st.button("Guardar observación de Worden", key=f"save_worden_{alert['id']}"):
                try:
                    review_id = worden_repository.record(
                        alert["id"], observed_at=datetime.combine(observation_date, observation_time, tzinfo=ZoneInfo("America/New_York")),
                        status=statuses[observation_status], evidence_id=evidence_options[observation_evidence], notes=observation_notes,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success(f"Observación #{review_id} guardada.")
            observations = worden_repository.recent(alert["id"])
            if observations:
                st.dataframe(pd.DataFrame([{"ID": item["id"], "Hora observada": item["observed_at"], "Registrada": item["created_at"],
                                            "Estado": item["status"], "Captura": item["evidence_id"], "Notas": item["notes"]}
                                           for item in observations]), width="stretch", hide_index=True)
    st.markdown("### Acuse de alerta")
    acknowledgement_columns = st.columns(2)
    acknowledgement_status = acknowledgement_columns[0].selectbox(
        "Estado de atención", ["VISTA", "ATENDIDA", "DESCARTADA"], key=f"ack_status_{alert['id']}"
    )
    acknowledgement_notes = acknowledgement_columns[1].text_input(
        "Notas del acuse", key=f"ack_notes_{alert['id']}"
    )
    if st.button("Guardar acuse", key=f"save_ack_{alert['id']}"):
        try:
            acknowledgement_id = AlertRepository().record_acknowledgement(
                alert["id"], status=acknowledgement_status, notes=acknowledgement_notes
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(f"Acuse #{acknowledgement_id} guardado.")
    acknowledgements = AlertRepository().acknowledgements(alert["id"])
    if acknowledgements:
        st.dataframe(pd.DataFrame([
            {"ID": item["id"], "Fecha": item["created_at"], "Estado": item["status"], "Notas": item["notes"]}
            for item in acknowledgements
        ]), width="stretch", hide_index=True)
    candidates = report.get("option_selection", {}).get("candidates", [])
    eligible_candidates = [item for item in candidates if item.get("eligible") is True]
    if eligible_candidates:
        st.markdown("### Selección explícita de contrato")
        contract_labels = {
            f"{item['symbol']} · Ask {item['ask']} · Delta {item.get('delta')}": item
            for item in eligible_candidates
        }
        selected_contract_label = st.selectbox(
            "Contrato elegible", list(contract_labels), key=f"contract_{alert['id']}"
        )
        contract_notes = st.text_input(
            "Notas de selección", key=f"contract_notes_{alert['id']}"
        )
        if st.button("Guardar selección de contrato", key=f"save_contract_{alert['id']}"):
            selection_id = AlertRepository().record_contract_selection(
                alert["id"], contract_labels[selected_contract_label]["symbol"], notes=contract_notes
            )
            st.success(f"Selección de contrato #{selection_id} guardada.")
    contract_selections = AlertRepository().contract_selections(alert["id"])
    if contract_selections:
        st.dataframe(
            pd.DataFrame([{"ID": item["id"], "Fecha": item["created_at"], "Contrato": item["contract_symbol"], "Notas": item["notes"]} for item in contract_selections]),
            width="stretch", hide_index=True,
        )
    st.markdown("### Gobierno operativo")
    governance_columns = st.columns(3)
    governance_mode = governance_columns[0].selectbox(
        "Modo", [item.value for item in TradingMode], key=f"gov_mode_{alert['id']}"
    )
    weekly_count = governance_columns[1].number_input(
        "Entradas nuevas esta semana", min_value=0, step=1, key=f"gov_count_{alert['id']}"
    )
    weekly_limit = governance_columns[2].number_input(
        "Límite semanal", min_value=1, value=3, step=1, key=f"gov_limit_{alert['id']}"
    )
    watchlist_text = st.text_input(
        "Lista autorizada (separada por comas)", value=alert["symbol"], key=f"gov_watchlist_{alert['id']}"
    )
    entry_plan = st.text_area("Plan de entrada", key=f"gov_entry_{alert['id']}")
    exit_plan = st.text_area("Plan de salida", key=f"gov_exit_{alert['id']}")
    real_ack = st.checkbox(
        "Confirmo explícitamente el uso del modo REAL",
        key=f"gov_real_ack_{alert['id']}",
        disabled=governance_mode != TradingMode.REAL.value,
    )
    governance_notes = st.text_input("Notas de gobierno", key=f"gov_notes_{alert['id']}")
    if st.button("Guardar revisión de gobierno", key=f"save_governance_{alert['id']}"):
        governance_id = AlertRepository().record_governance_review(
            alert["id"],
            GovernanceRequest(
                mode=TradingMode(governance_mode), workflow=OperationWorkflow.NUEVA_ENTRADA,
                watchlist_symbols=tuple(item.strip() for item in watchlist_text.split(",") if item.strip()),
                new_trades_this_week=int(weekly_count), entry_plan=entry_plan, exit_plan=exit_plan,
                real_mode_acknowledged=real_ack, symbol=alert["symbol"],
            ),
            limits=GovernanceLimits(max_new_trades_per_week=int(weekly_limit)), notes=governance_notes,
        )
        st.success(f"Revisión de gobierno #{governance_id} guardada.")
    governance_reviews = AlertRepository().governance_reviews(alert["id"])
    if governance_reviews:
        st.dataframe(pd.DataFrame([
            {"ID": item["id"], "Fecha": item["created_at"], "Modo": item["mode"], "Estado": item["status"], "Motivos": " · ".join(item["reasons"])}
            for item in governance_reviews
        ]), width="stretch", hide_index=True)

    st.markdown("### Revisión humana")
    review_values = ["PENDIENTE", "SÍ", "NO"]
    review_columns = st.columns(3)
    path_review = review_columns[0].selectbox(
        "Camino hasta siguiente nivel", review_values, key=f"alert_path_{alert['id']}"
    )
    news_review = review_columns[1].selectbox(
        "Noticias revisadas", review_values, key=f"alert_news_{alert['id']}"
    )
    panorama_review = review_columns[2].selectbox(
        "Panorama general", review_values, key=f"alert_panorama_{alert['id']}"
    )
    review_notes = st.text_area("Notas de revisión", key=f"alert_notes_{alert['id']}")
    if st.button("Guardar revisión de alerta", key=f"save_alert_review_{alert['id']}"):
        values = {"PENDIENTE": None, "SÍ": True, "NO": False}
        try:
            review_id = AlertRepository().record_human_review(
                alert["id"],
                path_clear=values[path_review],
                news_clear=values[news_review],
                panorama_approved=values[panorama_review],
                notes=review_notes,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(f"Revisión #{review_id} guardada sin modificar la alerta original.")
    reviews = AlertRepository().human_reviews(alert["id"])
    if reviews:
        st.dataframe(_alert_reviews_table(reviews), width="stretch", hide_index=True)
        if st.button("Reevaluar con la última revisión", key=f"reevaluate_{alert['id']}"):
            latest_contract = contract_selections[0] if contract_selections else None
            latest_governance = governance_reviews[0] if governance_reviews else None
            payload = reevaluate_alert(
                report,
                reviews[0],
                latest_contract,
                latest_governance,
                visual_audit,
            )
            reevaluation_id = AlertRepository().record_reevaluation(
                alert["id"], reviews[0]["id"], payload
            )
            if reevaluation_id is None:
                st.info("Esta revisión ya fue reevaluada.")
            else:
                st.success(f"Reevaluación #{reevaluation_id} guardada.")
    reevaluations = AlertRepository().reevaluations(alert["id"])
    if reevaluations:
        st.markdown("### Reevaluaciones derivadas")
        st.dataframe(
            pd.DataFrame([
                {"ID": item["id"], "Revisión": item["review_id"], "Contrato": item["contract_selection_id"] or "—", "Gobierno": item["governance_review_id"] or "—", "Fecha": item["created_at"], "Decisión": item["decision"]}
                for item in reevaluations
            ]),
            width="stretch", hide_index=True,
        )
        st.markdown("### Resultado posterior")
        reevaluation_labels = {
            f"#{item['id']} · {item['decision']} · {item['created_at']}": item
            for item in reevaluations
        }
        outcome_reevaluation = st.selectbox(
            "Reevaluación evaluada", list(reevaluation_labels), key=f"outcome_reevaluation_{alert['id']}"
        )
        selected_reevaluation = reevaluation_labels[outcome_reevaluation]
        try:
            derived_outcome_mode = _reevaluation_outcome_mode(
                selected_reevaluation,
                governance_reviews,
            )
        except ValueError as error:
            st.error(str(error))
            derived_outcome_mode = "PAPER"
            outcome_mode_valid = False
        else:
            outcome_mode_valid = True
        outcome_columns = st.columns(3)
        outcome_mode = outcome_columns[0].selectbox(
            "Modo del resultado",
            [derived_outcome_mode],
            disabled=True,
            key=(
                f"outcome_mode_{alert['id']}_"
                f"{selected_reevaluation['id']}"
            ),
        )
        trade_taken = outcome_columns[1].checkbox(
            "Operación tomada", value=True, key=f"outcome_taken_{alert['id']}"
        )
        result_options = ["POSITIVO", "NEGATIVO", "EMPATE"] if trade_taken else ["NO_OPERADA"]
        outcome_result = outcome_columns[2].selectbox(
            "Resultado", result_options, key=f"outcome_result_{alert['id']}"
        )
        has_pnl = st.checkbox("Registrar P&L monetario", key=f"outcome_has_pnl_{alert['id']}", disabled=not trade_taken)
        outcome_pnl = st.number_input(
            "P&L", value=0.0, step=1.0, key=f"outcome_pnl_{alert['id']}", disabled=not has_pnl or not trade_taken
        )
        outcome_notes = st.text_area("Notas del resultado", key=f"outcome_notes_{alert['id']}")
        if st.button(
            "Guardar resultado",
            disabled=not outcome_mode_valid,
            key=f"save_outcome_{alert['id']}",
        ):
            outcome_id = AlertRepository().record_outcome(
                alert["id"], reevaluation_labels[outcome_reevaluation]["id"],
                mode=outcome_mode, trade_taken=trade_taken, result=outcome_result,
                pnl=float(outcome_pnl) if has_pnl and trade_taken else None, notes=outcome_notes,
            )
            st.success(f"Resultado #{outcome_id} guardado como nueva versión.")
    outcomes = AlertRepository().outcomes(alert["id"])
    if outcomes:
        st.dataframe(pd.DataFrame([
            {"ID": item["id"], "Reevaluación": item["reevaluation_id"], "Modo": item["mode"], "Tomada": "SÍ" if item["trade_taken"] else "NO", "Resultado": item["result"], "P&L": item["pnl"], "Fecha": item["created_at"]}
            for item in outcomes
        ]), width="stretch", hide_index=True)
    feedback_summary = summarize_alert_feedback(AlertRepository().alert_learning_records())
    if feedback_summary:
        st.markdown("### Aprendizaje descriptivo de alertas")
        st.caption("PAPER y REAL permanecen separados. Estas métricas no modifican automáticamente las estrategias.")
        st.dataframe(pd.DataFrame(feedback_summary), width="stretch", hide_index=True)
    context_summary = summarize_context_performance(AlertRepository().alert_learning_records())
    if context_summary:
        st.markdown("### Desempeño por contexto")
        st.caption("Una combinación necesita al menos 10 resultados tomados para ser elegible para calibración; aun entonces sigue siendo descriptiva.")
        st.dataframe(pd.DataFrame(context_summary), width="stretch", hide_index=True)
    temporal_summary = evaluate_temporal_stability(AlertRepository().alert_learning_records())
    if temporal_summary:
        st.markdown("### Validación temporal fuera de muestra")
        st.caption("El 70% inicial sirve como referencia y el 30% más reciente como evaluación. No modifica decisiones ni metodología.")
        st.dataframe(pd.DataFrame(temporal_summary), width="stretch", hide_index=True)
        degraded = [item for item in temporal_summary if item["status"] == "DEGRADACION_OBSERVADA"]
        if degraded:
            st.warning("Se observó degradación temporal en una o más combinaciones. Requiere revisión humana; no implica desactivar automáticamente una estrategia.")


def _audit_summary_table(audit: object) -> pd.DataFrame:
    """Resume la auditoria del reporte generado."""
    return pd.DataFrame(
        [
            {
                "Preparacion": str(getattr(audit, "readiness", "")),
                "Aprendizaje PAPER": (
                    "SI" if bool(getattr(audit, "learning_ready", False)) else "NO"
                ),
                "Faltantes": int(getattr(audit, "missing_gate_count", 0))
                + int(getattr(audit, "missing_strategy_count", 0))
                + int(getattr(audit, "missing_invalidation_count", 0)),
                "Bloqueos": int(getattr(audit, "blocker_gate_count", 0))
                + int(getattr(audit, "blocker_invalidation_count", 0))
                + int(getattr(audit, "blocker_detector_count", 0)),
                "Estrategias detectadas": int(getattr(audit, "detected_count", 0)),
                "Confirmadas": int(getattr(audit, "confirmed_count", 0)),
            }
        ]
    )


def _review_queue_table(audit: object) -> pd.DataFrame:
    """Convierte la cola de auditoria en una tabla accionable."""
    rows = []
    for item in build_review_queue((audit,)):
        rows.append(
            {
                "Prioridad": item.priority,
                "Tipo": item.review_type,
                "Fuente": item.source,
                "Evidencia": item.evidence,
                "Simbolo": item.symbol,
                "Paquete": item.package_id or "N/D",
                "Decision": item.decision,
                "Sesgo tentativo": item.tentative_bias or "N/D",
                "Reporte": item.report_path or "N/D",
            }
        )
    return pd.DataFrame(rows)


def _review_queue_upload_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza una cola CSV exportada por el auditor."""
    missing = [field for field in REVIEW_QUEUE_FIELDS if field not in frame.columns]
    if missing:
        raise ValueError(
            "El CSV de cola no tiene columnas requeridas: " + ", ".join(missing)
        )
    rows = []
    for _, item in frame.iterrows():
        rows.append(
            {
                "Prioridad": str(item.get("priority") or ""),
                "Tipo": str(item.get("review_type") or ""),
                "Fuente": str(item.get("source") or ""),
                "Evidencia": str(item.get("evidence") or ""),
                "Simbolo": str(item.get("symbol") or ""),
                "Paquete": str(item.get("package_id") or "N/D"),
                "Readiness": str(item.get("readiness") or ""),
                "Decision": str(item.get("decision") or ""),
                "Sesgo tentativo": str(item.get("tentative_bias") or "N/D"),
                "Reporte": str(item.get("report_path") or "N/D"),
            }
        )
    return pd.DataFrame(rows)


def _filtered_review_queue(
    queue: pd.DataFrame,
    *,
    priorities: list[str],
    review_types: list[str],
    packages: list[str],
) -> pd.DataFrame:
    """Filtra una cola de revision por dimensiones operativas."""
    filtered = queue
    if priorities:
        filtered = filtered[filtered["Prioridad"].isin(priorities)]
    if review_types:
        filtered = filtered[filtered["Tipo"].isin(review_types)]
    if packages:
        filtered = filtered[filtered["Paquete"].isin(packages)]
    return filtered


def _case_intake_upload_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza una hoja de intake generada por el preflight."""
    missing = [field for field in INTAKE_TEMPLATE_FIELDS if field not in frame.columns]
    if missing:
        raise ValueError(
            "El CSV de intake no tiene columnas requeridas: " + ", ".join(missing)
        )
    rows = []
    human_fields = (
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
    for _, item in frame.iterrows():
        pending = []
        for field in human_fields:
            value = str(item.get(field) or "").strip()
            if not value or value in {"PENDIENTE", "NO_DISPONIBLE"}:
                pending.append(field)
        symbol = str(item.get("symbol") or "").strip().upper()
        session = str(item.get("session") or "").strip()
        rows.append(
            {
                "Paquete": f"{symbol}_{session}" if symbol and session else "N/D",
                "Simbolo": symbol,
                "Sesion": session,
                "TC2000": str(item.get("tc2000_export_checked") or ""),
                "Setup a revisar": str(item.get("primary_setup_to_review") or ""),
                "Revisiones pendientes": str(item.get("manual_reviews_pending") or ""),
                "Riesgo": str(item.get("risk_review_status") or ""),
                "Gobierno": str(item.get("governance_review_status") or ""),
                "Paper trade": str(item.get("paper_trade_taken") or ""),
                "Resultado paper": str(item.get("paper_trade_result") or ""),
                "Notas": str(item.get("operator_notes") or ""),
                "Pendientes intake": len(pending),
                "Campos pendientes": " | ".join(pending),
            }
        )
    return pd.DataFrame(rows)


def _operator_board_upload_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza el tablero operativo generado por el batch."""
    missing = [field for field in OPERATOR_BOARD_FIELDS if field not in frame.columns]
    if missing:
        raise ValueError(
            "El CSV de tablero no tiene columnas requeridas: " + ", ".join(missing)
        )
    rows = []
    for _, item in frame.iterrows():
        rows.append(
            {
                "Paquete": str(item.get("package_id") or "N/D"),
                "Simbolo": str(item.get("symbol") or ""),
                "Sesion": str(item.get("session") or ""),
                "Decision": str(item.get("decision") or ""),
                "Readiness": str(item.get("readiness") or ""),
                "Learning ready": str(item.get("learning_ready") or ""),
                "Sesgo tentativo": str(item.get("tentative_bias") or "N/D"),
                "Detectadas": str(item.get("detected_count") or "0"),
                "Confirmadas": str(item.get("confirmed_count") or "0"),
                "Faltantes": str(item.get("missing_total") or "0"),
                "Bloqueos": str(item.get("blocker_total") or "0"),
                "Primer pendiente": str(item.get("first_missing_evidence") or ""),
                "Primer bloqueo": str(item.get("first_blocker") or ""),
                "Calidad": str(item.get("data_quality") or ""),
                "Panorama": str(item.get("panorama") or ""),
                "Riesgo": str(item.get("risk") or ""),
                "Gobierno": str(item.get("governance") or ""),
                "Temporalidades": str(item.get("timeframes") or ""),
                "Reporte": str(item.get("report_path") or ""),
            }
        )
    return pd.DataFrame(rows)


def _render_review_queue_controls(queue: pd.DataFrame, *, key_prefix: str) -> None:
    """Muestra filtros y descarga para una cola de revision."""
    if queue.empty:
        st.success("No hay faltantes ni bloqueos para poner en cola.")
        return
    queue_columns = st.columns(3)
    priority_options = sorted(queue["Prioridad"].dropna().unique())
    type_options = sorted(queue["Tipo"].dropna().unique())
    package_options = sorted(queue["Paquete"].dropna().unique())
    selected_priorities = queue_columns[0].multiselect(
        "Prioridad",
        priority_options,
        default=priority_options,
        key=f"{key_prefix}_priority_filter",
    )
    selected_types = queue_columns[1].multiselect(
        "Tipo",
        type_options,
        default=type_options,
        key=f"{key_prefix}_type_filter",
    )
    selected_packages = queue_columns[2].multiselect(
        "Paquete",
        package_options,
        default=package_options,
        key=f"{key_prefix}_package_filter",
    )
    filtered_queue = _filtered_review_queue(
        queue,
        priorities=selected_priorities,
        review_types=selected_types,
        packages=selected_packages,
    )
    st.dataframe(filtered_queue, width="stretch", hide_index=True)
    st.download_button(
        "Descargar cola CSV",
        data=filtered_queue.to_csv(index=False).encode("utf-8"),
        file_name="review_queue_filtrada.csv",
        mime="text/csv",
        key=f"{key_prefix}_download",
    )


def _recent_analyses_table(analyses: list[dict[str, object]]) -> pd.DataFrame:
    """Resume analisis guardados con auditoria y fuente de datos."""
    rows = []
    for item in analyses:
        missing_count = (
            int(item.get("audit_missing_gate_count", 0))
            + int(item.get("audit_missing_strategy_count", 0))
            + int(item.get("audit_missing_invalidation_count", 0))
        )
        blocker_count = (
            int(item.get("audit_blocker_gate_count", 0))
            + int(item.get("audit_blocker_invalidation_count", 0))
            + int(item.get("audit_blocker_detector_count", 0))
        )
        rows.append(
            {
                "ID": item.get("id", ""),
                "Creado": item.get("created_at", ""),
                "Simbolo": item.get("symbol", ""),
                "Data as of": item.get("data_as_of", ""),
                "Decision": item.get("decision", ""),
                "Confianza": item.get("confidence", ""),
                "Auditoria": item.get("audit_readiness", "") or "N/D",
                "Learning ready": (
                    "SI" if bool(item.get("audit_learning_ready", False)) else "NO"
                ),
                "Faltantes": missing_count,
                "Bloqueos": blocker_count,
                "Fuente datos": item.get("data_provider", "") or "N/D",
                "TF fuente": item.get("data_source_timeframes", "") or "N/D",
                "Sesgo tentativo": item.get("tentative_bias", "") or "N/D",
                "Estrategias tentativas": item.get("tentative_strategies", "") or "N/D",
            }
        )
    return pd.DataFrame(rows)


def _filtered_recent_analyses(
    analyses: pd.DataFrame,
    *,
    symbols: list[str],
    decisions: list[str],
    audit_states: list[str],
) -> pd.DataFrame:
    """Filtra analisis guardados sin modificar el orden original."""
    filtered = analyses
    if symbols:
        filtered = filtered[filtered["Simbolo"].isin(symbols)]
    if decisions:
        filtered = filtered[filtered["Decision"].isin(decisions)]
    if audit_states:
        filtered = filtered[filtered["Auditoria"].isin(audit_states)]
    return filtered


def _report_audits_table(audits: list[dict[str, object]]) -> pd.DataFrame:
    """Resume auditorias guardadas con pendientes principales."""
    rows = []
    for item in audits:
        rows.append(
            {
                "ID": item["id"],
                "Creada": item["created_at"],
                "Simbolo": item["symbol"],
                "Data as of": item["data_as_of"],
                "Decision": item["decision"],
                "Estado": item["readiness"],
                "Learning ready": "SI" if item["learning_ready"] else "NO",
                "App": item["app_version"] or "N/D",
                "Metodologia": item["methodology_version"] or "N/D",
                "Paquete": item["package_id"] or "N/D",
                "Sesion paquete": item["package_session"] or "N/D",
                "TF paquete": item["package_timeframes"] or "N/D",
                "Fuente datos": item["data_provider"] or "N/D",
                "TF fuente": item["data_source_timeframes"] or "N/D",
                "Calidad": item["data_quality_status"] or "N/D",
                "Panorama": item["panorama_status"] or "N/D",
                "Riesgo": item["risk_status"] or "N/D",
                "Gobierno": item["governance_status"] or "N/D",
                "Sesgo tentativo": item["tentative_bias"] or "N/D",
                "Estrategias tentativas": item["tentative_strategies"] or "N/D",
                "Evaluados": item["evaluated_count"],
                "Detectados": item["detected_count"],
                "Confirmados": item["confirmed_count"],
                "Omitidos": item["skipped_count"],
                "Errores": item["error_count"],
                "Estrategias": ", ".join(item["detected_strategies"]),
                "Pendientes": len(item["missing_evidence"]),
                "Primer pendiente": item["first_missing_evidence"]
                or _first_text_or_na(item["missing_evidence"]),
                "Pend. compuertas": item["missing_gate_count"],
                "Pend. estrategias": item["missing_strategy_count"],
                "Pend. invalidaciones": item["missing_invalidation_count"],
                "Bloqueos": len(item["blockers"]),
                "Primer bloqueo": item["first_blocker"]
                or _first_text_or_na(item["blockers"]),
                "Bloq. compuertas": item["blocker_gate_count"],
                "Bloq. invalidaciones": item["blocker_invalidation_count"],
                "Bloq. detectores": item["blocker_detector_count"],
            }
        )
    return pd.DataFrame(rows)


def _filtered_report_audits(
    audits: pd.DataFrame,
    *,
    symbols: list[str],
    readiness: list[str],
    packages: list[str],
) -> pd.DataFrame:
    """Filtra auditorias guardadas por dimensiones de revision."""
    filtered = audits
    if symbols:
        filtered = filtered[filtered["Simbolo"].isin(symbols)]
    if readiness:
        filtered = filtered[filtered["Estado"].isin(readiness)]
    if packages:
        filtered = filtered[filtered["Paquete"].isin(packages)]
    return filtered


def _closed_trades_table(trades: list[dict[str, object]]) -> pd.DataFrame:
    """Resume operaciones cerradas sin reinterpretar la metodologia."""
    rows = []
    for item in trades:
        pnl = float(item.get("pnl") or 0)
        decision_followed = item.get("decision_followed")
        rows.append(
            {
                "ID": item.get("id", ""),
                "Analisis": item.get("analysis_id", ""),
                "Simbolo": item.get("symbol", ""),
                "Data as of": item.get("data_as_of", ""),
                "Decision analisis": item.get("decision", ""),
                "Accion": item.get("action", ""),
                "Modo": item.get("mode", ""),
                "Flujo": item.get("workflow", ""),
                "Abierta": item.get("opened_at", ""),
                "Cerrada": item.get("closed_at", ""),
                "Contratos": item.get("contracts", ""),
                "Entrada": item.get("entry_price", ""),
                "Salida": item.get("exit_price", ""),
                "Comisiones": item.get("fees", ""),
                "PnL": round(pnl, 2),
                "Resultado": (
                    "GANADORA" if pnl > 0 else "PERDEDORA" if pnl < 0 else "TABLAS"
                ),
                "Siguio decision": "SI" if bool(decision_followed) else "NO",
                "Excepcion": item.get("override_reason", "") or "N/D",
                "Estrategias": ", ".join(
                    str(value) for value in item.get("strategies", [])
                ),
            }
        )
    return pd.DataFrame(rows)


def _filtered_closed_trades(
    trades: pd.DataFrame,
    *,
    modes: list[str],
    symbols: list[str],
    decisions: list[str],
) -> pd.DataFrame:
    """Filtra operaciones cerradas por dimensiones operativas."""
    filtered = trades
    if modes:
        filtered = filtered[filtered["Modo"].isin(modes)]
    if symbols:
        filtered = filtered[filtered["Simbolo"].isin(symbols)]
    if decisions:
        filtered = filtered[filtered["Decision analisis"].isin(decisions)]
    return filtered


def _closed_trade_comparison_table(trades: pd.DataFrame) -> pd.DataFrame:
    """Agrega resultados cerrados por modo y seguimiento de decision."""
    if trades.empty:
        return pd.DataFrame()
    rows = []
    for (mode, followed), frame in trades.groupby(["Modo", "Siguio decision"]):
        operations = len(frame)
        wins = int((frame["PnL"] > 0).sum())
        total_pnl = round(float(frame["PnL"].sum()), 2)
        rows.append(
            {
                "Modo": mode,
                "Siguio decision": followed,
                "Operaciones": operations,
                "Ganadoras": wins,
                "Win rate": round(wins / operations * 100, 2),
                "PnL total": total_pnl,
                "PnL promedio": round(total_pnl / operations, 2),
            }
        )
    return pd.DataFrame(rows).sort_values(["Modo", "Siguio decision"])


def _first_text_or_na(value: object) -> str:
    """Devuelve el primer texto útil de una lista o N/D."""
    if isinstance(value, str):
        return value or "N/D"
    if isinstance(value, (list, tuple)):
        for item in value:
            if item:
                return str(item)
    return "N/D"


def _analysis_requires_override_reason(analysis: Mapping[str, object]) -> bool:
    """Indica si el analisis seleccionado requiere excepcion documentada."""
    return str(analysis.get("audit_readiness") or "") in {
        "INCOMPLETO",
        "BLOQUEADO",
    }


def _optional_review(label: str, *, key: str) -> bool | None:
    """Solicita una revisión ternaria sin confundir pendiente con rechazo."""
    value = st.selectbox(label, ["PENDIENTE", "SÍ", "NO"], key=key)
    return {"PENDIENTE": None, "SÍ": True, "NO": False}[value]


def _record_common_news_review(
    reviews: dict[str, bool | None], value: bool | None
) -> None:
    """Conserva una revisión explícita de noticias aunque otra sección quede pendiente."""
    if value is not None or "common.news_clear" not in reviews:
        reviews["common.news_clear"] = value


def _effective_common_news_review(
    reviews: dict[str, bool | None], fallback: bool | None
) -> bool | None:
    """Devuelve la revisión común de noticias que debe alimentar compuertas."""
    return reviews.get("common.news_clear", fallback)


def render_analysis() -> None:
    """Carga TC2000 y presenta el análisis implementado actualmente."""
    st.subheader("Análisis de activo")
    st.info(
        "Radar metodológico: los detectores implementados se evalúan con "
        "trazabilidad, y las estrategias parciales conservan sus revisiones "
        "obligatorias antes de cualquier decisión."
    )

    symbol = st.text_input("Símbolo", value="SPY").strip().upper()
    use_demo = st.checkbox(
        "Usar demostración sintética",
        help="Datos educativos generados localmente; no representan el mercado.",
    )
    use_alpaca = st.checkbox(
        "Usar datos de mercado Alpaca",
        help="Actualiza historial real de solo lectura usando credenciales del entorno.",
    )
    if use_demo and use_alpaca:
        st.error("Selecciona demostración o Alpaca, no ambas fuentes simultáneamente.")
        return
    if use_alpaca:
        lookback_days = st.number_input(
            "Historial Alpaca (días naturales)",
            min_value=30,
            max_value=730,
            value=365,
            step=30,
        )
        if st.button("Actualizar datos Alpaca", type="primary"):
            try:
                with st.spinner("Recuperando barras y reconstruyendo temporalidades..."):
                    config = AlpacaMarketConfig.from_env()
                    provider = AlpacaMarketDataProvider(config)
                    store = MarketBarStore()
                    continuity = MarketContinuityService(
                        store, provider, provider_name="ALPACA", feed=config.feed
                    )
                    end = datetime.now(timezone.utc)
                    continuity.recover(
                        symbol,
                        end=end,
                        initial_lookback=timedelta(days=int(lookback_days)),
                    )
                    minute_bars = store.load_frame(
                        symbol=symbol, provider="ALPACA", feed=config.feed
                    )
                    if minute_bars.empty:
                        raise ValueError("No hay barras Alpaca almacenadas para el símbolo.")
                    sessions = AlpacaMarketCalendarProvider(config).fetch_sessions(
                        (end - timedelta(days=int(lookback_days))).date(),
                        (end + timedelta(days=30)).date(),
                    )
                    st.session_state["alpaca_analysis_bundle"] = build_alpaca_data_bundle(
                        minute_bars,
                        symbol=symbol,
                        feed=config.feed,
                        session_closes=session_close_map(sessions),
                    )
                    st.session_state["alpaca_analysis_identity"] = (symbol, config.feed)
            except (ValueError, OSError) as error:
                st.error(str(error))
        live_bundle = st.session_state.get("alpaca_analysis_bundle")
        identity = st.session_state.get("alpaca_analysis_identity")
        if live_bundle is None or not identity or identity[0] != symbol:
            st.caption("Pulsa Actualizar datos Alpaca para cargar este símbolo.")
            return
    upload_columns = st.columns(3)
    uploads = {
        "15m": upload_columns[0].file_uploader(
            "TC2000 · 15 minutos", type=["txt", "csv"], key="upload_15m"
        ),
        "1H": upload_columns[1].file_uploader(
            "TC2000 · Hora", type=["txt", "csv"], key="upload_1h"
        ),
        "1D": upload_columns[2].file_uploader(
            "TC2000 · Diario", type=["txt", "csv"], key="upload_1d"
        ),
    }
    available_uploads = {
        timeframe: uploaded
        for timeframe, uploaded in uploads.items()
        if uploaded is not None
    }
    if not available_uploads and not use_demo and not use_alpaca:
        st.caption("Carga al menos una exportación para comenzar.")
        return

    try:
        datasets: dict[str, pd.DataFrame] = {}
        evaluations = {}
        if use_demo:
            data_bundle = build_demo_data_bundle(generate_demo_datasets())
        elif use_alpaca:
            data_bundle = st.session_state["alpaca_analysis_bundle"]
        else:
            data_bundle = load_tc2000_upload_data_bundle(available_uploads)
        datasets = dict(data_bundle.datasets)
        data_source = data_source_metadata(data_bundle)
        for timeframe, dataset in datasets.items():
            datasets[timeframe] = dataset
            evaluations[timeframe] = evaluate_expuesto_bollinger(dataset)
    except (ValueError, FileNotFoundError, pd.errors.ParserError) as error:
        st.error(str(error))
        return

    if use_demo:
        st.warning(
            "DEMOSTRACIÓN SINTÉTICA: resultados educativos; no corresponden "
            "a una compañía ni deben utilizarse para operar."
        )

    preferred_timeframe = next(
        timeframe for timeframe in ("15m", "1H", "1D") if timeframe in datasets
    )
    df = datasets[preferred_timeframe]
    strategy = evaluations[preferred_timeframe]
    latest = df.iloc[-1]
    data_quality = evaluate_data_quality(datasets)
    if data_quality.status is GateStatus.RECHAZADO:
        st.error("Calidad de datos: RECHAZADA. La decisión permanecerá bloqueada.")
        for issue in data_quality.issues:
            st.write(f"- {issue}")
    else:
        st.success("Calidad de datos: APROBADA")
    st.dataframe(_data_source_table(data_source), width="stretch", hide_index=True)
    if data_quality.latest_sessions:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Temporalidad": timeframe,
                        "Ultima sesion": session,
                        "Velas": data_quality.candle_counts.get(timeframe, 0),
                    }
                    for timeframe, session in sorted(data_quality.latest_sessions.items())
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    col1, col2, col3 = st.columns(3)
    col1.metric("Última fecha", f"{latest['date']:%Y-%m-%d}")
    col2.metric("Último cierre", f"{latest['close']:.2f}")
    col3.metric(
        f"Cumplimiento detector ({preferred_timeframe})",
        f"{strategy.compliance_percentage:.2f}%",
    )

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Temporalidad": timeframe,
                    "Última fecha": f"{dataset.iloc[-1]['date']:%Y-%m-%d %H:%M}",
                    "Close": round(float(dataset.iloc[-1]["close"]), 2),
                    "Estado": evaluation.strategy_id,
                    "Sesgo": evaluation.bias.value,
                }
                for timeframe, dataset in datasets.items()
                for evaluation in [evaluations[timeframe]]
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    missing_timeframes = [
        timeframe for timeframe in ("15m", "1H", "1D") if timeframe not in datasets
    ]
    if missing_timeframes:
        st.warning(
            "Panorama incompleto. Faltan temporalidades: "
            + ", ".join(missing_timeframes)
        )
    else:
        st.info(
            "Las tres temporalidades están disponibles. El motor de panorama "
            "aún requiere umbrales metodológicos antes de aprobarlas."
        )

    chart = df.set_index("date")[[
        "close",
        "bollinger_mid",
        "bollinger_upper",
        "bollinger_lower",
    ]]
    st.line_chart(chart)

    st.markdown(f"### {strategy.name} · {preferred_timeframe}")
    st.write(f"Sesgo inicial: **{strategy.bias.value}**")
    st.dataframe(_criteria_table(strategy), width="stretch", hide_index=True)

    strategy_evaluations = [strategy]
    reviews: dict[str, bool | None] = {}
    session_closed = False
    if "15m" in datasets:
        with st.expander("Detector en validación · CT15"):
            ct_left, ct_right = st.columns(2)
            with ct_left:
                ct_trend = _optional_review(
                    "Tendencia previa válida para CT15", key="ct15_prior_trend"
                )
                ct_line = _optional_review(
                    "Línea trazada por el lado correcto", key="ct15_line_drawn"
                )
            with ct_right:
                ct_break = _optional_review(
                    "El salto rompió la línea de tendencia", key="ct15_line_break"
                )
            reviews.update(
                {
                    "ct15.prior_trend": ct_trend,
                    "ct15.trendline_drawn": ct_line,
                    "ct15.trendline_broken": ct_break,
                }
            )
            try:
                ct15_evaluation = evaluate_ct15(
                    datasets["15m"],
                    hourly=datasets.get("1H"),
                    daily=datasets.get("1D"),
                    prior_trend_valid=ct_trend,
                    trendline_drawn_correctly=ct_line,
                    trendline_broken=ct_break,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{ct15_evaluation.name}**")
                st.write(f"Sesgo observado: **{ct15_evaluation.bias.value}**")
                st.dataframe(
                    _criteria_table(ct15_evaluation),
                    width="stretch",
                    hide_index=True,
                )
                if ct15_evaluation.detected:
                    strategy_evaluations.append(ct15_evaluation)

        with st.expander("Detector en validación · Retorno a Bollinger"):
            st.caption("Lateralidad, compresión y excepcionalidad se calculan con el historial del símbolo.")
            fast_reversal = _optional_review(
                "Reversión observada en los primeros minutos",
                key="return_fast_reversal",
            )
            reviews.update(
                {
                    "return.fast_reversal": fast_reversal,
                }
            )
            try:
                return_evaluation = evaluate_retorno_bollinger_lateral(
                    datasets["15m"],
                    reversal_within_first_minutes=fast_reversal,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{return_evaluation.name}**")
                st.write(f"Sesgo observado: **{return_evaluation.bias.value}**")
                st.dataframe(
                    _criteria_table(return_evaluation),
                    width="stretch",
                    hide_index=True,
                )
                if return_evaluation.detected:
                    strategy_evaluations.append(return_evaluation)

    if "1H" in datasets and "1D" in datasets and len(datasets["1D"]) >= 6:
        with st.expander("Detector en validación · Primer Salto"):
            st.caption(
                "Reconoce un salto diario respetado. No predice su magnitud ni "
                "autoriza por sí solo una entrada para el salto siguiente."
            )
            session_closed = st.checkbox(
                "Confirmo que la última vela diaria está cerrada",
                key="jump_session_closed",
            )
            st.caption("Tendencia de cinco días, línea y confirmación horaria se calculan automáticamente.")
            news = _optional_review(
                "Calendario sin noticia invalidante", key="jump_news"
            )
            path = _optional_review(
                "Camino limpio al siguiente nivel", key="jump_path"
            )
            reviews.update(
                {
                    "jump.path_clear": path,
                }
            )
            _record_common_news_review(reviews, news)

            jump_evaluation = evaluate_first_jump_setup(
                datasets["1D"],
                hourly=datasets["1H"],
                session_closed=session_closed,
                news_clear=news,
                path_clear=path,
            )
            st.write(f"Resultado: **{jump_evaluation.name}**")
            st.write(f"Sesgo observado: **{jump_evaluation.bias.value}**")
            st.dataframe(
                _criteria_table(jump_evaluation),
                width="stretch",
                hide_index=True,
            )
            if jump_evaluation.detected:
                strategy_evaluations.append(jump_evaluation)
    elif "1D" in datasets:
        st.warning("Primer Salto requiere al menos dos sesiones diarias.")

    if "1H" in datasets:
        with st.expander("Detector en validación · Salto de Lateralidad en Hora"):
            st.caption(
                "Evalúa continuidad desde una lateralidad de Hora. La ruptura "
                "puede confirmarse con vela cerrada o salto, pero no estima "
                "la magnitud del movimiento."
            )
            st.caption("Canal, ruptura, distancia a MA20 y volatilidad se calculan automáticamente.")
            lateral_news = _optional_review(
                "Calendario sin noticia invalidante",
                key="lateral_jump_news",
            )
            lateral_path = _optional_review(
                "Camino limpio al siguiente techo o piso",
                key="lateral_jump_path",
            )
            reviews.update(
                {
                    "lateral_jump.path_clear": lateral_path,
                }
            )
            _record_common_news_review(reviews, lateral_news)
            try:
                lateral_jump = evaluate_salto_lateralidad_hora(
                    datasets["1H"],
                    news_clear=lateral_news,
                    path_clear=lateral_path,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{lateral_jump.name}**")
                st.write(f"Sesgo observado: **{lateral_jump.bias.value}**")
                st.dataframe(_criteria_table(lateral_jump), width="stretch", hide_index=True)
                if lateral_jump.detected:
                    strategy_evaluations.append(lateral_jump)

        with st.expander("Detector en validación · Cambio de Tendencia en Hora"):
            st.caption("Tendencia de dos días, línea, ruptura, cierre y alineación 15m se calculan automáticamente.")
            try:
                hour_change = evaluate_cambio_tendencia_hora(
                    datasets["1H"],
                    intraday_15m=datasets["15m"],
                    hourly_candle_closed=True,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{hour_change.name}**")
                st.dataframe(_criteria_table(hour_change), width="stretch", hide_index=True)
                if hour_change.detected:
                    strategy_evaluations.append(hour_change)

    if "1H" in datasets and "1D" in datasets:
        with st.expander("Detector en validación · Momentum"):
            st.caption("La tendencia previa, la estructura 100/200 y las rupturas cerradas se calculan automáticamente.")
            momentum_path = _optional_review("Camino limpio al siguiente nivel", key="momentum_path")
            reviews["momentum.path_clear"] = momentum_path
            try:
                momentum = evaluate_momentum(
                    datasets["1H"], datasets["1D"],
                    path_clear=momentum_path,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{momentum.name}**")
                st.dataframe(_criteria_table(momentum), width="stretch", hide_index=True)
                if momentum.detected:
                    strategy_evaluations.append(momentum)

    if all(timeframe in datasets for timeframe in ("15m", "1H", "1D")):
        with st.expander("Detector en validación · Efecto Imán"):
            st.caption(
                "Combina la primera vela de 15m, medias 20/40 de Hora y el "
                "salto diario. El sesgo apunta hacia MA20 de Hora."
            )
            st.caption(
                "Tendencia, distancia anormal y camino entre medias se calculan automáticamente."
            )
            worden_cross = _optional_review(
                "Volumen de Hora cruzó la línea roja de Worden",
                key="magnet_worden_cross",
            )
            reviews.update(
                {
                    "magnet.worden_volume_cross": worden_cross,
                }
            )
            try:
                magnet_evaluation = evaluate_efecto_iman(
                    datasets["15m"],
                    datasets["1H"],
                    datasets["1D"],
                    worden_volume_crossed=worden_cross,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{magnet_evaluation.name}**")
                st.write(f"Sesgo observado: **{magnet_evaluation.bias.value}**")
                st.dataframe(
                    _criteria_table(magnet_evaluation),
                    width="stretch",
                    hide_index=True,
                )
                if magnet_evaluation.detected:
                    strategy_evaluations.append(magnet_evaluation)

        with st.expander("Detector en validación · Rebote en Punto Medio"):
            bounce_left, bounce_right = st.columns(2)
            with bounce_left:
                st.caption("El acercamiento de tres días se calcula automáticamente.")
                midpoint_respected = _optional_review(
                    "Override respeto del Punto Medio Diario en 15m",
                    key="bounce_midpoint_respected",
                )
            with bounce_right:
                hourly_closed = st.checkbox(
                    "Confirmo que la vela de Hora evaluada está cerrada",
                    key="bounce_hourly_closed",
                )
            reviews.update(
                {
                    "bounce.midpoint_respected": midpoint_respected,
                    "bounce.hourly_candle_closed": hourly_closed,
                }
            )
            try:
                bounce_evaluation = evaluate_rebote_punto_medio(
                    datasets["15m"],
                    datasets["1H"],
                    datasets["1D"],
                    midpoint_respected_in_15m=midpoint_respected,
                    hourly_candle_closed=hourly_closed,
                )
            except ValueError as error:
                st.warning(str(error))
            else:
                st.write(f"Resultado: **{bounce_evaluation.name}**")
                st.write(f"Sesgo observado: **{bounce_evaluation.bias.value}**")
                st.dataframe(
                    _criteria_table(bounce_evaluation),
                    width="stretch",
                    hide_index=True,
                )
                if bounce_evaluation.detected:
                    strategy_evaluations.append(bounce_evaluation)

    st.markdown("### Panorama general")
    panorama_left, panorama_right = st.columns(2)
    with panorama_left:
        panorama_path = _optional_review(
            "Espacio libre hasta el siguiente nivel", key="panorama_path"
        )
        panorama_news = _optional_review(
            "Calendario sin noticia invalidante", key="panorama_news"
        )
    with panorama_right:
        panorama_approval = _optional_review(
            "Apruebo el panorama después de revisar los gráficos",
            key="panorama_approval",
        )
        data_current = _optional_review(
            "Los archivos corresponden al mismo análisis vigente",
            key="panorama_data_current",
        )

    _record_common_news_review(reviews, panorama_news)
    effective_news_clear = _effective_common_news_review(reviews, panorama_news)
    risk_status = (
        st.session_state["risk_status"]
        if st.session_state.get("risk_symbol") == symbol
        else GateStatus.NO_DISPONIBLE
    )
    governance_status = st.session_state["governance_status"]
    if governance_status is GateStatus.APROBADO and (
        symbol not in st.session_state.get("governance_watchlist", ())
        or st.session_state.get("governance_workflow") != "NUEVA_ENTRADA"
    ):
        governance_status = GateStatus.RECHAZADO
    assessment = assess_market(
        AnalysisContext(
            datasets=datasets,
            reviews=reviews,
            session_closed=session_closed,
        ),
        panorama_path_clear=panorama_path,
        news_clear=effective_news_clear,
        panorama_human_approval=panorama_approval,
        data_current_review=data_current,
        risk_status=risk_status,
        risk_option_type=st.session_state.get("risk_option_type"),
        governance_status=governance_status,
    )
    strategy_evaluations = list(assessment.pipeline.evaluations)
    panorama = assessment.panorama
    level_map = assessment.levels
    invalidations = assessment.invalidations
    decision = assessment.decision

    st.markdown("### Radar de detectores")
    radar_metrics = st.columns(4)
    radar_metrics[0].metric("Ejecutados", len(strategy_evaluations))
    radar_metrics[1].metric(
        "Detectados", sum(item.detected for item in strategy_evaluations)
    )
    radar_metrics[2].metric(
        "Confirmados",
        sum(item.required_criteria_satisfied for item in strategy_evaluations),
    )
    radar_metrics[3].metric("Omitidos", len(assessment.pipeline.skipped))
    st.dataframe(
        _strategy_radar_table(strategy_evaluations),
        width="stretch",
        hide_index=True,
    )
    if assessment.pipeline.skipped:
        with st.expander("Detectores omitidos por datos faltantes"):
            st.dataframe(
                _skipped_detectors_table(assessment.pipeline.skipped),
                width="stretch",
                hide_index=True,
            )

    if assessment.pipeline.errors:
        with st.expander("Detectores no evaluables"):
            for detector_id, error in assessment.pipeline.errors.items():
                st.write(f"- {detector_id}: {error}")

    if level_map:
        st.markdown("#### Medias móviles en el recorrido")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Temporalidad": level.timeframe,
                        "Media": level.period,
                        "Valor": round(level.value, 4),
                        "Distancia %": round(level.distance_pct, 2),
                        "Delante del sesgo": "SÍ" if level.ahead_of_bias else "NO",
                    }
                    for level in level_map
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    st.write(f"Estado del panorama: **{panorama.status.value}**")
    st.write(f"Dirección técnica observada: **{panorama.dominant_direction.value}**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Temporalidad": item.timeframe,
                    "Dirección": item.direction.value,
                    "Bollinger": item.bollinger_location.value,
                    "Close": item.close,
                    "MA20": item.ma20,
                    "MA40": item.ma40,
                    "Abriendo volatilidad": item.volatility_opening,
                }
                for item in panorama.snapshots
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    for message in (*panorama.conflicts, *panorama.reasons):
        st.write(f"- {message}")

    st.markdown("### Invalidaciones")
    st.dataframe(
        _criteria_table(invalidations),
        width="stretch",
        hide_index=True,
    )

    gate_columns = st.columns(4)
    gate_columns[0].metric("Calidad", decision.data_quality_status.value)
    gate_columns[1].metric("Panorama", panorama.status.value)
    gate_columns[2].metric("Riesgo", decision.risk_status.value)
    gate_columns[3].metric(
        "Plan operativo", decision.governance_status.value
    )
    if decision.decision.value == "NO_OPERAR":
        st.warning("Recomendación asistida: NO OPERAR")
    else:
        st.success(f"Recomendación asistida: {decision.decision.value}")
    if decision.supporting_strategies:
        st.markdown("#### Estrategias que sostienen la dirección")
        st.dataframe(
            pd.DataFrame({"Estrategia": decision.supporting_strategies}),
            width="stretch",
            hide_index=True,
        )
    elif decision.tentative_strategies and decision.tentative_bias is not None:
        st.markdown(
            f"#### Sesgo tentativo hacia {decision.tentative_bias.value}"
        )
        st.dataframe(
            pd.DataFrame({"Estrategia": decision.tentative_strategies}),
            width="stretch",
            hide_index=True,
        )
    st.markdown("#### Razones")
    for reason in decision.reasons:
        st.write(f"- {reason}")

    report = build_analysis_report(
        symbol=symbol,
        data_as_of=f"{latest['date']:%Y-%m-%d %H:%M}",
        methodology_version=METHODOLOGY_VERSION,
        app_version=APP_VERSION,
        strategies={
            "evaluations": assessment.pipeline.evaluations,
            "skipped": assessment.pipeline.skipped,
            "errors": assessment.pipeline.errors,
        },
        panorama=panorama,
        invalidations=invalidations,
        levels=level_map,
        data_quality=data_quality,
        risk=st.session_state.get("risk_evaluation"),
        governance=st.session_state.get("governance_evaluation"),
        decision=decision,
        data_source=data_source,
    )
    report_audit = audit_report(report, report_path=f"{symbol}_{latest['date']:%Y%m%d}")
    st.markdown("### Auditoria inmediata")
    st.dataframe(_audit_summary_table(report_audit), width="stretch", hide_index=True)
    if report_audit.readiness == "BLOQUEADO":
        st.error("El reporte tiene bloqueos que deben resolverse antes de usarlo.")
    elif report_audit.readiness == "INCOMPLETO":
        st.warning("El reporte requiere evidencia adicional antes de considerarse completo.")
    else:
        st.success("El reporte esta listo para revision humana documentada.")
    with st.expander("Evidencia faltante y bloqueos"):
        if report_audit.missing_evidence:
            st.dataframe(
                pd.DataFrame({"Evidencia faltante": report_audit.missing_evidence}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No hay evidencia faltante registrada.")
        if report_audit.blockers:
            st.dataframe(
                pd.DataFrame({"Bloqueos": report_audit.blockers}),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No hay bloqueos registrados.")
    st.download_button(
        "Exportar reporte JSON",
        data=report_to_json(report),
        file_name=f"{symbol}_{latest['date']:%Y%m%d}_jjtrade.json",
        mime="application/json",
    )

    if st.button("Guardar análisis en el diario"):
        analysis_id = JournalRepository().record_analysis(
            symbol=symbol,
            data_as_of=f"{latest['date']:%Y-%m-%d %H:%M}",
            methodology_version=METHODOLOGY_VERSION,
            decision=decision.decision.value,
            confidence=decision.confidence,
            strategies=[
                _strategy_evaluation_label(item)
                for item in strategy_evaluations
                if item.detected
            ],
            payload={
                **report,
                "loaded_timeframes": list(datasets),
                "report_audit": asdict(report_audit),
            },
        )
        st.success(f"Análisis #{analysis_id} guardado localmente.")


def render_risk() -> None:
    """Evalúa manualmente una cotización con límites explícitos."""
    st.subheader("Riesgo y contrato de opciones")
    st.warning(
        "Estos límites deben provenir de tu plan aprobado. La app no propone "
        "valores ni ejecuta órdenes. Un contrato expirado se rechaza siempre."
    )

    left, right = st.columns(2)
    with left:
        symbol = st.text_input("Activo subyacente", value="SPY")
        option_type = st.selectbox("Tipo", ["CALL", "PUT"])
        spot = st.number_input("Spot", min_value=0.01, value=600.0)
        strike = st.number_input("Strike", min_value=0.01, value=600.0)
        bid = st.number_input("Bid", min_value=0.0, value=1.00)
        ask = st.number_input("Ask", min_value=0.01, value=1.05)
        expiration = st.date_input("Expiración", value=date.today() + timedelta(days=7))
        contracts = st.number_input("Contratos", min_value=1, value=1, step=1)

    with right:
        use_max_spread = st.checkbox("Tengo un límite aprobado de spread absoluto")
        max_spread = st.number_input(
            "Spread máximo", min_value=0.0, value=0.0, disabled=not use_max_spread
        )
        use_max_spread_pct = st.checkbox("Tengo un límite aprobado de spread porcentual")
        max_spread_pct = st.number_input(
            "Spread máximo (%)", min_value=0.0, value=0.0, disabled=not use_max_spread_pct
        )
        use_max_distance = st.checkbox("Tengo un límite aprobado de distancia spot/strike")
        max_distance = st.number_input(
            "Distancia spot/strike máxima (%)", min_value=0.0, value=0.0, disabled=not use_max_distance
        )
        use_min_dte = st.checkbox("Tengo un vencimiento mínimo aprobado")
        min_dte = st.number_input(
            "Días mínimos al vencimiento", min_value=0, value=0, step=1, disabled=not use_min_dte
        )
        use_max_cost = st.checkbox("Tengo un costo máximo aprobado")
        max_cost = st.number_input(
            "Costo máximo de posición ($)", min_value=0.0, value=0.0, disabled=not use_max_cost
        )

    risk_fingerprint = (
        symbol.strip().upper(), option_type, float(spot), float(strike),
        float(bid), float(ask), expiration.isoformat(), int(contracts),
        bool(use_max_spread), float(max_spread), bool(use_max_spread_pct),
        float(max_spread_pct), bool(use_max_distance), float(max_distance),
        bool(use_min_dte), int(min_dte), bool(use_max_cost), float(max_cost),
    )
    if st.session_state.get("risk_fingerprint") not in {None, risk_fingerprint}:
        st.session_state["risk_status"] = GateStatus.NO_DISPONIBLE
        st.session_state["risk_evaluation"] = None
        st.session_state["risk_option_type"] = None

    if st.button("Evaluar contrato"):
        try:
            result = evaluate_option_risk(
                OptionQuote(
                    symbol=symbol.strip().upper(),
                    option_type=option_type,
                    spot=spot,
                    strike=strike,
                    bid=bid,
                    ask=ask,
                    expiration=expiration,
                    contracts=int(contracts),
                ),
                RiskLimits(
                    max_spread_absolute=max_spread if use_max_spread else None,
                    max_spread_pct=max_spread_pct if use_max_spread_pct else None,
                    max_spot_strike_distance_pct=(
                        max_distance if use_max_distance else None
                    ),
                    min_days_to_expiration=int(min_dte) if use_min_dte else None,
                    max_position_cost=max_cost if use_max_cost else None,
                ),
            )
        except ValueError as error:
            st.error(str(error))
            return

        st.metric("Estado de riesgo", result.status.value)
        st.dataframe(_criteria_table(result), width="stretch", hide_index=True)
        st.session_state["risk_status"] = result.status
        st.session_state["risk_symbol"] = symbol.strip().upper()
        st.session_state["risk_option_type"] = option_type
        st.session_state["risk_evaluation"] = {
            "result": asdict(result),
            "quote": {
                "symbol": symbol.strip().upper(),
                "option_type": option_type,
                "spot": spot,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "expiration": expiration.isoformat(),
                "contracts": int(contracts),
            },
        }
        st.session_state["risk_fingerprint"] = risk_fingerprint
        st.caption("La evaluación queda vinculada a la sesión actual de la app.")


    st.markdown("### Buscar contratos en Alpaca")
    st.caption(
        "La búsqueda usa los límites anteriores. El feed indicative puede "
        "estudiarse, pero nunca se marca como elegible."
    )
    search_columns = st.columns(3)
    option_feed = search_columns[0].selectbox(
        "Feed de opciones", ["indicative", "opra"]
    )
    max_search_dte = search_columns[1].number_input(
        "Vencimiento máximo (días)", min_value=1, value=14, step=1
    )
    min_quote_size = search_columns[2].number_input(
        "Tamaño mínimo bid/ask", min_value=0, value=1, step=1
    )
    delta_columns = st.columns(2)
    min_delta = delta_columns[0].number_input(
        "Delta absoluto mínimo", min_value=0.0, max_value=1.0, value=0.35
    )
    max_delta = delta_columns[1].number_input(
        "Delta absoluto máximo", min_value=0.0, max_value=1.0, value=0.65
    )
    if st.button("Buscar candidatos de opciones"):
        limits_ready = all(
            (
                use_max_spread,
                use_max_spread_pct,
                use_max_distance,
                use_min_dte,
                use_max_cost,
            )
        )
        if not limits_ready:
            st.error("Configura todos los límites antes de buscar candidatos.")
        else:
            try:
                config = AlpacaMarketConfig.from_env()
                provider = AlpacaOptionDataProvider(config, option_feed=option_feed)
                today = date.today()
                distance_fraction = float(max_distance) / 100
                chain = provider.fetch_chain(
                    symbol,
                    option_type=option_type.lower(),
                    expiration_date_gte=today + timedelta(days=int(min_dte)),
                    expiration_date_lte=today + timedelta(days=int(max_search_dte)),
                    strike_price_gte=float(spot) * (1 - distance_fraction),
                    strike_price_lte=float(spot) * (1 + distance_fraction),
                )
                candidates = select_option_candidates(
                    chain,
                    spot=float(spot),
                    policy=OptionSelectionPolicy(
                        risk_limits=RiskLimits(
                            max_spread_absolute=float(max_spread),
                            max_spread_pct=float(max_spread_pct),
                            max_spot_strike_distance_pct=float(max_distance),
                            min_days_to_expiration=int(min_dte),
                            max_position_cost=float(max_cost),
                        ),
                        min_bid_size=int(min_quote_size),
                        min_ask_size=int(min_quote_size),
                        min_delta=float(min_delta),
                        max_delta=float(max_delta),
                    ),
                    as_of=today,
                )
                st.session_state["option_candidates"] = candidates
            except (ValueError, OSError) as error:
                st.error(str(error))
    candidates = st.session_state.get("option_candidates", ())
    if candidates:
        st.dataframe(
            _option_candidates_table(candidates), width="stretch", hide_index=True
        )


def render_journal() -> None:
    """Registra planes, operaciones y resultados sin alterar las reglas."""
    st.subheader("Diario y aprendizaje controlado")
    repository = JournalRepository()
    analyses = repository.list_recent_analyses()
    if analyses:
        st.markdown("### Análisis recientes")
        analyses_table = _recent_analyses_table(analyses)
        analysis_filter_columns = st.columns(3)
        analysis_symbols = sorted(analyses_table["Simbolo"].dropna().unique())
        analysis_decisions = sorted(analyses_table["Decision"].dropna().unique())
        analysis_audits = sorted(analyses_table["Auditoria"].dropna().unique())
        selected_analysis_symbols = analysis_filter_columns[0].multiselect(
            "Simbolo analisis",
            analysis_symbols,
            default=analysis_symbols,
            key="journal_analysis_symbol_filter",
        )
        selected_analysis_decisions = analysis_filter_columns[1].multiselect(
            "Decision analisis",
            analysis_decisions,
            default=analysis_decisions,
            key="journal_analysis_decision_filter",
        )
        selected_analysis_audits = analysis_filter_columns[2].multiselect(
            "Auditoria analisis",
            analysis_audits,
            default=analysis_audits,
            key="journal_analysis_audit_filter",
        )
        filtered_analyses = _filtered_recent_analyses(
            analyses_table,
            symbols=selected_analysis_symbols,
            decisions=selected_analysis_decisions,
            audit_states=selected_analysis_audits,
        )
        st.dataframe(filtered_analyses, width="stretch", hide_index=True)
        st.download_button(
            "Descargar analisis filtrados CSV",
            data=filtered_analyses.to_csv(index=False).encode("utf-8"),
            file_name="analisis_diario_filtrados.csv",
            mime="text/csv",
            key="journal_analysis_download",
        )

        st.markdown("### Registrar operación planificada")
        labels = {
            f"#{item['id']} · {item['symbol']} · {item['decision']} · {item['data_as_of']}": item
            for item in analyses
        }
        selected_label = st.selectbox("Análisis asociado", list(labels))
        selected = labels[selected_label]
        if _analysis_requires_override_reason(selected):
            st.warning(
                "El análisis asociado no está listo; cualquier operación requiere "
                "razón de excepción documentada."
            )
        trade_left, trade_right = st.columns(2)
        with trade_left:
            trade_mode = TradingMode(
                st.selectbox("Modo del diario", [item.value for item in TradingMode])
            )
            trade_action = st.selectbox("Acción tomada", ["CALL", "PUT"])
            contract_symbol = st.text_input("Símbolo del contrato (opcional)")
            strike = st.number_input("Strike", min_value=0.0, value=0.0)
            expiration = st.date_input(
                "Expiración del contrato", value=date.today() + timedelta(days=7)
            )
            contracts = st.number_input(
                "Contratos operados", min_value=1, value=1, step=1
            )
            entry_price = st.number_input(
                "Precio de entrada por contrato", min_value=0.0, value=1.0
            )
        with trade_right:
            entry_plan = st.text_area("Plan escrito de entrada", key="journal_entry_plan")
            exit_plan = st.text_area("Plan escrito de salida", key="journal_exit_plan")
            notes = st.text_area("Notas", key="journal_notes")
            override_reason = st.text_area(
                "Razón si no siguió la decisión o el análisis no está listo",
                key="journal_override_reason",
            )
            real_ack = trade_mode is TradingMode.PAPER or st.checkbox(
                "Acepto expresamente documentar una operación con capital real."
            )

        weekly_count = repository.weekly_new_trade_count(trade_mode.value)
        st.caption(
            f"Entradas nuevas {trade_mode.value} esta semana: {weekly_count} de 3."
        )
        if st.button("Registrar operación en el diario"):
            governance = evaluate_governance(
                GovernanceRequest(
                    mode=trade_mode,
                    workflow=OperationWorkflow.NUEVA_ENTRADA,
                    new_trades_this_week=weekly_count,
                    entry_plan=entry_plan,
                    exit_plan=exit_plan,
                    real_mode_acknowledged=real_ack,
                )
            )
            if governance.status is not GateStatus.APROBADO:
                st.error("La operación no superó el gobierno operativo.")
                for reason in governance.reasons:
                    st.write(f"- {reason}")
            else:
                try:
                    trade_id = repository.record_planned_trade(
                        analysis_id=int(selected["id"]),
                        action=trade_action,
                        contracts=int(contracts),
                        entry_price=float(entry_price),
                        contract_symbol=contract_symbol.strip() or None,
                        strike=float(strike) if strike else None,
                        expiration=expiration.isoformat(),
                        notes=notes,
                        mode=trade_mode.value,
                        entry_plan=entry_plan,
                        exit_plan=exit_plan,
                        override_reason=override_reason,
                        real_mode_acknowledged=real_ack,
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success(f"Operación #{trade_id} registrada.")
    else:
        st.info("Guarda primero un análisis para poder vincular una operación.")

    open_trades = repository.list_open_trades()
    if open_trades:
        st.markdown("### Operaciones abiertas")
        st.dataframe(
            pd.DataFrame(open_trades), width="stretch", hide_index=True
        )
        open_labels = {
            f"#{item['id']} · {item['symbol']} · {item['action']} · {item['mode']}": item
            for item in open_trades
        }
        close_label = st.selectbox("Operación para cerrar", list(open_labels))
        close_left, close_right = st.columns(2)
        exit_price = close_left.number_input(
            "Precio de salida", min_value=0.0, value=1.0
        )
        fees = close_right.number_input("Comisiones totales", min_value=0.0, value=0.0)
        if st.button("Cerrar operación"):
            try:
                repository.close_trade(
                    int(open_labels[close_label]["id"]),
                    exit_price=float(exit_price),
                    fees=float(fees),
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Operación cerrada y resultado calculado.")

    closed_trades = repository.list_closed_trades(limit=100)
    st.markdown("### Operaciones cerradas")
    if closed_trades:
        closed_table = _closed_trades_table(closed_trades)
        closed_filter_columns = st.columns(3)
        closed_modes = sorted(closed_table["Modo"].dropna().unique())
        closed_symbols = sorted(closed_table["Simbolo"].dropna().unique())
        closed_decisions = sorted(closed_table["Decision analisis"].dropna().unique())
        selected_closed_modes = closed_filter_columns[0].multiselect(
            "Modo operaciones",
            closed_modes,
            default=closed_modes,
            key="journal_closed_mode_filter",
        )
        selected_closed_symbols = closed_filter_columns[1].multiselect(
            "Simbolo operaciones",
            closed_symbols,
            default=closed_symbols,
            key="journal_closed_symbol_filter",
        )
        selected_closed_decisions = closed_filter_columns[2].multiselect(
            "Decision operaciones",
            closed_decisions,
            default=closed_decisions,
            key="journal_closed_decision_filter",
        )
        filtered_closed = _filtered_closed_trades(
            closed_table,
            modes=selected_closed_modes,
            symbols=selected_closed_symbols,
            decisions=selected_closed_decisions,
        )
        comparison = _closed_trade_comparison_table(filtered_closed)
        if not comparison.empty:
            st.dataframe(comparison, width="stretch", hide_index=True)
        st.dataframe(filtered_closed, width="stretch", hide_index=True)
        st.download_button(
            "Descargar operaciones cerradas CSV",
            data=filtered_closed.to_csv(index=False).encode("utf-8"),
            file_name="operaciones_cerradas_filtradas.csv",
            mime="text/csv",
            key="journal_closed_trades_download",
        )
    else:
        st.info("Todavía no hay operaciones cerradas para comparar.")

    st.markdown("### Estadísticas por estrategia")
    statistics_mode = st.selectbox(
        "Modo estadisticas",
        ["TODOS", "PAPER", "REAL"],
        key="journal_statistics_mode",
    )
    learning_records = repository.learning_records(
        None if statistics_mode == "TODOS" else statistics_mode
    )
    statistics = summarize_strategy_performance(learning_records)
    if statistics:
        st.dataframe(pd.DataFrame(statistics), width="stretch", hide_index=True)
    else:
        st.info("Todavía no hay operaciones cerradas para calcular estadísticas.")
    st.caption(
        "El intervalo mostrado describe incertidumbre de la tasa observada. "
        "No corrige sesgo de selección ni garantiza resultados futuros; la "
        "confianza permanece NO_CALIBRADA."
    )

    audits = repository.list_recent_report_audits(limit=20)
    st.markdown("### Auditorías recientes")
    if audits:
        audit_table = _report_audits_table(audits)
        audit_filter_columns = st.columns(3)
        audit_symbols = sorted(audit_table["Simbolo"].dropna().unique())
        audit_states = sorted(audit_table["Estado"].dropna().unique())
        audit_packages = sorted(audit_table["Paquete"].dropna().unique())
        selected_audit_symbols = audit_filter_columns[0].multiselect(
            "Simbolo auditoria",
            audit_symbols,
            default=audit_symbols,
            key="journal_audit_symbol_filter",
        )
        selected_audit_states = audit_filter_columns[1].multiselect(
            "Estado auditoria",
            audit_states,
            default=audit_states,
            key="journal_audit_state_filter",
        )
        selected_audit_packages = audit_filter_columns[2].multiselect(
            "Paquete auditoria",
            audit_packages,
            default=audit_packages,
            key="journal_audit_package_filter",
        )
        filtered_audits = _filtered_report_audits(
            audit_table,
            symbols=selected_audit_symbols,
            readiness=selected_audit_states,
            packages=selected_audit_packages,
        )
        st.dataframe(filtered_audits, width="stretch", hide_index=True)
        st.download_button(
            "Descargar auditorias filtradas CSV",
            data=filtered_audits.to_csv(index=False).encode("utf-8"),
            file_name="auditorias_diario_filtradas.csv",
            mime="text/csv",
            key="journal_audit_download",
        )
    else:
        st.info("Todavía no hay auditorías guardadas.")


def render_governance() -> None:
    """Revisa disciplina y planes sin emitir una señal de mercado."""
    st.subheader("Plan y disciplina operativa")
    st.info(
        "La app comienza en PAPER. Esta compuerta no analiza dirección ni "
        "ejecuta órdenes; verifica que el flujo tenga límites y un plan escrito."
    )

    left, right = st.columns(2)
    with left:
        mode = TradingMode(st.selectbox("Modo", [item.value for item in TradingMode]))
        workflow = OperationWorkflow(
            st.selectbox("Flujo", [item.value for item in OperationWorkflow])
        )
        watchlist_text = st.text_input(
            "Radar (símbolos separados por coma)", value="SPY, QQQ, TSLA"
        )
        weekly_trades = JournalRepository().weekly_new_trade_count(mode.value)
        st.metric("Operaciones nuevas esta semana", weekly_trades)
    with right:
        entry_plan = st.text_area("Plan de entrada")
        exit_plan = st.text_area("Plan de salida")
        real_acknowledged = False
        if mode is TradingMode.REAL:
            real_acknowledged = st.checkbox(
                "Entiendo que PAPER no garantiza resultados y decido revisar "
                "manualmente el uso de capital real."
            )

    governance_fingerprint = (
        mode.value,
        workflow.value,
        tuple(sorted(symbol.strip().upper() for symbol in watchlist_text.split(",") if symbol.strip())),
        int(weekly_trades),
        entry_plan.strip(),
        exit_plan.strip(),
        bool(real_acknowledged),
    )
    if st.session_state.get("governance_fingerprint") not in {
        None,
        governance_fingerprint,
    }:
        st.session_state["governance_status"] = GateStatus.NO_DISPONIBLE
        st.session_state["governance_evaluation"] = None
        st.session_state["governance_watchlist"] = ()
        st.session_state["governance_workflow"] = None

    if st.button("Evaluar disciplina operativa"):
        result = evaluate_governance(
            GovernanceRequest(
                mode=mode,
                workflow=workflow,
                watchlist_symbols=tuple(watchlist_text.split(",")),
                new_trades_this_week=int(weekly_trades),
                entry_plan=entry_plan,
                exit_plan=exit_plan,
                real_mode_acknowledged=real_acknowledged,
            )
        )
        if result.status is GateStatus.APROBADO:
            st.success("Disciplina operativa: APROBADA")
        else:
            st.error("Disciplina operativa: RECHAZADA")
            for reason in result.reasons:
                st.write(f"- {reason}")
        st.session_state["governance_status"] = result.status
        st.session_state["governance_watchlist"] = tuple(
            sorted(
                symbol.strip().upper()
                for symbol in watchlist_text.split(",")
                if symbol.strip()
            )
        )
        st.session_state["governance_workflow"] = workflow.value
        st.session_state["governance_evaluation"] = {
            "result": asdict(result),
            "request": {
                "mode": mode.value,
                "workflow": workflow.value,
                "watchlist": st.session_state["governance_watchlist"],
                "new_trades_this_week": int(weekly_trades),
                "entry_plan": entry_plan,
                "exit_plan": exit_plan,
            },
        }
        st.session_state["governance_fingerprint"] = governance_fingerprint
        st.caption("La evaluación queda vinculada a la sesión actual de la app.")


def render_report_audit() -> None:
    """Audita reportes JSON exportados sin recalcular señales."""
    st.subheader("Auditoría de reportes")
    st.info(
        "Sube un JSON generado por JJTrade AI para revisar si falta evidencia, "
        "si hay bloqueos o si el caso está listo para revisión PAPER. Esta "
        "pestaña no cambia la decisión ni emite señales nuevas."
    )

    scanner_uploads = st.file_uploader(
        "Reportes JSON para scanner por estrategia",
        type=["json"],
        accept_multiple_files=True,
        key="strategy_scanner_uploads",
    )
    if scanner_uploads:
        try:
            scanner_reports = [
                json.loads(item.getvalue().decode("utf-8"))
                for item in scanner_uploads
            ]
            scanner_table = _strategy_scan_table(
                build_strategy_scan_rows(scanner_reports)
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            st.error(f"No se pudo construir el scanner: {error}")
        else:
            st.markdown("### Scanner por estrategia")
            scanner_metrics = st.columns(4)
            scanner_metrics[0].metric("Evaluaciones", len(scanner_table))
            scanner_metrics[1].metric(
                "Confirmadas",
                int((scanner_table["Estado"] == "CONFIRMADA").sum()),
            )
            scanner_metrics[2].metric(
                "Candidatas",
                int((scanner_table["Estado"] == "CANDIDATA").sum()),
            )
            scanner_metrics[3].metric(
                "Simbolos", scanner_table["Simbolo"].nunique()
            )
            strategy_filter = st.multiselect(
                "Estrategias scanner",
                sorted(scanner_table["ID"].unique()),
                default=sorted(scanner_table["ID"].unique()),
                key="strategy_scanner_strategy_filter",
            )
            state_filter = st.multiselect(
                "Estados scanner",
                sorted(scanner_table["Estado"].unique()),
                default=sorted(scanner_table["Estado"].unique()),
                key="strategy_scanner_state_filter",
            )
            symbol_filter = st.multiselect(
                "Simbolos scanner",
                sorted(scanner_table["Simbolo"].unique()),
                default=sorted(scanner_table["Simbolo"].unique()),
                key="strategy_scanner_symbol_filter",
            )
            filtered_scanner = scanner_table[
                scanner_table["ID"].isin(strategy_filter)
                & scanner_table["Estado"].isin(state_filter)
                & scanner_table["Simbolo"].isin(symbol_filter)
            ]
            st.dataframe(filtered_scanner, width="stretch", hide_index=True)
            st.download_button(
                "Descargar scanner filtrado CSV",
                data=filtered_scanner.to_csv(index=False).encode("utf-8"),
                file_name="scanner_estrategias.csv",
                mime="text/csv",
                key="strategy_scanner_download",
            )

    queue_upload = st.file_uploader(
        "Cola CSV de lote",
        type=["csv"],
        key="audit_review_queue_upload",
    )
    if queue_upload is not None:
        try:
            uploaded_queue = _review_queue_upload_table(pd.read_csv(queue_upload))
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
            st.error(f"No se pudo leer la cola CSV: {error}")
        else:
            st.markdown("### Cola de revision de lote")
            batch_metrics = st.columns(4)
            batch_metrics[0].metric("Filas", len(uploaded_queue))
            batch_metrics[1].metric(
                "Paquetes", uploaded_queue["Paquete"].nunique()
            )
            batch_metrics[2].metric(
                "Bloqueos",
                int((uploaded_queue["Prioridad"] == "1_BLOQUEO").sum()),
            )
            batch_metrics[3].metric(
                "Faltantes",
                int((uploaded_queue["Prioridad"] == "2_FALTANTE").sum()),
            )
            _render_review_queue_controls(
                uploaded_queue,
                key_prefix="batch_review_queue",
            )

    board_upload = st.file_uploader(
        "Tablero operador CSV",
        type=["csv"],
        key="audit_operator_board_upload",
    )
    if board_upload is not None:
        try:
            board_table = _operator_board_upload_table(pd.read_csv(board_upload))
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
            st.error(f"No se pudo leer el tablero CSV: {error}")
        else:
            st.markdown("### Tablero operador")
            board_metrics = st.columns(4)
            board_metrics[0].metric("Paquetes", len(board_table))
            board_metrics[1].metric(
                "Incompletos",
                int((board_table["Readiness"] == "INCOMPLETO").sum()),
            )
            board_metrics[2].metric(
                "Bloqueados",
                int((board_table["Readiness"] == "BLOQUEADO").sum()),
            )
            board_metrics[3].metric(
                "Learning ready",
                int((board_table["Learning ready"] == "SI").sum()),
            )
            board_filter = st.multiselect(
                "Readiness tablero",
                sorted(board_table["Readiness"].dropna().unique()),
                default=sorted(board_table["Readiness"].dropna().unique()),
                key="operator_board_readiness_filter",
            )
            filtered_board = board_table[board_table["Readiness"].isin(board_filter)]
            st.dataframe(filtered_board, width="stretch", hide_index=True)
            st.download_button(
                "Descargar tablero filtrado CSV",
                data=filtered_board.to_csv(index=False).encode("utf-8"),
                file_name="operator_board_filtrado.csv",
                mime="text/csv",
                key="operator_board_download",
            )

    intake_upload = st.file_uploader(
        "Intake CSV de casos",
        type=["csv"],
        key="audit_case_intake_upload",
    )
    if intake_upload is not None:
        try:
            intake_table = _case_intake_upload_table(pd.read_csv(intake_upload))
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
            st.error(f"No se pudo leer el intake CSV: {error}")
        else:
            st.markdown("### Intake de casos")
            intake_metrics = st.columns(4)
            intake_metrics[0].metric("Casos", len(intake_table))
            intake_metrics[1].metric("Simbolos", intake_table["Simbolo"].nunique())
            intake_metrics[2].metric(
                "Con pendientes",
                int((intake_table["Pendientes intake"] > 0).sum()),
            )
            intake_metrics[3].metric(
                "Riesgo aprobado",
                int((intake_table["Riesgo"] == "APROBADO").sum()),
            )
            intake_filter = st.multiselect(
                "Paquete intake",
                sorted(intake_table["Paquete"].dropna().unique()),
                default=sorted(intake_table["Paquete"].dropna().unique()),
                key="case_intake_package_filter",
            )
            filtered_intake = intake_table[intake_table["Paquete"].isin(intake_filter)]
            st.dataframe(filtered_intake, width="stretch", hide_index=True)
            st.download_button(
                "Descargar intake resumido CSV",
                data=filtered_intake.to_csv(index=False).encode("utf-8"),
                file_name="case_intake_resumen.csv",
                mime="text/csv",
                key="case_intake_download",
            )

    uploaded = st.file_uploader(
        "Reporte JSON de JJTrade AI",
        type=["json"],
        key="audit_report_upload",
    )
    if uploaded is None:
        st.caption(
            "Puedes generar reportes desde Análisis, validation_runner.py o "
            "validation_batch.py."
        )
        return

    try:
        report = json.loads(uploaded.getvalue().decode("utf-8"))
        audit = audit_report(report, report_path=uploaded.name)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        st.error(f"No se pudo leer el reporte JSON: {error}")
        return

    status_method = {
        "LISTO_REVISION": st.success,
        "INCOMPLETO": st.warning,
        "BLOQUEADO": st.error,
    }.get(audit.readiness, st.info)
    status_method(f"Estado de auditoría: {audit.readiness}")

    metric_columns = st.columns(4)
    metric_columns[0].metric("Símbolo", audit.symbol or "N/D")
    metric_columns[1].metric("Data as of", audit.data_as_of or "N/D")
    metric_columns[2].metric("Decisión", audit.decision)
    metric_columns[3].metric(
        "Learning ready", "SÍ" if audit.learning_ready else "NO"
    )
    version_columns = st.columns(2)
    version_columns[0].metric("App", audit.app_version or "N/D")
    version_columns[1].metric("Metodologia", audit.methodology_version or "N/D")
    if audit.package_id:
        package_columns = st.columns(3)
        package_columns[0].metric("Paquete", audit.package_id)
        package_columns[1].metric("Sesión paquete", audit.package_session or "N/D")
        package_columns[2].metric("Temporalidades", audit.package_timeframes or "N/D")
    gate_columns = st.columns(4)
    gate_columns[0].metric("Calidad", audit.data_quality_status)
    gate_columns[1].metric("Panorama", audit.panorama_status)
    gate_columns[2].metric("Riesgo", audit.risk_status)
    gate_columns[3].metric("Gobierno", audit.governance_status)
    radar_columns = st.columns(5)
    radar_columns[0].metric("Evaluados", audit.evaluated_count)
    radar_columns[1].metric("Detectados", audit.detected_count)
    radar_columns[2].metric("Confirmados", audit.confirmed_count)
    radar_columns[3].metric("Omitidos", audit.skipped_count)
    radar_columns[4].metric("Errores", audit.error_count)
    issue_columns = st.columns(6)
    issue_columns[0].metric("Pend. compuertas", audit.missing_gate_count)
    issue_columns[1].metric("Pend. estrategias", audit.missing_strategy_count)
    issue_columns[2].metric("Pend. invalidaciones", audit.missing_invalidation_count)
    issue_columns[3].metric("Bloq. compuertas", audit.blocker_gate_count)
    issue_columns[4].metric("Bloq. invalidaciones", audit.blocker_invalidation_count)
    issue_columns[5].metric("Bloq. detectores", audit.blocker_detector_count)

    review_queue = _review_queue_table(audit)
    st.markdown("### Cola de revision")
    _render_review_queue_controls(review_queue, key_prefix="audit_queue")

    st.markdown("### Estrategias detectadas")
    if audit.detected_strategies:
        st.dataframe(
            pd.DataFrame({"Estrategia": audit.detected_strategies}),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No hay estrategias detectadas en el reporte.")

    st.markdown("### Evidencia faltante")
    if audit.missing_evidence:
        st.dataframe(
            pd.DataFrame({"Pendiente": audit.missing_evidence}),
            width="stretch",
            hide_index=True,
        )
    else:
        st.success("No se detectó evidencia faltante.")

    st.markdown("### Bloqueos")
    if audit.blockers:
        st.dataframe(
            pd.DataFrame({"Bloqueo": audit.blockers}),
            width="stretch",
            hide_index=True,
        )
    else:
        st.success("No se detectaron bloqueos activos.")

    audit_payload = {
        "symbol": audit.symbol,
        "data_as_of": audit.data_as_of,
        "decision": audit.decision,
        "readiness": audit.readiness,
        "learning_ready": audit.learning_ready,
        "missing_evidence": audit.missing_evidence,
        "blockers": audit.blockers,
        "detected_strategies": audit.detected_strategies,
        "first_missing_evidence": audit.first_missing_evidence,
        "first_blocker": audit.first_blocker,
        "app_version": audit.app_version,
        "methodology_version": audit.methodology_version,
        "package_id": audit.package_id,
        "package_session": audit.package_session,
        "package_timeframes": audit.package_timeframes,
        "data_provider": audit.data_provider,
        "data_source_timeframes": audit.data_source_timeframes,
        "data_source_files": audit.data_source_files,
        "data_quality_status": audit.data_quality_status,
        "panorama_status": audit.panorama_status,
        "risk_status": audit.risk_status,
        "governance_status": audit.governance_status,
        "tentative_bias": audit.tentative_bias,
        "tentative_strategies": audit.tentative_strategies,
        "missing_gate_count": audit.missing_gate_count,
        "missing_strategy_count": audit.missing_strategy_count,
        "missing_invalidation_count": audit.missing_invalidation_count,
        "blocker_gate_count": audit.blocker_gate_count,
        "blocker_invalidation_count": audit.blocker_invalidation_count,
        "blocker_detector_count": audit.blocker_detector_count,
        "evaluated_count": audit.evaluated_count,
        "detected_count": audit.detected_count,
        "confirmed_count": audit.confirmed_count,
        "skipped_count": audit.skipped_count,
        "error_count": audit.error_count,
        "report_path": audit.report_path,
    }
    if st.button("Guardar auditoría en el diario"):
        try:
            audit_id = JournalRepository().record_report_audit(
                symbol=audit.symbol,
                data_as_of=audit.data_as_of,
                decision=audit.decision,
                readiness=audit.readiness,
                learning_ready=audit.learning_ready,
                missing_evidence=audit.missing_evidence,
                blockers=audit.blockers,
                detected_strategies=audit.detected_strategies,
                payload=audit_payload,
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(f"Auditoría #{audit_id} guardada localmente.")

    st.download_button(
        "Descargar auditoría JSON",
        data=json.dumps(audit_payload, ensure_ascii=False, indent=2),
        file_name=f"audit_{audit.symbol or 'reporte'}.json",
        mime="application/json",
    )


def render_telegram_connection() -> None:
    from telegram_alerts import CONFIG_PATH, TelegramError, connection, discover, save_connection, send_test
    st.subheader("Avisos a mi teléfono")
    st.caption("Conecta tu bot de Telegram. La clave se guarda protegida por Windows en este equipo.")
    st.markdown("**1 · Copia la clave de BotFather**")
    st.caption("Busca el mensaje de creación del bot y copia la clave de HTTP API. Pégala solo en este campo privado.")
    with st.form("telegram_discover"):
        token = st.text_input("Clave privada del bot", type="password")
        find = st.form_submit_button("Buscar mi chat de Telegram")
    if find:
        st.session_state.pop("telegram_pending", None)
        try:
            bot_name, chats = discover(token.strip())
            st.session_state["telegram_pending"] = (token.strip(), bot_name, chats)
        except TelegramError as error:
            st.error(str(error))
    pending = st.session_state.get("telegram_pending")
    if pending:
        pending_token, bot_name, chats = pending
        st.markdown("**2 · Confirma tu chat**")
        choice = st.selectbox("¿Cuál es tu chat?", range(len(chats)),
                              format_func=lambda index: f"{chats[index]['name']} · @{chats[index]['username']} · {chats[index]['id']}")
        if st.button("Vincular este chat"):
            try:
                save_connection(pending_token, bot_name, chats[choice])
                st.session_state.pop("telegram_pending", None)
                st.success("Chat vinculado. Ahora envía la prueba.")
            except (TelegramError, OSError):
                st.error("No se pudo guardar la conexión. Inténtalo de nuevo en este equipo Windows.")
    saved = None
    try:
        saved = connection()
        if saved:
            st.success(f"Conectado a @{saved['bot_name']} · {saved['chat_name']}")
            st.markdown("**3 · Comprueba que el mensaje llega a tu teléfono**")
            if st.button("Enviar mensaje de prueba"):
                send_test()
                st.success("Telegram aceptó el mensaje. Comprueba que llegó y que tienes activadas las notificaciones del bot.")
            if st.button("Desconectar Telegram"):
                CONFIG_PATH.unlink(missing_ok=True)
                st.session_state.pop("telegram_pending", None)
                st.rerun()
    except (TelegramError, OSError) as error:
        st.error(str(error) if isinstance(error, TelegramError) else "No se pudo leer la conexión guardada.")
    from bollinger_phone_worker import STATUS_PATH, enabled, set_enabled
    st.markdown("**Avisos tempranos · Bollinger en 15 minutos**")
    st.caption("Avisa al salir por la banda superior o inferior, con ambas bandas abriéndose y el punto medio acompañando. Un aviso por compañía, vela y dirección. No espera la aprobación PAPER.")
    if saved:
        if enabled():
            st.success("Avisos de Bollinger habilitados.")
            if st.button("Pausar avisos de Bollinger"):
                set_enabled(False)
                st.rerun()
        elif st.button("Activar avisos de Bollinger"):
            set_enabled(True)
            st.rerun()
    try:
        radar = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        heartbeat = datetime.fromisoformat(radar["heartbeat"])
        if datetime.now(timezone.utc) - heartbeat > timedelta(seconds=30):
            st.warning("El servicio de avisos no está respondiendo. No se garantiza la entrega de alertas.")
        else:
            radar_labels = {"VIGILANDO": "Radar vigilando los datos del buscador", "FUERA_DE_SESION": "Radar activo, esperando la apertura del mercado", "PAUSADO": "Avisos pausados", "SIN_DATOS_RECIENTES": "Sin datos recientes: revisa que el buscador esté corriendo", "ERROR": "El radar necesita revisión"}
            st.info(radar_labels.get(radar["state"], radar["state"]))
            if radar.get("errors"):
                st.warning("Telegram no confirmó algún envío. Revisa la conexión antes de confiar en los avisos.")
    except (OSError, ValueError, KeyError):
        st.warning("El servicio de avisos aún no ha informado su estado.")
    st.caption("El equipo y el buscador deben permanecer encendidos y conectados. Se revisan barras de un minuto; Telegram e Internet pueden añadir demora. Las alertas no garantizan acierto.")


def render_paper_entry_validation() -> None:
    st.subheader("¿Está lista esta señal para practicar?")
    st.info("Selecciona una señal, responde tres preguntas y escribe tu plan. La app comprobará lo demás y te dirá si puedes practicar o qué falta resolver.")
    st.caption("PAPER significa simulación: no usa dinero real ni envía órdenes. Una aprobación no garantiza ganancias.")
    repository = AlertRepository()
    alerts = repository.recent(limit=100)
    if not alerts:
        st.info("Todavía no hay alertas para revisar.")
        return
    labels = {f"#{item['id']} · {item['symbol']} · {_market_event_local_time(item['trigger_timestamp'])}": item for item in alerts}
    st.markdown("**Paso 1 · Elige la señal que quieres revisar**")
    alert = labels[st.selectbox("Compañía y hora de la señal", list(labels), key="paper_validation_alert")]
    report = alert["report"]
    research_path = Path(__file__).resolve().parent / "exports" / "strategy_research" / "latest.json"
    try:
        research = json.loads(research_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        research = {}
    now = datetime.now(timezone.utc)
    evidence = entry_evidence(alert, research, as_of=now)
    st.markdown("**¿Qué ha observado la app en movimientos parecidos?**")
    favorable_count = sum(item["status"] == "EVIDENCIA_FAVORABLE" for item in evidence["rows"])
    if evidence["rows"] and favorable_count == len(evidence["rows"]):
        st.success("El historial cumple el filtro de resultados favorables. Todavía faltan las comprobaciones de esta entrada.")
    elif any(item["status"] == "MUESTRA_INSUFICIENTE" for item in evidence["rows"]):
        st.info("La app necesita observar más resultados antes de aprobar esta señal por su historial.")
    elif evidence["rows"]:
        st.warning("Los resultados anteriores todavía no cumplen el filtro para aprobar esta señal.")
    if evidence["rows"]:
        with st.expander("Ver números y detalles del historial"):
            st.dataframe(pd.DataFrame([{"Estrategia": item["strategy_id"], "Dirección": item["bias"], "Muestra": item["sample_size"],
                                   "Sesiones": item["session_count"], "Positivos %": item["positive_rate_pct"],
                                   "Retorno medio %": item["average_directional_return_pct"], "Estado": item["status"]}
                                  for item in evidence["rows"]]), width="stretch", hide_index=True)
    else:
        st.info("No hay una estrategia confirmada con evidencia para esta señal.")
    st.caption("Se comparan movimientos anteriores de la misma estrategia y dirección. Estos resultados no predicen el próximo movimiento.")
    candidates = {"Sin contrato elegible": None}
    candidates.update({item["symbol"]: item for item in report.get("option_selection", {}).get("candidates", []) if item.get("eligible") is True})
    with st.form(f"paper_entry_form_{alert['id']}"):
        st.markdown("**Paso 2 · Confirma lo que revisaste**")
        st.caption("Si no sabes la respuesta, selecciona «No lo he revisado». La app mantendrá la entrada pendiente.")
        options = {"No lo he revisado": None, "Sí, lo revisé y cumple": True, "No, encontré un problema": False}
        path = options[st.selectbox("¿El precio tiene espacio para avanzar hacia tu objetivo?", list(options), help="Revisa si hay soportes o resistencias cercanos que puedan frenar el movimiento.")]
        news = options[st.selectbox("¿Revisaste las noticias y no encontraste algo que contradiga la entrada?", list(options))]
        panorama = options[st.selectbox("¿El movimiento general del mercado acompaña esta señal?", list(options))]
        st.markdown("**Paso 3 · Elige el contrato y escribe tu plan**")
        contract_label = st.selectbox("Contrato de opciones disponible para practicar", list(candidates), help="La app solo permite seleccionar contratos que pasaron su evaluación. La cotización también debe estar vigente.")
        if len(candidates) == 1:
            st.info("Falta un contrato con precio actualizado y riesgo evaluado. Puedes guardar tu revisión, pero la entrada seguirá bloqueada hasta contar con ese dato.")
        entry_plan = st.text_area("¿Cuándo entrarías y qué te haría cancelar la entrada?", placeholder="Escribe el precio o condición de entrada y el nivel que invalidaría tu idea.")
        exit_plan = st.text_area("¿Cuándo saldrías?", placeholder="Escribe tu objetivo y cuándo cerrarías si el movimiento va en contra.")
        with st.expander("Límites de tu plan y notas"):
            weekly_count = st.number_input("¿Cuántas entradas nuevas llevas esta semana?", min_value=0, step=1)
            watchlist = st.text_input("Compañías que autorizaste para practicar", value=alert["symbol"], help="Separa los símbolos con comas. La compañía de esta señal debe estar incluida.")
            notes = st.text_area("Notas de lo que revisaste (opcional)")
        st.caption("Comprueba los límites de tu plan antes de continuar. La revisión se guardará para esta señal.")
        submitted = st.form_submit_button("Comprobar si puedo practicar")
    if submitted:
        try:
            review_id = repository.record_human_review(alert["id"], path_clear=path, news_clear=news, panorama_approved=panorama, notes=notes)
            repository.record_governance_review(alert["id"], GovernanceRequest(
                mode=TradingMode.PAPER, workflow=OperationWorkflow.NUEVA_ENTRADA,
                watchlist_symbols=tuple(item.strip() for item in watchlist.split(",") if item.strip()),
                new_trades_this_week=int(weekly_count), entry_plan=entry_plan, exit_plan=exit_plan, symbol=alert["symbol"]), notes=notes)
            if candidates[contract_label] is not None:
                repository.record_contract_selection(alert["id"], contract_label, notes=notes)
            contracts = repository.contract_selections(alert["id"])
            contract = contracts[0] if contracts and candidates[contract_label] is not None else None
            validated_at = datetime.now(timezone.utc)
            session = MarketSessionRepository(repository.database_path).session(validated_at.astimezone(ZoneInfo("America/New_York")).date())
            payload = validate_paper_entry(alert, repository.human_reviews(alert["id"])[0], contract,
                                          repository.governance_reviews(alert["id"])[0],
                                          VisualEvidenceRepository(repository.database_path).audit(alert["id"]), research,
                                          as_of=validated_at, session=session)
            validation_id = repository.record_reevaluation(alert["id"], review_id, payload)
            st.session_state[f"paper_validation_result_{alert['id']}"] = (validation_id, payload)
        except (ValueError, OSError) as error:
            st.error(str(error))
    saved = st.session_state.get(f"paper_validation_result_{alert['id']}")
    if saved:
        validation_id, payload = saved
        assessment = payload["paper_entry_validation"]
        if assessment["status"] == "APROBADA_PAPER":
            current_time = datetime.now(timezone.utc)
            original_time = datetime.fromisoformat(alert["trigger_timestamp"])
            current_session = MarketSessionRepository(repository.database_path).session(current_time.astimezone(ZoneInfo("America/New_York")).date())
            if current_time - original_time > timedelta(minutes=3) or current_session is None or not current_session.opens_at <= current_time < current_session.closes_at:
                st.warning(f"La aprobación #{validation_id} es un registro anterior y ya no está vigente. Valida una señal actual.")
            else:
                st.success(f"Lista para practicar en simulación · {payload['decision']['decision']}. Aprobada al momento de esta revisión.")
        else:
            st.warning("Todavía no está lista para practicar. Resuelve los puntos siguientes y vuelve a comprobar.")
            st.markdown("**Qué falta resolver**")
            for blocker in assessment["blockers"]:
                st.write("• " + blocker)
        st.caption("Resultado guardado con fecha, revisiones y evidencia. No permanece vigente indefinidamente.")


def main() -> None:
    """Construye la navegación principal de la aplicación."""
    st.markdown("""<style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        background-color: #08111f !important; color: #e8eef7 !important;
    }
    [data-testid="stHeader"] {background-color: #08111f !important;}
    [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3, [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"], [data-testid="stWidgetLabel"] {
        color: #e8eef7 !important;
    }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
        color: #a8b8ce !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {border-color: #29405c !important;}
    </style>""", unsafe_allow_html=True)
    st.title("JJTrade AI")
    st.caption("Metodología Investep · decisión asistida · ejecución humana")
    if "risk_status" not in st.session_state:
        st.session_state["risk_status"] = GateStatus.NO_DISPONIBLE
    if "risk_symbol" not in st.session_state:
        st.session_state["risk_symbol"] = None
    if "risk_option_type" not in st.session_state:
        st.session_state["risk_option_type"] = None
    if "risk_fingerprint" not in st.session_state:
        st.session_state["risk_fingerprint"] = None
    if "governance_status" not in st.session_state:
        st.session_state["governance_status"] = GateStatus.NO_DISPONIBLE
    if "governance_fingerprint" not in st.session_state:
        st.session_state["governance_fingerprint"] = None
    if "governance_watchlist" not in st.session_state:
        st.session_state["governance_watchlist"] = ()
    if "governance_workflow" not in st.session_state:
        st.session_state["governance_workflow"] = None
    simple_tab, phone_tab, validation_tab, research_tab, risk_tab, governance_tab, journal_tab, analysis_tab, audit_tab = st.tabs(
        [
            "Bollinger en vivo",
            "Avisos a mi teléfono",
            "Validar entrada PAPER",
            "Seguimiento de resultados",
            "Riesgo de opciones",
            "Plan operativo",
            "Diario",
            "Análisis",
            "Auditoría",
        ]
    )
    with simple_tab:
        render_bollinger_dashboard()
    with validation_tab:
        st.info("Las validaciones de entrada quedan fuera del enfoque actual. Primero estamos comprobando la salida de Bollinger y la continuidad del movimiento. Consulta Bollinger en vivo y Seguimiento de resultados.")
    with phone_tab:
        render_telegram_connection()
    with research_tab:
        _render_strategy_research()
    with risk_tab:
        render_risk()
    with governance_tab:
        render_governance()
    with analysis_tab:
        render_analysis()
    with journal_tab:
        render_journal()
    with audit_tab:
        render_report_audit()


if __name__ == "__main__":
    main()
