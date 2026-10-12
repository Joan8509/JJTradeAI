"""Validación PAPER con evidencia posterior a la emisión, sin ejecutar órdenes."""

from datetime import datetime, timedelta, timezone

from alert_reevaluation import reevaluate_alert
from paper_signal_evaluator import _confirmed_directional_strategies, _wilson_interval
from strategy_research import _non_overlapping, _research_groups


def entry_evidence(alert, research, *, as_of, minimum_sample=20):
    if as_of.tzinfo is None or minimum_sample <= 0:
        raise ValueError("Fecha o muestra mínima inválida.")
    confirmed = set(_confirmed_directional_strategies(alert["report"]))
    version = str(alert["report"].get("methodology_version", ""))
    generated = datetime.fromisoformat(research["generated_at"]) if research.get("generated_at") else None
    rows = []
    if generated and generated.tzinfo and generated <= as_of:
        for row in research.get("entry_observations", {}).get("CONFIRMADAS", []):
            if (row["alert_id"] != alert["id"] and row["methodology_version"] == version
                    and row["provider"] == alert["provider"] and row["feed"] == alert["feed"]
                    and row["horizon_minutes"] == 60 and (row["strategy_id"], row["bias"]) in confirmed
                    and datetime.fromisoformat(row["exit_timestamp"]) <= as_of):
                rows.append(row)
    result = []
    groups = _research_groups(rows)
    for strategy, bias in sorted(confirmed):
        samples = _non_overlapping(groups.get((strategy, bias, 60, version), []))
        wins = sum(row["directional_return_pct"] > 0 for row in samples)
        lower, upper = _wilson_interval(wins, len(samples))
        mean = sum(row["directional_return_pct"] for row in samples) / len(samples) if samples else None
        status = "MUESTRA_INSUFICIENTE" if len(samples) < minimum_sample else "EVIDENCIA_FAVORABLE" if lower > 0.5 and mean > 0 else "EVIDENCIA_NO_FAVORABLE"
        result.append({"strategy_id": strategy, "bias": bias, "sample_size": len(samples),
                       "session_count": len({row["session"] for row in samples}),
                       "positive_rate_pct": round(wins / len(samples) * 100, 2) if samples else None,
                       "interval_95_low": round(lower * 100, 2), "interval_95_high": round(upper * 100, 2),
                       "average_directional_return_pct": round(mean, 6) if mean is not None else None, "status": status})
    return {"rows": result, "source_generated_at": research.get("generated_at"), "as_of": as_of.isoformat(),
            "minimum_sample": minimum_sample, "horizon_minutes": 60,
            "authority": "EVIDENCIA_DESCRIPTIVA_NO_PROBABILIDAD_CALIBRADA"}


def validate_paper_entry(alert, review, contract, governance, visual_audit, research, *, as_of, session):
    if as_of.tzinfo is None:
        raise ValueError("La validación debe incluir zona horaria.")
    result = reevaluate_alert(alert["report"], review, contract, governance, visual_audit)
    methodology_decision = dict(result["decision"])
    evidence = entry_evidence(alert, research, as_of=as_of)
    blockers = []
    try:
        research_time = datetime.fromisoformat(research["generated_at"])
    except (KeyError, ValueError, TypeError):
        research_time = None
    if research_time is None or research_time.tzinfo is None or not timedelta(0) <= as_of - research_time <= timedelta(minutes=10):
        blockers.append("El informe de aprendizaje no está actualizado; espera una nueva evaluación.")
    if methodology_decision.get("decision") not in {"CALL", "PUT"}:
        blockers.extend(methodology_decision.get("reasons", []))
    if governance is None or governance.get("mode") != "PAPER":
        blockers.append("La revisión operativa debe ser PAPER.")
    if session is None or not session.opens_at <= as_of < session.closes_at:
        blockers.append("La sesión de mercado no está abierta o falta su calendario.")
    stamp = datetime.fromisoformat(alert["trigger_timestamp"])
    if stamp.tzinfo is None or not timedelta(0) <= as_of - stamp <= timedelta(minutes=3):
        blockers.append("La señal no está vigente: se aplica la ventana de frescura existente de tres minutos.")
    if alert["report"].get("live_data_freshness", {}).get("status") != "APROBADO":
        blockers.append("La frescura original de los datos no está aprobada.")
    candidate = contract.get("candidate", {}) if contract else {}
    quote_stamp = candidate.get("quote_timestamp") or candidate.get("snapshot", {}).get("quote_timestamp")
    try:
        quote_time = datetime.fromisoformat(quote_stamp) if quote_stamp else None
    except (ValueError, TypeError):
        quote_time = None
    if quote_time is None or quote_time.tzinfo is None or not timedelta(0) <= as_of - quote_time <= timedelta(minutes=3):
        blockers.append("Falta una cotización vigente del contrato seleccionado.")
    if candidate.get("option_type") != methodology_decision.get("decision"):
        blockers.append("El contrato no coincide con la dirección de la estrategia.")
    supporting = {name.split("@")[0] for name in methodology_decision.get("supporting_strategies", [])}
    by_strategy = {row["strategy_id"]: row for row in evidence["rows"]}
    if not supporting or any(by_strategy.get(sid, {}).get("status") != "EVIDENCIA_FAVORABLE" for sid in supporting):
        blockers.append("La evidencia histórica de las estrategias de soporte todavía no es favorable y suficiente.")
    blockers = list(dict.fromkeys(blockers))
    result["paper_entry_validation"] = {"validated_at": as_of.astimezone(timezone.utc).isoformat(),
        "methodology_decision": methodology_decision, "historical_evidence": evidence,
        "blockers": blockers, "status": "BLOQUEADA" if blockers else "APROBADA_PAPER",
        "disclaimer": "Cumplimiento y evidencia descriptiva; no garantiza acierto ni ejecuta órdenes."}
    if blockers:
        result["decision"] = {**methodology_decision, "decision": "NO_OPERAR", "reasons": blockers, "confidence": "NO_CALIBRADA"}
    return result
