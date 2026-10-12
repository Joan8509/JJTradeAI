"""Estudio de precios posteriores a la emisión; no simula órdenes ni opciones."""

from datetime import datetime, timedelta, timezone
import json
import math
from zoneinfo import ZoneInfo

from paper_signal_evaluator import _confirmed_directional_strategies


MODEL = "APERTURA_MINUTO_POSTERIOR_A_EMISION_V1"
MARKET_ZONE = ZoneInfo("America/New_York")


def _utc(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return stamp.astimezone(timezone.utc)


def evaluate_entry_path(*, available_at, trigger, bias, horizon, bars, as_of):
    """Entrada en apertura del minuto siguiente; salida al cierre del horizonte exacto."""
    if bias not in {"CALL", "PUT"} or horizon <= 0:
        raise ValueError("Dirección u horizonte inválido.")
    if any(stamp.tzinfo is None for stamp in (available_at, trigger, as_of)):
        raise ValueError("Las fechas deben incluir zona horaria.")
    available_at, trigger, as_of = (stamp.astimezone(timezone.utc) for stamp in (available_at, trigger, as_of))
    signal_ready = max(available_at, trigger + timedelta(minutes=1))
    entry_at = signal_ready.replace(second=0, microsecond=0) + timedelta(minutes=1)
    exit_at = entry_at + timedelta(minutes=horizon)
    session = trigger.astimezone(MARKET_ZONE).date()
    if entry_at.astimezone(MARKET_ZONE).date() != session:
        return {"status": "REGISTRO_RETROACTIVO"}
    if exit_at.astimezone(MARKET_ZONE).date() != session:
        return {"status": "FUERA_DE_SESION"}
    local_entry = entry_at.astimezone(MARKET_ZONE)
    local_exit = exit_at.astimezone(MARKET_ZONE)
    if (local_entry.hour, local_entry.minute) < (9, 30) or (local_exit.hour, local_exit.minute) > (16, 0):
        return {"status": "FUERA_DE_SESION"}
    if exit_at > as_of:
        return {"status": "HORIZONTE_PENDIENTE"}
    by_stamp = {_utc(row["timestamp"]): row for row in bars}
    timestamps = [entry_at + timedelta(minutes=minute) for minute in range(horizon)]
    if any(stamp not in by_stamp for stamp in timestamps):
        return {"status": "DATOS_INCOMPLETOS"}
    path = [by_stamp[stamp] for stamp in timestamps]
    values = [float(row[key]) for row in path for key in ("open", "high", "low", "close")]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        return {"status": "DATOS_INVALIDOS"}
    if any(float(row["high"]) < max(float(row["open"]), float(row["close"]), float(row["low"]))
           or float(row["low"]) > min(float(row["open"]), float(row["close"]), float(row["high"])) for row in path):
        return {"status": "DATOS_INVALIDOS"}
    entry_price = float(path[0]["open"])
    exit_price = float(path[-1]["close"])
    direction = 1 if bias == "CALL" else -1
    raw = (exit_price / entry_price - 1) * 100
    favorable = ((max(float(row["high"]) for row in path) / entry_price - 1) if bias == "CALL"
                 else (1 - min(float(row["low"]) for row in path) / entry_price)) * 100
    adverse = ((min(float(row["low"]) for row in path) / entry_price - 1) if bias == "CALL"
               else (1 - max(float(row["high"]) for row in path) / entry_price)) * 100
    return {
        "status": "EVALUADA", "model": MODEL, "signal_available_at": available_at.isoformat(),
        "entry_timestamp": entry_at.isoformat(), "exit_timestamp": exit_at.isoformat(),
        "entry_price": entry_price, "exit_price": exit_price,
        "entry_delay_seconds": (entry_at - available_at).total_seconds(),
        "underlying_return_pct": round(raw, 6), "directional_return_pct": round(raw * direction, 6),
        "favorable_excursion_pct": round(max(0, favorable), 6),
        "adverse_excursion_pct": round(min(0, adverse), 6),
    }


def collect_entry_outcomes(connection, *, as_of, strategy_ids):
    rows = {"CONFIRMADAS": [], "CANDIDATAS": []}
    counts = {}
    for alert in connection.execute(
        "SELECT id,symbol,provider,feed,created_at,trigger_timestamp,payload_json FROM strategy_alerts "
        "WHERE detected_count>0 AND julianday(created_at)<=julianday(?)", (as_of.isoformat(),)
    ):
        report = json.loads(alert["payload_json"])
        confirmed = set(_confirmed_directional_strategies(report))
        detected = {(item.get("strategy_id"), item.get("bias"))
                    for item in report.get("strategies", {}).get("evaluations", [])
                    if item.get("detected") is True and item.get("strategy_id") in strategy_ids
                    and item.get("bias") in {"CALL", "PUT"}}
        available = _utc(alert["created_at"])
        trigger = _utc(alert["trigger_timestamp"])
        entry_at = max(available, trigger + timedelta(minutes=1)).replace(second=0, microsecond=0) + timedelta(minutes=1)
        bars = []
        if entry_at.astimezone(MARKET_ZONE).date() == trigger.astimezone(MARKET_ZONE).date():
            bars = connection.execute(
                "SELECT timestamp,open,high,low,close FROM minute_bars WHERE symbol=? AND provider=? AND feed=? "
                "AND timestamp>=? AND timestamp<? ORDER BY timestamp",
                (alert["symbol"], alert["provider"], alert["feed"], entry_at.isoformat(),
                 min(entry_at + timedelta(minutes=60), as_of).isoformat()),
            ).fetchall()
        for strategy, bias in sorted(detected):
            cohort = "CONFIRMADAS" if (strategy, bias) in confirmed else "CANDIDATAS"
            for horizon in (15, 30, 60):
                outcome = evaluate_entry_path(available_at=available, trigger=trigger, bias=bias,
                                              horizon=horizon, bars=bars, as_of=as_of)
                key = (cohort, outcome["status"])
                counts[key] = counts.get(key, 0) + 1
                if outcome["status"] == "EVALUADA":
                    outcome.update(alert_id=alert["id"], strategy_id=strategy, bias=bias, horizon_minutes=horizon,
                                   symbol=alert["symbol"], provider=alert["provider"], feed=alert["feed"],
                                   methodology_version=report.get("methodology_version", ""),
                                   context=report.get("learning_context", {}))
                    rows[cohort].append(outcome)
    return rows, [{"cohort": cohort, "status": status, "count": count} for (cohort, status), count in sorted(counts.items())]
