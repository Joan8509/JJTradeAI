"""Prealerta PAPER aislada de Retorno a Bollinger a los cinco minutos."""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from strategies.retorno_bollinger_lateral import evaluate_retorno_bollinger_lateral


EARLY_WINDOW_MINUTES = 5


def is_opening_five_minute_close(timestamp: object) -> bool:
    """Indica si la barra cerrada corresponde a las 09:34 de Nueva York."""
    value = pd.Timestamp(timestamp)
    if value.tzinfo is None:
        raise ValueError("El timestamp temprano debe incluir zona horaria.")
    local = value.tz_convert("America/New_York")
    return local.hour == 9 and local.minute == 34


def build_early_return_report(
    minute_bars: pd.DataFrame,
    *,
    symbol: str,
) -> dict[str, Any] | None:
    """Confirma solo Retorno a Bollinger sin otorgar autoridad operativa."""
    if minute_bars.empty or len(minute_bars) < EARLY_WINDOW_MINUTES:
        return None
    normalized = minute_bars.sort_values("date").reset_index(drop=True)
    latest = pd.Timestamp(normalized.iloc[-1]["date"])
    if not is_opening_five_minute_close(latest):
        return None
    frame_15m = prepare_market_frame(aggregate_minute_bars(normalized, "15m"))
    evaluation = evaluate_retorno_bollinger_lateral(
        frame_15m,
        minute_1m=normalized,
    )
    if not evaluation.detected or not evaluation.required_criteria_satisfied:
        return None
    criteria = [
        {
            "criterion_id": item.criterion_id,
            "name": item.name,
            "status": item.status.value,
            "required": item.required,
            "detail": item.detail,
            "source": item.source,
        }
        for item in evaluation.criteria
    ]
    return {
        "symbol": symbol.strip().upper(),
        "data_as_of": latest.isoformat(),
        "mode": "PAPER",
        "preliminary": True,
        "decision": {
            "decision": "NO_OPERAR",
            "reason": "Prealerta de cinco minutos; requiere ciclo completo y compuertas.",
        },
        "strategy_summary": {"detected": 1, "confirmed": 1},
        "strategies": {
            "evaluations": [
                {
                    "strategy_id": evaluation.strategy_id,
                    "name": evaluation.name,
                    "bias": evaluation.bias.value,
                    "detected": True,
                    "required_criteria_satisfied": True,
                    "criteria": criteria,
                }
            ],
            "errors": {},
        },
        "alert_event": {
            "type": "PREALERTA_5M",
            "channel": "MERCADO",
            "priority": "MEDIA",
            "requires_ack": True,
            "reason": "Retorno a Bollinger confirmado en los primeros cinco minutos.",
            "authority": "PREALERTA_NO_MODIFICA_DECISION",
        },
    }
