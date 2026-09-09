"""Estado operativo del scanner consciente del calendario oficial."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from market_calendar import MarketSession


def evaluate_operational_status(
    *,
    preflight: Mapping[str, Any] | None,
    health: Mapping[str, Any] | None,
    session: MarketSession | None,
    now: datetime,
    maximum_bar_delay: timedelta = timedelta(minutes=3),
    reconciliation: Mapping[str, Any] | None = None,
    reconciliations: Mapping[str, Mapping[str, Any]] | None = None,
    expected_symbols: tuple[str, ...] = (),
    open_processing_incident_count: int = 0,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now debe incluir zona horaria.")
    reasons: list[str] = []
    if not preflight or preflight.get("status") != "LISTO":
        reasons.append("No existe un preflight remoto LISTO.")
    if open_processing_incident_count < 0:
        raise ValueError("El conteo de incidentes no puede ser negativo.")
    if open_processing_incident_count:
        reasons.append(
            f"Existen {open_processing_incident_count} incidente(s) "
            "de procesamiento sin resolver."
        )
    market_open = bool(session and session.opens_at <= now <= session.closes_at)
    if market_open and reconciliation and reconciliation.get("status") not in {"APROBADO", "OMITIDO"}:
        reasons.append(f"Última reconciliación {str(reconciliation.get('status')).lower()}.")
    reconciliation_coverage = evaluate_reconciliation_coverage(
        reconciliations or {}, expected_symbols=expected_symbols,
        session=session, now=now,
    )
    if market_open:
        reasons.extend(reconciliation_coverage["issues"])
    if health is None:
        return _result("NO_INICIADO", market_open, reasons + ["El scanner no tiene heartbeat."], reconciliation_coverage)
    service_status = str(health.get("status", ""))
    if service_status in {"DESCONECTADO", "DETENIDO"}:
        return _result("BLOQUEADO", market_open, reasons + [f"Scanner {service_status.lower()}."] , reconciliation_coverage)
    if service_status in {"INICIANDO", "CONECTANDO"}:
        return _result("INICIANDO", market_open, reasons + ["El scanner está estableciendo conexión."], reconciliation_coverage)
    if service_status != "CONECTADO":
        return _result("DEGRADADO", market_open, reasons + ["Estado de scanner desconocido."], reconciliation_coverage)
    if not market_open:
        status = "LISTO_EN_ESPERA" if not reasons else "DEGRADADO"
        return _result(status, False, reasons + ["Mercado cerrado según calendario oficial."], reconciliation_coverage)
    last_bar_text = health.get("last_bar_at")
    if not last_bar_text:
        return _result("DEGRADADO", True, reasons + ["Mercado abierto sin vela recibida."], reconciliation_coverage)
    try:
        last_bar = datetime.fromisoformat(str(last_bar_text).replace("Z", "+00:00"))
    except ValueError:
        return _result("DEGRADADO", True, reasons + ["Timestamp de última vela inválido."], reconciliation_coverage)
    delay = now - last_bar.astimezone(now.tzinfo)
    if delay > maximum_bar_delay:
        reasons.append(f"Última vela retrasada {round(delay.total_seconds() / 60, 1)} minutos.")
        return _result("DEGRADADO", True, reasons, reconciliation_coverage)
    return _result("DEGRADADO" if reasons else "LISTO", True, reasons, reconciliation_coverage)


def evaluate_reconciliation_coverage(
    reconciliations: Mapping[str, Mapping[str, Any]], *,
    expected_symbols: tuple[str, ...], session: MarketSession | None,
    now: datetime, maximum_age: timedelta = timedelta(minutes=20),
) -> dict[str, Any]:
    expected = tuple(sorted({item.strip().upper() for item in expected_symbols if item.strip()}))
    issues: list[str] = []
    details: list[dict[str, Any]] = []
    grace = bool(session and now <= session.opens_at + maximum_age)
    for symbol in expected:
        item = reconciliations.get(symbol)
        if item is None:
            state = "ESPERANDO_PRIMER_BLOQUE" if grace else "FALTANTE"
            if not grace:
                issues.append(f"{symbol} no tiene reconciliación reciente.")
            details.append({"symbol": symbol, "status": state, "age_minutes": None})
            continue
        status = str(item.get("status", "NO_DISPONIBLE"))
        try:
            timestamp = datetime.fromisoformat(str(item.get("trigger_timestamp", "")).replace("Z", "+00:00"))
            age = (now - timestamp.astimezone(now.tzinfo)).total_seconds() / 60
        except ValueError:
            age = None
        if status not in {"APROBADO", "OMITIDO"}:
            issues.append(f"{symbol} tiene reconciliación {status.lower()}.")
        elif age is None or age > maximum_age.total_seconds() / 60:
            issues.append(f"{symbol} tiene reconciliación atrasada.")
        details.append({"symbol": symbol, "status": status, "age_minutes": round(age, 1) if age is not None else None})
    return {"status": "APROBADO" if not issues else "DEGRADADO", "expected_count": len(expected), "covered_count": sum(item["status"] not in {"FALTANTE", "ESPERANDO_PRIMER_BLOQUE"} for item in details), "issues": issues, "details": details}


def _result(status: str, market_open: bool, reasons: list[str], coverage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"status": status, "market_open": market_open, "reasons": reasons, "reconciliation_coverage": dict(coverage or {}), "authority": "MONITOREO_NO_EJECUTA_ORDENES"}
