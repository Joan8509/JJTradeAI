"""Aprendizaje descriptivo que nunca reescribe reglas Investep."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
import hashlib
import json
from typing import Any
from datetime import datetime


@dataclass(frozen=True)
class LearningPolicy:
    """Política explícita para decidir si una muestra puede calibrarse."""

    minimum_sample_size: int | None = None


@dataclass(frozen=True)
class TemporalValidationPolicy:
    """Tamaños mínimos para una comparación cronológica fuera de muestra."""

    training_fraction: float = 0.7
    minimum_training_size: int = 10
    minimum_test_size: int = 5


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    proportion = wins / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def _direction_priority(score: float) -> str:
    if score >= 80:
        return "ALTA"
    if score >= 60:
        return "MEDIA"
    if score >= 40:
        return "BAJA"
    return "MINIMA"


def _direction_confidence_score(best_rate: float | None, sample_size: int, minimum_sample_size: int) -> tuple[float, str]:
    if best_rate is None:
        return (0.0, "MINIMA")
    sample_factor = min(sample_size / max(minimum_sample_size, 1), 1.0)
    score = (best_rate * 0.7) + (sample_factor * 30.0)
    return (round(score, 2), _direction_priority(score))


def summarize_strategy_performance(
    records: Iterable[Mapping[str, Any]],
    policy: LearningPolicy = LearningPolicy(),
) -> list[dict[str, Any]]:
    """Calcula métricas por estrategia y modo, conservando sus limitaciones."""
    if policy.minimum_sample_size is not None and policy.minimum_sample_size <= 0:
        raise ValueError("El tamaño mínimo de muestra debe ser mayor que cero.")

    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        for strategy in record.get("strategies", []):
            groups.setdefault((str(strategy), str(record["mode"])), []).append(record)

    summaries: list[dict[str, Any]] = []
    for (strategy, mode), items in sorted(groups.items()):
        pnls = [float(item["pnl"]) for item in items]
        wins = sum(value > 0 for value in pnls)
        decision_counts = {
            "CALL": sum(item.get("decision") == "CALL" for item in items),
            "PUT": sum(item.get("decision") == "PUT" for item in items),
            "NO_OPERAR": sum(
                item.get("decision") == "NO_OPERAR" for item in items
            ),
        }
        gross_profit = sum(value for value in pnls if value > 0)
        gross_loss = abs(sum(value for value in pnls if value < 0))
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in pnls:
            cumulative += value
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)
        lower, upper = _wilson_interval(wins, len(pnls))
        if policy.minimum_sample_size is None:
            sample_status = "SIN_UMBRAL_APROBADO"
        elif len(pnls) >= policy.minimum_sample_size:
            sample_status = "MUESTRA_MINIMA_ALCANZADA"
        else:
            sample_status = "MUESTRA_INSUFICIENTE"
        summaries.append(
            {
                "strategy_id": strategy,
                "mode": mode,
                "sample_size": len(pnls),
                "observed_win_rate": round(wins / len(pnls) * 100, 2),
                "win_rate_interval_95_low": round(lower * 100, 2),
                "win_rate_interval_95_high": round(upper * 100, 2),
                "average_pnl": round(sum(pnls) / len(pnls), 2),
                "total_pnl": round(sum(pnls), 2),
                "profit_factor": (
                    round(gross_profit / gross_loss, 2)
                    if gross_loss > 0
                    else None
                ),
                "max_drawdown": round(max_drawdown, 2),
                "decision_followed_rate": round(
                    sum(bool(item["decision_followed"]) for item in items)
                    / len(items)
                    * 100,
                    2,
                ),
                "decision_call_count": decision_counts["CALL"],
                "decision_put_count": decision_counts["PUT"],
                "decision_no_operar_count": decision_counts["NO_OPERAR"],
                "human_override_count": sum(
                    not bool(item["decision_followed"]) for item in items
                ),
                "sample_status": sample_status,
                "confidence": "NO_CALIBRADA",
            }
        )
    return summaries


def summarize_alert_feedback(
    records: Iterable[Mapping[str, Any]],
    policy: LearningPolicy = LearningPolicy(),
) -> list[dict[str, Any]]:
    """Resume feedback de alertas sin mezclar PAPER/REAL ni contar correcciones viejas."""
    if policy.minimum_sample_size is not None and policy.minimum_sample_size <= 0:
        raise ValueError("El tamaño mínimo de muestra debe ser mayor que cero.")
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        if not record.get("trade_taken"):
            continue
        for strategy in record.get("strategies", []):
            groups.setdefault((str(strategy), str(record["mode"])), []).append(record)
    summaries: list[dict[str, Any]] = []
    for (strategy, mode), items in sorted(groups.items()):
        wins = sum(item.get("result") == "POSITIVO" for item in items)
        losses = sum(item.get("result") == "NEGATIVO" for item in items)
        ties = sum(item.get("result") == "EMPATE" for item in items)
        lower, upper = _wilson_interval(wins, len(items))
        sample_status = (
            "SIN_UMBRAL_APROBADO" if policy.minimum_sample_size is None
            else "MUESTRA_MINIMA_ALCANZADA" if len(items) >= policy.minimum_sample_size
            else "MUESTRA_INSUFICIENTE"
        )
        known_pnls = [float(item["pnl"]) for item in items if item.get("pnl") is not None]
        summaries.append({
            "strategy_id": strategy, "mode": mode, "sample_size": len(items),
            "positive_count": wins, "negative_count": losses, "breakeven_count": ties,
            "observed_positive_rate": round(wins / len(items) * 100, 2),
            "positive_rate_interval_95_low": round(lower * 100, 2),
            "positive_rate_interval_95_high": round(upper * 100, 2),
            "average_pnl": round(sum(known_pnls) / len(known_pnls), 2) if known_pnls else None,
            "sample_status": sample_status, "confidence": "DESCRIPTIVA_NO_PREDICTIVA",
        })
    return summaries


def summarize_context_performance(
    records: Iterable[Mapping[str, Any]],
    policy: LearningPolicy = LearningPolicy(minimum_sample_size=10),
) -> list[dict[str, Any]]:
    """Segmenta resultados por contexto; nunca llama confiable a una muestra pequeña."""
    if policy.minimum_sample_size is None or policy.minimum_sample_size <= 0:
        raise ValueError("La calibración contextual requiere un tamaño mínimo explícito.")
    dimensions = (
        "trend_15m", "relative_volatility_15m", "session_segment",
        "benchmark_regime", "benchmark_alignment", "benchmark_synchronization",
        "visual_confirmation",
    )
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        if not record.get("trade_taken"):
            continue
        context = record.get("context", {})
        for strategy in record.get("strategies", []):
            for dimension in dimensions:
                value = str(context.get(dimension, "NO_DISPONIBLE"))
                if value == "NO_DISPONIBLE":
                    continue
                groups.setdefault((str(strategy), str(record["mode"]), dimension, value), []).append(record)
    summaries: list[dict[str, Any]] = []
    for (strategy, mode, dimension, value), items in sorted(groups.items()):
        wins = sum(item.get("result") == "POSITIVO" for item in items)
        lower, upper = _wilson_interval(wins, len(items))
        sufficient = len(items) >= policy.minimum_sample_size
        summaries.append({
            "strategy_id": strategy, "mode": mode, "context_dimension": dimension,
            "context_value": value, "sample_size": len(items),
            "observed_positive_rate": round(wins / len(items) * 100, 2),
            "positive_rate_interval_95_low": round(lower * 100, 2),
            "positive_rate_interval_95_high": round(upper * 100, 2),
            "sample_status": "MUESTRA_MINIMA_ALCANZADA" if sufficient else "MUESTRA_INSUFICIENTE",
            "eligible_for_calibration": sufficient,
            "confidence": "DESCRIPTIVA_NO_PREDICTIVA",
        })
    return summaries


def evaluate_temporal_stability(
    records: Iterable[Mapping[str, Any]],
    policy: TemporalValidationPolicy = TemporalValidationPolicy(),
) -> list[dict[str, Any]]:
    """Compara el tramo inicial con el posterior sin barajar ni mirar hacia atrás."""
    if not 0 < policy.training_fraction < 1:
        raise ValueError("La fracción de entrenamiento debe estar entre cero y uno.")
    if policy.minimum_training_size <= 0 or policy.minimum_test_size <= 0:
        raise ValueError("Los tamaños mínimos temporales deben ser mayores que cero.")
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        if not record.get("trade_taken"):
            continue
        version = str(record.get("methodology_version") or "SIN_VERSION")
        for strategy in record.get("strategies", []):
            groups.setdefault((str(strategy), str(record["mode"]), version), []).append(record)
    results: list[dict[str, Any]] = []
    for (strategy, mode, version), items in sorted(groups.items()):
        ordered = sorted(items, key=lambda item: (str(item.get("event_at") or item.get("created_at", "")), int(item.get("outcome_id", 0))))
        split = int(len(ordered) * policy.training_fraction)
        training, test = ordered[:split], ordered[split:]
        enough = len(training) >= policy.minimum_training_size and len(test) >= policy.minimum_test_size
        training_wins = sum(item.get("result") == "POSITIVO" for item in training)
        test_wins = sum(item.get("result") == "POSITIVO" for item in test)
        training_interval = _wilson_interval(training_wins, len(training))
        test_interval = _wilson_interval(test_wins, len(test))
        if not enough:
            status = "MUESTRA_TEMPORAL_INSUFICIENTE"
        elif test_interval[1] < training_interval[0]:
            status = "DEGRADACION_OBSERVADA"
        elif test_interval[0] > training_interval[1]:
            status = "MEJORA_OBSERVADA"
        else:
            status = "SIN_DIFERENCIA_CONCLUYENTE"
        results.append({
            "strategy_id": strategy, "mode": mode, "methodology_version": version,
            "total_size": len(ordered), "training_size": len(training), "test_size": len(test),
            "training_positive_rate": round(training_wins / len(training) * 100, 2) if training else None,
            "test_positive_rate": round(test_wins / len(test) * 100, 2) if test else None,
            "training_interval_95_low": round(training_interval[0] * 100, 2),
            "training_interval_95_high": round(training_interval[1] * 100, 2),
            "test_interval_95_low": round(test_interval[0] * 100, 2),
            "test_interval_95_high": round(test_interval[1] * 100, 2),
            "status": status, "out_of_sample": enough,
            "confidence": "VALIDACION_TEMPORAL_DESCRIPTIVA",
        })
    return results


def build_learning_advisory(
    records: Iterable[Mapping[str, Any]],
    *,
    strategy_ids: Iterable[str],
    context: Mapping[str, Any],
    as_of: datetime,
    methodology_version: str,
    minimum_sample_size: int = 10,
) -> dict[str, Any]:
    """Congela evidencia conocida antes de una alerta sin intervenir en su decisión."""
    if as_of.tzinfo is None:
        raise ValueError("as_of debe incluir zona horaria.")
    if minimum_sample_size <= 0:
        raise ValueError("El tamaño mínimo debe ser mayor que cero.")
    normalized_methodology = methodology_version.strip()
    if not normalized_methodology:
        raise ValueError("methodology_version es obligatoria.")
    requested = {str(item) for item in strategy_ids}
    eligible_records = []
    for record in records:
        if (
            not record.get("trade_taken")
            or str(record.get("methodology_version", "")).strip()
            != normalized_methodology
            or not requested.intersection(
                str(item) for item in record.get("strategies", [])
            )
        ):
            continue
        created_at = str(record.get("created_at", ""))
        event_at = str(record.get("event_at", ""))
        try:
            known_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            occurred_at = datetime.fromisoformat(event_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (
            known_at.tzinfo is not None
            and occurred_at.tzinfo is not None
            and occurred_at <= known_at <= as_of
        ):
            eligible_records.append(record)
    rows: list[dict[str, Any]] = []
    dimensions = ("trend_15m", "relative_volatility_15m", "session_segment", "benchmark_regime", "benchmark_alignment")
    for strategy in sorted(requested):
        for mode in ("PAPER", "REAL"):
            base = [item for item in eligible_records if item.get("mode") == mode and strategy in {str(value) for value in item.get("strategies", [])}]
            rows.append(_advisory_row(strategy, mode, "GENERAL", "TODOS", base, minimum_sample_size))
            for dimension in dimensions:
                value = str(context.get(dimension, "NO_DISPONIBLE"))
                if value == "NO_DISPONIBLE":
                    continue
                matched = [item for item in base if str(item.get("context", {}).get(dimension, "NO_DISPONIBLE")) == value]
                rows.append(_advisory_row(strategy, mode, dimension, value, matched, minimum_sample_size))
    manifest = [
        {
            "outcome_id": item.get("outcome_id"), "created_at": item.get("created_at"),
            "event_at": item.get("event_at"), "mode": item.get("mode"),
            "result": item.get("result"),
            "methodology_version": item.get("methodology_version"),
            "strategies": sorted(str(value) for value in item.get("strategies", [])),
            "context": {str(key): str(value) for key, value in sorted(item.get("context", {}).items())},
        }
        for item in sorted(eligible_records, key=lambda value: int(value.get("outcome_id", 0)))
    ]
    fingerprint = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "as_of": as_of.isoformat(), "minimum_sample_size": minimum_sample_size,
        "methodology_version": normalized_methodology,
        "known_outcome_count": len(eligible_records), "rows": rows,
        "source_outcome_ids": [item["outcome_id"] for item in manifest],
        "history_fingerprint_sha256": fingerprint,
        "policy_version": "LEARNING_ADVISORY_V2",
        "authority": "DESCRIPTIVA_NO_INFLUYE_DECISION",
        "disclaimer": "Evidencia histórica; no modifica estrategias, compuertas ni CALL/PUT.",
    }


def build_directional_learning_signal(
    records: Iterable[Mapping[str, Any]],
    *,
    strategy_ids: Iterable[str],
    context: Mapping[str, Any],
    current_direction: str,
    as_of: datetime,
    methodology_version: str,
    mode: str = "PAPER",
    minimum_sample_size: int = 10,
) -> dict[str, Any]:
    """Compara CALL/PUT históricos para una alerta ya confirmada.

    Esta señal solo comunica evidencia posterior y nunca sustituye las
    compuertas metodológicas ni convierte una muestra pequeña en certeza.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of debe incluir zona horaria.")
    if minimum_sample_size <= 0:
        raise ValueError("El tamaño mínimo debe ser mayor que cero.")
    normalized_direction = current_direction.strip().upper()
    if normalized_direction not in {"CALL", "PUT"}:
        return {
            "status": "NO_DIRECCIONAL", "recommended_direction": None,
            "current_direction": normalized_direction, "rows": [],
            "authority": "DESCRIPTIVA_NO_INFLUYE_DECISION",
        }
    normalized_mode = mode.strip().upper()
    normalized_methodology = methodology_version.strip()
    requested = {str(item) for item in strategy_ids}
    eligible: list[Mapping[str, Any]] = []
    for record in records:
        if (
            not record.get("trade_taken")
            or str(record.get("mode", "")).upper() != normalized_mode
            or str(record.get("methodology_version", "")).strip() != normalized_methodology
            or not requested.intersection(str(item) for item in record.get("strategies", []))
            or str(record.get("decision", "")).upper() not in {"CALL", "PUT"}
            or str(record.get("result", "")).upper() not in {"POSITIVO", "NEGATIVO"}
        ):
            continue
        try:
            known_at = datetime.fromisoformat(str(record.get("created_at", "")).replace("Z", "+00:00"))
            occurred_at = datetime.fromisoformat(str(record.get("event_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if known_at.tzinfo is not None and occurred_at.tzinfo is not None and occurred_at <= known_at <= as_of:
            eligible.append(record)

    dimensions = ("trend_15m", "relative_volatility_15m", "session_segment", "benchmark_regime", "benchmark_alignment")
    contextual = [
        item for item in eligible
        if all(
            str(item.get("context", {}).get(dimension, "NO_DISPONIBLE")) == str(context.get(dimension))
            for dimension in dimensions
            if str(context.get(dimension, "NO_DISPONIBLE")) != "NO_DISPONIBLE"
        )
    ]
    source = contextual if len(contextual) >= minimum_sample_size else eligible
    rows: list[dict[str, Any]] = []
    for strategy in sorted(requested):
        items = [item for item in source if strategy in {str(value) for value in item.get("strategies", [])}]
        direction_rows: dict[str, dict[str, Any]] = {}
        for direction in ("CALL", "PUT"):
            direction_items = [item for item in items if str(item.get("decision", "")).upper() == direction]
            wins = sum(str(item.get("result", "")).upper() == "POSITIVO" for item in direction_items)
            low, high = _wilson_interval(wins, len(direction_items))
            direction_rows[direction] = {
                "direction": direction, "sample_size": len(direction_items),
                "positive_count": wins,
                "positive_rate": round(wins / len(direction_items) * 100, 2) if direction_items else None,
                "interval_95_low": round(low * 100, 2),
                "interval_95_high": round(high * 100, 2),
            }
        ranked = sorted(direction_rows.values(), key=lambda row: (row["interval_95_low"], row["positive_rate"] or 0), reverse=True)
        best = ranked[0]
        calibrated = best["sample_size"] >= minimum_sample_size and best["interval_95_low"] >= 50.0
        confidence_score, priority = _direction_confidence_score(best["interval_95_low"], best["sample_size"], minimum_sample_size)
        rows.append({
            "strategy_id": strategy, "source": "CONTEXTO" if source is contextual else "GENERAL",
            "current_direction": normalized_direction, "historical_direction": best["direction"] if calibrated else None,
            "calibrated": calibrated, "sample_size": best["sample_size"],
            "positive_rate": best["positive_rate"], "interval_95_low": best["interval_95_low"],
            "confidence_score": confidence_score, "priority": priority,
            "call": direction_rows["CALL"], "put": direction_rows["PUT"],
        })
    calibrated_rows = [row for row in rows if row["calibrated"]]
    directions = {row["historical_direction"] for row in calibrated_rows}
    if not calibrated_rows:
        status = "MUESTRA_INSUFICIENTE"
        recommendation = None
        summary_score = 0.0
        summary_priority = "MINIMA"
    elif len(directions) > 1:
        status = "HISTORIAL_CONFLICTIVO"
        recommendation = None
        summary_score = round(sum(row["confidence_score"] for row in calibrated_rows) / len(calibrated_rows), 2)
        summary_priority = _direction_priority(summary_score)
    else:
        recommendation = next(iter(directions))
        status = "APRENDIZAJE_ALINEADO" if recommendation == normalized_direction else "APRENDIZAJE_CONTRARIO"
        summary_score = round(sum(row["confidence_score"] for row in calibrated_rows) / len(calibrated_rows), 2)
        summary_priority = _direction_priority(summary_score)
    return {
        "status": status, "recommended_direction": recommendation,
        "current_direction": normalized_direction, "minimum_sample_size": minimum_sample_size,
        "known_outcome_count": len(source), "summary_score": summary_score,
        "priority": summary_priority, "rows": rows,
        "authority": "DESCRIPTIVA_NO_INFLUYE_DECISION",
        "disclaimer": "Patrón histórico de resultados confirmados; no sustituye compuertas ni garantiza el próximo movimiento.",
    }


def audit_learning_advisory(
    advisory: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    *,
    strategy_ids: Iterable[str],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Comprueba si la asesoría congelada aún se reproduce con el historial actual."""
    if not advisory.get("policy_version") or not advisory.get("history_fingerprint_sha256"):
        return {"status": "NO_AUDITABLE", "reasons": ["La asesoría no contiene identidad reproducible."]}
    try:
        as_of = datetime.fromisoformat(str(advisory["as_of"]).replace("Z", "+00:00"))
        minimum = int(advisory["minimum_sample_size"])
        methodology_version = str(advisory["methodology_version"]).strip()
    except (KeyError, TypeError, ValueError):
        return {"status": "NO_AUDITABLE", "reasons": ["Faltan política o corte temporal válidos."]}
    if not methodology_version:
        return {
            "status": "NO_AUDITABLE",
            "reasons": ["Falta la version metodologica de la asesoria."],
        }
    current = build_learning_advisory(
        records, strategy_ids=strategy_ids, context=context, as_of=as_of,
        methodology_version=methodology_version,
        minimum_sample_size=minimum,
    )
    reasons: list[str] = []
    if advisory.get("policy_version") != current["policy_version"]:
        reasons.append("La versión de la política es distinta.")
    if advisory.get("history_fingerprint_sha256") != current["history_fingerprint_sha256"]:
        reasons.append("El conjunto histórico disponible para ese corte cambió.")
    if advisory.get("rows") != current["rows"]:
        reasons.append("Las métricas congeladas no coinciden con el recálculo.")
    return {
        "status": "REPRODUCIBLE" if not reasons else "HISTORIAL_CAMBIO",
        "reasons": reasons,
        "stored_fingerprint": advisory.get("history_fingerprint_sha256"),
        "current_fingerprint": current["history_fingerprint_sha256"],
        "stored_outcome_count": advisory.get("known_outcome_count"),
        "current_outcome_count": current["known_outcome_count"],
        "authority": "AUDITORIA_NO_INFLUYE_DECISION",
    }


def _advisory_row(strategy: str, mode: str, dimension: str, value: str, items: list[Mapping[str, Any]], minimum: int) -> dict[str, Any]:
    wins = sum(item.get("result") == "POSITIVO" for item in items)
    low, high = _wilson_interval(wins, len(items))
    sufficient = len(items) >= minimum
    return {
        "strategy_id": strategy, "mode": mode, "context_dimension": dimension,
        "context_value": value, "sample_size": len(items),
        "observed_positive_rate": round(wins / len(items) * 100, 2) if items else None,
        "positive_rate_interval_95_low": round(low * 100, 2),
        "positive_rate_interval_95_high": round(high * 100, 2),
        "status": "MUESTRA_MINIMA_ALCANZADA" if sufficient else "MUESTRA_INSUFICIENTE",
        "eligible_for_review": sufficient,
    }
