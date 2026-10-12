"""Seguimiento descriptivo de resultados PAPER, sin cambiar las decisiones."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from market_store import DEFAULT_MARKET_DATABASE
from scanner_instance import ScannerInstanceLease, consume_stop_request
from analysis_pipeline import DETECTOR_REGISTRY
from paper_signal_evaluator import _confirmed_directional_strategies, _evaluate_one
from signal_entry_research import MODEL as ENTRY_MODEL, collect_entry_outcomes
from minute_gap_audit import build_gap_audit


MARKET_ZONE = ZoneInfo("America/New_York")
DETECTOR_NAMES = {
    "PRIMER_SALTO": "Primer Salto", "SALTO_LATERALIDAD_HORA": "Salto de Lateralidad en Hora",
    "CT15": "Cambio de Tendencia en 15", "EFECTO_IMAN": "Efecto Imán",
    "REBOTE_PUNTO_MEDIO": "Rebote en Punto Medio", "RETORNO_BOLLINGER_LATERAL": "Retorno a Bollinger",
    "CAMBIO_TENDENCIA_HORA": "Cambio de Tendencia en Hora", "MOMENTUM": "Momentum",
    "EXPUESTO_BOLLINGER": "Expuesto Bollinger (complementario)",
}
LIMITATIONS = [
    "Resultados sobre el subyacente; no son ganancias de opciones ni incluyen costos.",
    "Se cuentan resultados positivos, negativos y planos; no se invierte una señal por perder.",
    "Se descartan ventanas superpuestas del mismo símbolo en la muestra sin solapamiento.",
    "Distintos símbolos y sesiones pueden estar correlacionados; los conteos no prueban independencia.",
    "La comparación temporal usa sesiones anteriores y posteriores, sin optimizar reglas.",
    "La evidencia es descriptiva y no modifica señales, umbrales ni autorización de operar.",
]


def _stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("La evidencia debe tener zona horaria.")
    return result.astimezone(timezone.utc)


def _metrics(rows: list[dict]) -> dict:
    count = len(rows)
    return {
        "sample_size": count,
        "session_count": len({row["session"] for row in rows}),
        "symbol_count": len({row["symbol"] for row in rows}),
        "positive_count": sum(row["directional_return_pct"] > 0 for row in rows),
        "negative_count": sum(row["directional_return_pct"] < 0 for row in rows),
        "flat_count": sum(row["directional_return_pct"] == 0 for row in rows),
        "positive_rate_pct": round(sum(row["directional_return_pct"] > 0 for row in rows) / count * 100, 2) if count else None,
        "average_directional_return_pct": round(sum(row["directional_return_pct"] for row in rows) / count, 6) if count else None,
        "average_favorable_excursion_pct": round(sum(row["favorable_excursion_pct"] for row in rows) / count, 6) if count else None,
        "average_adverse_excursion_pct": round(sum(row["adverse_excursion_pct"] for row in rows) / count, 6) if count else None,
    }


def _research_groups(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for item in rows:
        row = dict(item)
        row["session"] = _stamp(row["entry_timestamp"]).astimezone(MARKET_ZONE).date().isoformat()
        groups[(row["strategy_id"], row["bias"], row["horizon_minutes"], row["methodology_version"])].append(row)
    return groups


def _non_overlapping(items: list[dict]) -> list[dict]:
    retained = []
    last_exit = {}
    for row in sorted(items, key=lambda r: (_stamp(r["entry_timestamp"]), r["alert_id"])):
        key = (row["symbol"], row["provider"], row["feed"])
        entry = _stamp(row["entry_timestamp"])
        if key not in last_exit or entry >= last_exit[key]:
            retained.append(row)
            last_exit[key] = _stamp(row["exit_timestamp"])
    return retained


def summarize_research(rows: list[dict]) -> list[dict]:
    result = []
    for (strategy, bias, horizon, version), items in sorted(_research_groups(rows).items()):
        retained = _non_overlapping(items)
        sessions = sorted({row["session"] for row in retained})
        split = max(1, int(len(sessions) * 0.7)) if sessions else 0
        prior_sessions = set(sessions[:split])
        prior = [row for row in retained if row["session"] in prior_sessions]
        recent = [row for row in retained if row["session"] not in prior_sessions]
        by_symbol = defaultdict(list)
        by_context = defaultdict(list)
        for row in retained:
            by_symbol[row["symbol"]].append(row)
            context = row.get("context", {})
            for dimension in ("session_segment", "trend_15m", "benchmark_alignment"):
                value = context.get(dimension)
                if value and value != "NO_DISPONIBLE":
                    by_context[(dimension, value)].append(row)
        result.append({
            "strategy_id": strategy, "bias": bias, "horizon_minutes": horizon,
            "methodology_version": version,
            "all_evaluations": _metrics(items),
            "non_overlapping": _metrics(retained),
            "prior_period": _metrics(prior), "recent_period": _metrics(recent),
            "recent_period_starts": sessions[split] if split < len(sessions) else None,
            "by_symbol": [{"symbol": symbol, **_metrics(group)} for symbol, group in sorted(by_symbol.items())],
            "by_context": [{"dimension": dimension, "value": value, **_metrics(group)} for (dimension, value), group in sorted(by_context.items())],
        })
    return result


EXPERIMENT_FILTERS = {
    "EVITAR_LATERAL": ("trend_15m", "Evitar contexto lateral"),
    "SOLO_APERTURA": ("session_segment", "Solo apertura"),
    "TENDENCIA_ALINEADA": ("trend_15m", "Tendencia alineada con la dirección"),
}


def _filter_matches(row: dict, rule: str) -> bool:
    context = row.get("context", {})
    if rule == "EVITAR_LATERAL":
        return context.get("trend_15m") in {"ALCISTA", "BAJISTA"}
    if rule == "SOLO_APERTURA":
        return context.get("session_segment") == "APERTURA"
    return context.get("trend_15m") == ("ALCISTA" if row["bias"] == "CALL" else "BAJISTA")


def _filter_comparison(rows: list[dict], rule: str) -> dict:
    dimension = EXPERIMENT_FILTERS[rule][0]
    allowed = {"ALCISTA", "BAJISTA", "LATERAL"} if dimension == "trend_15m" else {"APERTURA", "MEDIA_SESION", "CIERRE", "FUERA_DE_SESION"}
    baseline = [row for row in rows if row.get("context", {}).get(dimension) in allowed]
    filtered = [row for row in baseline if _filter_matches(row, rule)]
    base, selected = _metrics(baseline), _metrics(filtered)
    enough = selected["sample_size"] >= 10 and selected["session_count"] >= 3
    positive_delta = round(selected["positive_rate_pct"] - base["positive_rate_pct"], 2) if filtered else None
    return_delta = round(selected["average_directional_return_pct"] - base["average_directional_return_pct"], 6) if filtered else None
    adverse_delta = round(selected["average_adverse_excursion_pct"] - base["average_adverse_excursion_pct"], 6) if filtered else None
    if not enough:
        status = "MUESTRA_INSUFICIENTE"
    elif len(filtered) == len(baseline):
        status = "SIN_CAMBIO"
    elif positive_delta > 0 and return_delta > 0 and adverse_delta >= 0:
        status = "MEJORA_DESCRIPTIVA" if selected["average_directional_return_pct"] > 0 else "MEJORA_RELATIVA_RETORNO_NEGATIVO"
    else:
        status = "MEJORA_NO_DEMOSTRADA"
    return {
        "baseline": base, "filtered": selected,
        "excluded_unknown_context": len(rows) - len(baseline),
        "retained_pct": round(len(filtered) / len(baseline) * 100, 2) if baseline else None,
        "positive_rate_delta_points": positive_delta,
        "average_return_delta_pct": return_delta,
        "average_adverse_excursion_delta_pct": adverse_delta,
        "status": status,
    }


def build_filter_experiments(rows: list[dict], *, cohort: str, as_of: datetime, frozen: list[dict]) -> list[dict]:
    """Fija hipótesis y su evaluación inicial; nunca las reajusta con datos futuros."""
    if as_of.tzinfo is None:
        raise ValueError("as_of debe incluir zona horaria.")
    existing = {tuple(item["key"]): item for item in frozen if item["cohort"] == cohort}
    output = []
    for (strategy, bias, horizon, version), items in sorted(_research_groups(rows).items()):
        items = _non_overlapping(items)
        sessions = sorted({row["session"] for row in items})
        split = max(1, int(len(sessions) * 0.7))
        training_sessions = set(sessions[:split])
        training = [row for row in items if row["session"] in training_sessions]
        test = [row for row in items if row["session"] not in training_sessions]
        for rule, (_, name) in EXPERIMENT_FILTERS.items():
            key = (cohort, strategy, bias, horizon, version, rule)
            if key in existing:
                experiment = dict(existing[key])
                for period in ("historical_training", "historical_test"):
                    comparison = dict(experiment[period])
                    if comparison["status"] == "MEJORA_DESCRIPTIVA" and comparison["filtered"]["average_directional_return_pct"] <= 0:
                        comparison["status"] = "MEJORA_RELATIVA_RETORNO_NEGATIVO"
                    experiment[period] = comparison
            else:
                train_comparison = _filter_comparison(training, rule)
                test_comparison = _filter_comparison(test, rule)
                experiment = {
                    "key": list(key), "cohort": cohort, "strategy_id": strategy, "bias": bias,
                    "horizon_minutes": horizon, "methodology_version": version,
                    "rule": rule, "name": name, "frozen_at": as_of.astimezone(timezone.utc).isoformat(),
                    "historical_training": train_comparison, "historical_test": test_comparison,
                    "historical_test_starts": sessions[split] if split < len(sessions) else None,
                }
            frozen_at = _stamp(experiment["frozen_at"])
            # Solo sesiones completas posteriores al registro de la hipótesis.
            frozen_session = frozen_at.astimezone(MARKET_ZONE).date().isoformat()
            future = [row for row in items if row["session"] > frozen_session and _stamp(row["entry_timestamp"]) > frozen_at]
            experiment["forward_test"] = _filter_comparison(future, rule)
            experiment["authority"] = "EXPERIMENTO_PAPER_NO_MODIFICA_SENALES"
            output.append(experiment)
    # Conservar hipótesis aunque una regeneración temporalmente no contenga su muestra.
    present = {tuple(item["key"]) for item in output}
    for key, item in existing.items():
        if key not in present:
            experiment = dict(item)
            experiment["forward_test"] = _filter_comparison([], experiment["rule"])
            output.append(experiment)
    return output


def summarize_detector_coverage(alerts) -> list[dict]:
    """Incluye todos los detectores, incluso sin resultados confirmados."""
    coverage = {}
    for detector in DETECTOR_REGISTRY:
        coverage[detector.detector_id] = {
            "detector_id": detector.detector_id, "name": DETECTOR_NAMES[detector.detector_id],
            "complementary": detector.detector_id == "EXPUESTO_BOLLINGER",
            "evaluated_scans": 0, "detected_scans": 0, "confirmed_scans": 0,
            "skipped_scans": 0, "error_scans": 0, "missing_scans": 0,
            "latest_by_symbol": {}, "blockers": Counter(),
            "unavailable_requirements": Counter(),
        }
    for alert in alerts:
        report = json.loads(alert["payload_json"])
        payload = report.get("strategies", {})
        evaluations = payload.get("evaluations", [])
        confirmed = {item[0] for item in _confirmed_directional_strategies(report)}
        for detector in DETECTOR_REGISTRY:
            stats = coverage[detector.detector_id]
            ids = set(detector.strategy_ids + detector.diagnostic_ids)
            items = [item for item in evaluations if item.get("strategy_id") in ids]
            unavailable = {
                (criterion.get("criterion_id", ""), criterion.get("name", ""), criterion.get("status", ""))
                for item in items for criterion in item.get("criteria", [])
                if criterion.get("required") and criterion.get("status") in {"NO_DISPONIBLE", "REQUIERE_REVISION"}
            }
            stats["unavailable_requirements"].update(unavailable)
            detected = [item for item in items if item.get("detected") is True]
            if detector.detector_id in payload.get("errors", {}):
                status = "ERROR"
                stats["error_scans"] += 1
            elif detector.detector_id in payload.get("skipped", {}):
                status = "OMITIDA"
                stats["skipped_scans"] += 1
            elif not items:
                status = "SIN_REGISTRO"
                stats["missing_scans"] += 1
            else:
                stats["evaluated_scans"] += 1
                stats["detected_scans"] += bool(detected)
                is_confirmed = any(item.get("strategy_id") in confirmed for item in detected)
                stats["confirmed_scans"] += is_confirmed
                status = "CONFIRMADA" if is_confirmed else "CANDIDATA_PENDIENTE" if detected else "SIN_DETECCION"
                for item in detected:
                    for criterion in item.get("criteria", []):
                        if criterion.get("required") and criterion.get("status") != "CUMPLE":
                            stats["blockers"][(criterion.get("name") or criterion.get("criterion_id", ""), criterion.get("status", ""))] += 1
            latest = stats["latest_by_symbol"].get(alert["symbol"])
            if latest is None or _stamp(alert["trigger_timestamp"]) >= _stamp(latest["timestamp"]):
                stats["latest_by_symbol"][alert["symbol"]] = {
                    "status": status, "timestamp": alert["trigger_timestamp"],
                    "unavailable_requirements": [{"criterion_id": cid, "name": name, "status": condition}
                                                 for cid, name, condition in sorted(unavailable)],
                }
    result = []
    for stats in coverage.values():
        stats["blockers"] = [{"criterion": criterion, "status": status, "count": count}
                             for (criterion, status), count in stats["blockers"].most_common(5)]
        stats["latest_status_counts"] = dict(Counter(item["status"] for item in stats["latest_by_symbol"].values()))
        stats["unavailable_requirements"] = [
            {"criterion_id": cid, "name": name, "status": status, "scan_count": count}
            for (cid, name, status), count in stats["unavailable_requirements"].most_common()
        ]
        result.append(stats)
    return result


def candidate_outcomes(connection: sqlite3.Connection, cutoff: datetime) -> tuple[list[dict], int]:
    """Observa candidatas sin confirmarlas ni insertarlas en el aprendizaje aprobado."""
    rows = []
    pending = 0
    strategy_ids = {sid for detector in DETECTOR_REGISTRY for sid in detector.strategy_ids}
    for alert in connection.execute(
        "SELECT id, symbol, provider, feed, trigger_timestamp, payload_json FROM strategy_alerts "
        "WHERE detected_count>0 AND julianday(created_at)<=julianday(?)",
        (cutoff.isoformat(),),
    ):
        report = json.loads(alert["payload_json"])
        confirmed = set(_confirmed_directional_strategies(report))
        candidates = {(item.get("strategy_id"), item.get("bias"))
                      for item in report.get("strategies", {}).get("evaluations", [])
                      if item.get("detected") is True and item.get("strategy_id") in strategy_ids
                      and item.get("bias") in {"CALL", "PUT"}}
        candidates -= confirmed
        if not candidates:
            continue
        trigger = _stamp(alert["trigger_timestamp"])
        end = min(trigger + timedelta(minutes=60), cutoff)
        bars = connection.execute(
            "SELECT timestamp,high,low,close FROM minute_bars WHERE symbol=? AND provider=? AND feed=? "
            "AND timestamp>=? AND timestamp<=? ORDER BY timestamp",
            (alert["symbol"], alert["provider"], alert["feed"], trigger.isoformat(), end.isoformat()),
        ).fetchall()
        timestamps = {_stamp(bar["timestamp"]) for bar in bars}
        for strategy, bias in sorted(candidates):
            for horizon in (15, 30, 60):
                target = trigger + timedelta(minutes=horizon)
                # No usar una vela tardía para suplir el cierre que falta.
                if trigger not in timestamps or target not in timestamps or target > cutoff:
                    pending += 1
                    continue
                evaluation = _evaluate_one(alert_id=alert["id"], strategy_id=strategy, bias=bias,
                                           trigger=trigger, horizon=horizon, bars=bars, neutral_threshold_pct=0.0)
                if evaluation is None:
                    pending += 1
                    continue
                row = asdict(evaluation)
                row.update(symbol=alert["symbol"], provider=alert["provider"], feed=alert["feed"],
                           methodology_version=report.get("methodology_version", ""),
                           context=report.get("learning_context", {}))
                rows.append(row)
    return rows, pending


def build_research_report(database: str | Path, *, as_of: datetime | None = None, frozen_experiments: list[dict] | None = None) -> dict:
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        raise ValueError("as_of debe incluir zona horaria.")
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)) as connection:
        connection.row_factory = sqlite3.Row
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        evidence = connection.execute(
            "SELECT e.*, a.symbol, a.provider, a.feed, a.payload_json "
            "FROM paper_signal_evaluations e JOIN strategy_alerts a ON a.id=e.alert_id "
            "WHERE julianday(e.exit_timestamp)<=julianday(?) AND julianday(e.evaluated_at)<=julianday(?)",
            (cutoff, cutoff),
        ).fetchall()
        health = connection.execute(
            "SELECT status, updated_at, last_bar_at FROM live_service_health "
            "WHERE service_id='live_strategy_scanner'"
        ).fetchone()
        coverage = summarize_detector_coverage(connection.execute(
            "SELECT symbol,trigger_timestamp,payload_json FROM strategy_alerts "
            "WHERE julianday(created_at)<=julianday(?) ORDER BY id", (cutoff,),
        ))
        candidate_rows, candidate_pending = candidate_outcomes(connection, as_of.astimezone(timezone.utc))
        entry_rows, entry_statuses = collect_entry_outcomes(
            connection, as_of=as_of.astimezone(timezone.utc),
            strategy_ids={sid for detector in DETECTOR_REGISTRY for sid in detector.strategy_ids},
        )
        gap_audit = build_gap_audit(connection, as_of=as_of.astimezone(timezone.utc))
    rows = []
    for item in evidence:
        row = dict(item)
        row["context"] = json.loads(row.pop("payload_json")).get("learning_context", {})
        rows.append(row)
    return {
        "generated_at": cutoff, "evaluation_count": len(rows),
        "scanner_health": dict(health) if health else None,
        "limitations": LIMITATIONS,
        "result_definition": "Positivo si retorno direccional > 0; negativo si < 0; plano si = 0. Sin costos.",
        "strategies": summarize_research(rows),
        "detector_coverage": coverage,
        "candidate_strategies": summarize_research(candidate_rows),
        "candidate_evaluation_count": len(candidate_rows),
        "candidate_pending_count": candidate_pending,
        "candidate_authority": "INVESTIGACION_NO_CONFIRMADA_NO_MODIFICA_SENALES",
        "entry_model": ENTRY_MODEL,
        "entry_status_counts": entry_statuses,
        "entry_strategies": summarize_research(entry_rows["CONFIRMADAS"]),
        "entry_candidate_strategies": summarize_research(entry_rows["CANDIDATAS"]),
        "entry_observations": entry_rows,
        "minute_gap_audit": gap_audit,
        "filter_experiments": (
            build_filter_experiments(rows, cohort="CONFIRMADAS", as_of=as_of, frozen=frozen_experiments or [])
            + build_filter_experiments(candidate_rows, cohort="CANDIDATAS", as_of=as_of, frozen=frozen_experiments or [])
        ),
    }


def write_report(report: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    lines = ["# Investigación de estrategias PAPER", "", f"Actualizado: {report['generated_at']}", "",
             f"Evaluaciones disponibles: {report['evaluation_count']}", "", report["result_definition"], "",
             "Las tasas son observaciones históricas, no probabilidades de la próxima señal.", "",
             "| Estrategia | Dirección | Minutos | Versión | Muestra sin solapamiento | Sesiones | Positivos % | Retorno medio % | Anterior % | Reciente % |",
             "|---|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for row in report["strategies"]:
        stats = row["non_overlapping"]
        values = [row["strategy_id"], row["bias"], row["horizon_minutes"], row["methodology_version"], stats["sample_size"], stats["session_count"], stats["positive_rate_pct"], stats["average_directional_return_pct"], row["prior_period"]["positive_rate_pct"], row["recent_period"]["positive_rate_pct"]]
        lines.append("| " + " | ".join(str(v) if v is not None else "N/D" for v in values) + " |")
    lines += ["", *["- " + item for item in LIMITATIONS], ""]
    lines += ["## Cobertura de todos los detectores", "",
              "| Estrategia | Escaneos evaluados | Detectados | Confirmados | Omitidos | Errores |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in report.get("detector_coverage", []):
        lines.append(f"| {row['name']} | {row['evaluated_scans']} | {row['detected_scans']} | {row['confirmed_scans']} | {row['skipped_scans']} | {row['error_scans']} |")
    lines += ["", f"Movimientos posteriores de candidatas pendientes: {report.get('candidate_evaluation_count', 0)}.",
              "Estas observaciones no convierten candidatas en señales confirmadas. Ver detalle por estrategia en latest.json.", ""]
    lines += ["## Pruebas de filtros", "", "Tres hipótesis fijas: evitar lateralidad, solo apertura y tendencia alineada.",
              "Cada prueba conserva la evaluación inicial y contrasta sesiones nuevas posteriores a su registro.",
              "Mejora descriptiva no demuestra significación estadística, rentabilidad ni precisión futura.",
              "Los detalles y las muestras de cada prueba están en filter_experiments de latest.json.", ""]
    lines += ["## Datos y definiciones pendientes", "",
              "Se incluyen requisitos sin datos o que requieren revisión aunque la estrategia no haya sido detectada.",
              "Cada requisito se cuenta una vez por escaneo y detector. No se incluyen criterios evaluados como NO_CUMPLE.", "",
              "| Estrategia | Requisito | Estado | Escaneos afectados |", "|---|---|---|---:|"]
    for detector in report.get("detector_coverage", []):
        for requirement in detector.get("unavailable_requirements", []):
            lines.append(f"| {detector['name']} | {requirement['name']} | {requirement['status']} | {requirement['scan_count']} |")
    lines += ["", "## Estudio de entrada posterior a la emisión", "",
              "Referencia: apertura del minuto posterior a la disponibilidad de la señal; salida al cierre del horizonte exacto.",
              "Exige barras continuas. No equivale a una ejecución y no incluye costos ni opciones.", "",
              "| Grupo | Estado | Observaciones (todos los horizontes) |", "|---|---|---:|"]
    for item in report.get("entry_status_counts", []):
        lines.append(f"| {item['cohort']} | {item['status']} | {item['count']} |")
    lines.append("")
    for name, content in (("latest.json", json.dumps(report, ensure_ascii=False, indent=2)), ("latest.md", "\n".join(lines))):
        target = output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=str(DEFAULT_MARKET_DATABASE))
    parser.add_argument("--output", type=Path, default=Path("exports/strategy_research"))
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    if args.interval < 10:
        parser.error("El intervalo mínimo es 10 segundos.")
    def update_report():
        latest = args.output / "latest.json"
        frozen = json.loads(latest.read_text(encoding="utf-8")).get("filter_experiments", []) if latest.exists() else []
        write_report(build_research_report(args.database, frozen_experiments=frozen), args.output)
    if not args.watch:
        update_report()
        return
    with ScannerInstanceLease(args.output / "worker.lock") as lease:
        while not consume_stop_request(args.output / "worker.stop", owner_token=lease.token):
            try:
                update_report()
            except (sqlite3.Error, OSError, ValueError) as error:
                print(f"Informe no actualizado: {type(error).__name__}", flush=True)
            for _ in range(args.interval):
                if consume_stop_request(args.output / "worker.stop", owner_token=lease.token):
                    return
                time.sleep(1)


if __name__ == "__main__":
    main()
