"""Radar intravela de Bollinger separado de las señales confirmadas."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from zoneinfo import ZoneInfo

import pandas as pd

from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars


def evaluate_live_bollinger_preview(
    minute_bars: pd.DataFrame, *, symbol: str, as_of: datetime
) -> dict[str, object]:
    """Evalua la vela 15m parcial; nunca confirma ni autoriza una entrada."""
    aggregated = aggregate_minute_bars(minute_bars, "15m")
    prepared = prepare_market_frame(aggregated)
    latest = prepared.iloc[-1]
    close = float(latest["close"])
    upper = float(latest["bollinger_upper"])
    lower = float(latest["bollinger_lower"])
    if pd.isna(upper) or pd.isna(lower):
        status, bias = "NO_DISPONIBLE", "SIN_SESGO"
    elif close > upper:
        status, bias = "EXPUESTO_SUPERIOR", "ESPERAR"
    elif close < lower:
        status, bias = "EXPUESTO_INFERIOR", "ESPERAR"
    else:
        status, bias = "DENTRO", "SIN_SESGO"
    local = pd.Timestamp(as_of).tz_convert("America/New_York")
    minutes_to_close = 15 - ((local.minute - 30) % 15) - 1
    return {
        "symbol": symbol.strip().upper(), "timeframe": "15m",
        "status": status, "bias": bias, "price": close,
        "bollinger_upper": upper, "bollinger_lower": lower,
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "minutes_to_close": max(0, minutes_to_close),
        "confirmed": False, "can_operate": False,
        "authority": "OBSERVACION_INTRAVELA_NO_AUTORIZA_OPERACION",
    }


class LiveBollingerPreviewRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS live_bollinger_preview ("
                "symbol TEXT PRIMARY KEY, updated_at TEXT NOT NULL, "
                "status TEXT NOT NULL, payload_json TEXT NOT NULL)"
            )

    def save(self, payload: dict[str, object]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO live_bollinger_preview(symbol,updated_at,status,payload_json) "
                "VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
                "updated_at=excluded.updated_at,status=excluded.status,payload_json=excluded.payload_json",
                (payload["symbol"], payload["as_of"], payload["status"],
                 json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )

    def current(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM live_bollinger_preview ORDER BY symbol"
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def attach_strategy_preview(
    payload: dict[str, object], report: dict[str, object]
) -> dict[str, object]:
    """Adjunta detectores provisionales sin copiar una decision operativa."""
    strategies = report.get("strategies", {})
    raw = strategies.get("evaluations", []) if isinstance(strategies, dict) else []
    detected = []
    try:
        observed_at = datetime.fromisoformat(
            str(payload.get("as_of", "")).replace("Z", "+00:00")
        ).astimezone(ZoneInfo("America/New_York"))
    except ValueError:
        observed_at = None
    opening_only_ids = {
        "RETORNO_BOLLINGER_LATERAL_ALCISTA",
        "RETORNO_BOLLINGER_LATERAL_BAJISTA",
    }
    for item in raw:
        if not isinstance(item, dict):
            continue
        strategy_id = str(item.get("strategy_id", ""))
        criteria = [
            criterion for criterion in item.get("criteria", [])
            if isinstance(criterion, dict) and criterion.get("required") is True
        ]
        pending_confirmation = bool(
            strategy_id
            and not strategy_id.startswith("SIN_")
            and item.get("detected") is not True
            and criteria
            and any(
                criterion.get("status") in {"NO_DISPONIBLE", "REQUIERE_REVISION"}
                for criterion in criteria
            )
            and all(
                criterion.get("status")
                in {"CUMPLE", "NO_DISPONIBLE", "REQUIERE_REVISION"}
                for criterion in criteria
            )
        )
        if item.get("detected") is not True and not pending_confirmation:
            continue
        if strategy_id in opening_only_ids and (
            observed_at is None
            or (observed_at.hour, observed_at.minute) < (9, 30)
            or (observed_at.hour, observed_at.minute) > (9, 34)
        ):
            continue
        pending = [
            str(criterion.get("name") or criterion.get("criterion_id"))
            for criterion in criteria
            if criterion.get("status") != "CUMPLE"
        ]
        detected.append({
            "strategy_id": strategy_id, "name": item.get("name"),
            "bias": "ESPERAR" if pending_confirmation else item.get("bias"),
            "potential_bias": item.get("bias") if pending_confirmation else None,
            "timeframe": item.get("timeframe"),
            "next_requirement": pending[0] if pending else "Confirmar al cierre",
            "pending_confirmation": pending_confirmation,
        })
    generic_exposures = {
        "EXPUESTO_BOLLINGER_INFERIOR", "EXPUESTO_BOLLINGER_SUPERIOR",
    }
    strong_bollinger_push = {
        "EXPUESTO_BOLLINGER_INFERIOR": "PUT",
        "EXPUESTO_BOLLINGER_SUPERIOR": "CALL",
    }
    methodology_biases = {
        str(item.get("bias"))
        for item in detected
        if str(item.get("strategy_id")) not in generic_exposures
        and str(item.get("bias")) in {"CALL", "PUT"}
    }
    directional_conflict = len(methodology_biases) > 1
    for item in detected:
        strategy_id = str(item.get("strategy_id"))
        if item.get("pending_confirmation"):
            item["bias"] = "ESPERAR"
            item["direction_status"] = "EN FORMACION - REQUIERE CONFIRMACION"
        elif strategy_id in generic_exposures:
            probable_bias = strong_bollinger_push.get(strategy_id, "ESPERAR")
            item["bias"] = "ESPERAR"
            item["potential_bias"] = probable_bias
            item["direction_status"] = (
                f"PROBABLE {probable_bias} - SIN DIRECCIÓN CONFIRMADA"
            )
            item["next_requirement"] = (
                "La exposición es fuerte y sugiere una dirección probable, "
                "pero aún no está confirmada por una estrategia metodológica."
            )
        elif directional_conflict:
            item["bias"] = "ESPERAR"
            item["direction_status"] = "DIRECCIONES EN CONFLICTO"
            item["next_requirement"] = (
                "Resolver la contradicción entre estrategias CALL y PUT."
            )
        else:
            item["direction_status"] = "DIRECCIÓN PRELIMINAR"
    return {**payload, "strategies": detected}
