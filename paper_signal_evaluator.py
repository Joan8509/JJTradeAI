"""Evaluacion PAPER posterior de estrategias confirmadas sobre el subyacente."""

from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from market_store import DEFAULT_MARKET_DATABASE


DEFAULT_HORIZONS = (15, 30, 60)
MARKET_ZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PaperSignalEvaluation:
    alert_id: int
    strategy_id: str
    bias: str
    horizon_minutes: int
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    underlying_return_pct: float
    directional_return_pct: float
    favorable_excursion_pct: float
    adverse_excursion_pct: float
    result: str


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    proportion = wins / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def build_paper_signal_advisory(
    database_path: str | Path,
    *,
    strategy_ids: Iterable[str],
    as_of: datetime,
    methodology_version: str,
    horizon_minutes: int = 60,
    minimum_sample_size: int = 20,
) -> dict[str, Any]:
    """Resume solo evidencia que ya existia antes de la alerta actual."""
    if as_of.tzinfo is None:
        raise ValueError("as_of debe incluir zona horaria.")
    if horizon_minutes <= 0 or minimum_sample_size <= 0:
        raise ValueError("Horizonte y muestra minima deben ser positivos.")
    requested = tuple(sorted({str(item).strip() for item in strategy_ids if str(item).strip()}))
    rows = []
    if requested:
        PaperSignalEvaluationRepository(database_path)
        with closing(sqlite3.connect(database_path)) as connection:
            connection.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in requested)
            evidence = connection.execute(
                "SELECT strategy_id, result, directional_return_pct "
                "FROM paper_signal_evaluations "
                f"WHERE strategy_id IN ({placeholders}) AND horizon_minutes=? "
                "AND methodology_version=? AND evaluated_at<=? AND exit_timestamp<=?",
                (*requested, horizon_minutes, methodology_version.strip(),
                 as_of.astimezone(timezone.utc).isoformat(),
                 as_of.astimezone(timezone.utc).isoformat()),
            ).fetchall()
        for strategy_id in requested:
            items = [item for item in evidence if item["strategy_id"] == strategy_id]
            total = len(items)
            wins = sum(item["result"] == "CORRECTA" for item in items)
            losses = sum(item["result"] == "INCORRECTA" for item in items)
            flats = total - wins - losses
            low, high = _wilson_interval(wins, total)
            average = (
                sum(float(item["directional_return_pct"]) for item in items) / total
                if total else None
            )
            if total < minimum_sample_size:
                status = "MUESTRA_INSUFICIENTE"
            elif low > 0.5 and average is not None and average > 0:
                status = "EVIDENCIA_FAVORABLE"
            elif high < 0.5 or (average is not None and average <= 0):
                status = "EVIDENCIA_DEBIL"
            else:
                status = "EVIDENCIA_NO_CONCLUYENTE"
            rows.append({
                "strategy_id": strategy_id,
                "horizon_minutes": horizon_minutes,
                "sample_size": total,
                "correct_count": wins,
                "incorrect_count": losses,
                "flat_count": flats,
                "observed_correct_rate": round(wins / total * 100, 2) if total else None,
                "correct_rate_interval_95_low": round(low * 100, 2),
                "correct_rate_interval_95_high": round(high * 100, 2),
                "average_directional_return_pct": round(average, 4) if average is not None else None,
                "status": status,
            })
    return {
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "horizon_minutes": horizon_minutes,
        "minimum_sample_size": minimum_sample_size,
        "methodology_version": methodology_version.strip(),
        "rows": rows,
        "authority": "DESCRIPTIVA_PAPER_NO_MODIFICA_DECISION",
    }


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Los timestamps deben incluir zona horaria.")
    return parsed.astimezone(timezone.utc)


def _confirmed_directional_strategies(
    report: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    strategies = report.get("strategies", {})
    evaluations = strategies.get("evaluations", ()) if isinstance(strategies, Mapping) else ()
    result = []
    for item in evaluations if isinstance(evaluations, list) else ():
        if not isinstance(item, Mapping) or item.get("detected") is not True:
            continue
        bias = str(item.get("bias", ""))
        strategy_id = str(item.get("strategy_id", "")).strip()
        criteria = item.get("criteria", ())
        required = [
            criterion for criterion in criteria
            if isinstance(criterion, Mapping) and criterion.get("required") is True
        ] if isinstance(criteria, list) else []
        if (
            strategy_id
            and bias in {"CALL", "PUT"}
            and required
            and all(str(item.get("status")) == "CUMPLE" for item in required)
        ):
            result.append((strategy_id, bias))
    return tuple(result)


class PaperSignalEvaluationRepository:
    def __init__(self, database_path: str | Path = DEFAULT_MARKET_DATABASE) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_signal_evaluations (
                    alert_id INTEGER NOT NULL,
                    strategy_id TEXT NOT NULL,
                    bias TEXT NOT NULL,
                    horizon_minutes INTEGER NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    entry_timestamp TEXT NOT NULL,
                    exit_timestamp TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    underlying_return_pct REAL NOT NULL,
                    directional_return_pct REAL NOT NULL,
                    favorable_excursion_pct REAL NOT NULL,
                    adverse_excursion_pct REAL NOT NULL,
                    result TEXT NOT NULL,
                    methodology_version TEXT NOT NULL,
                    PRIMARY KEY (alert_id, strategy_id, horizon_minutes),
                    FOREIGN KEY(alert_id) REFERENCES strategy_alerts(id)
                );
                CREATE INDEX IF NOT EXISTS idx_paper_signal_result
                ON paper_signal_evaluations(strategy_id, horizon_minutes, result);
                """
            )
            connection.commit()

    def save(self, evaluation: PaperSignalEvaluation, methodology_version: str) -> bool:
        with closing(sqlite3.connect(self.database_path)) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO paper_signal_evaluations (
                    alert_id, strategy_id, bias, horizon_minutes, evaluated_at,
                    entry_timestamp, exit_timestamp, entry_price, exit_price,
                    underlying_return_pct, directional_return_pct,
                    favorable_excursion_pct, adverse_excursion_pct, result,
                    methodology_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.alert_id, evaluation.strategy_id, evaluation.bias,
                    evaluation.horizon_minutes, datetime.now(timezone.utc).isoformat(),
                    evaluation.entry_timestamp, evaluation.exit_timestamp,
                    evaluation.entry_price, evaluation.exit_price,
                    evaluation.underlying_return_pct,
                    evaluation.directional_return_pct,
                    evaluation.favorable_excursion_pct,
                    evaluation.adverse_excursion_pct, evaluation.result,
                    methodology_version,
                ),
            )
            connection.commit()
            return cursor.rowcount == 1

    def summary(self) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT strategy_id, bias, horizon_minutes, COUNT(*) AS sample_size,
                       SUM(result='CORRECTA') AS correct_count,
                       SUM(result='INCORRECTA') AS incorrect_count,
                       SUM(result='PLANA') AS flat_count,
                       ROUND(AVG(directional_return_pct), 4) AS average_directional_return_pct,
                       ROUND(AVG(favorable_excursion_pct), 4) AS average_favorable_excursion_pct,
                       ROUND(AVG(adverse_excursion_pct), 4) AS average_adverse_excursion_pct
                FROM paper_signal_evaluations
                GROUP BY strategy_id, bias, horizon_minutes
                ORDER BY sample_size DESC, strategy_id, horizon_minutes
                """
            ).fetchall()
        return [dict(row) for row in rows]


def _evaluate_one(
    *, alert_id: int, strategy_id: str, bias: str, trigger: datetime,
    horizon: int, bars: Sequence[sqlite3.Row], neutral_threshold_pct: float,
) -> PaperSignalEvaluation | None:
    same_session = [
        row for row in bars
        if _utc(row["timestamp"]).astimezone(MARKET_ZONE).date()
        == trigger.astimezone(MARKET_ZONE).date()
    ]
    entry_candidates = [row for row in same_session if _utc(row["timestamp"]) == trigger]
    target = trigger + timedelta(minutes=horizon)
    exit_candidates = [row for row in same_session if _utc(row["timestamp"]) >= target]
    if not entry_candidates or not exit_candidates:
        return None
    entry = entry_candidates[-1]
    exit_bar = exit_candidates[0]
    path = [
        row for row in same_session
        if trigger < _utc(row["timestamp"]) <= _utc(exit_bar["timestamp"])
    ]
    if not path:
        return None
    entry_price = float(entry["close"])
    exit_price = float(exit_bar["close"])
    raw_return = (exit_price / entry_price - 1.0) * 100.0
    direction = 1.0 if bias == "CALL" else -1.0
    directional = raw_return * direction
    if bias == "CALL":
        favorable = (max(float(row["high"]) for row in path) / entry_price - 1.0) * 100.0
        adverse = (min(float(row["low"]) for row in path) / entry_price - 1.0) * 100.0
    else:
        favorable = (1.0 - min(float(row["low"]) for row in path) / entry_price) * 100.0
        adverse = (1.0 - max(float(row["high"]) for row in path) / entry_price) * 100.0
    result = (
        "CORRECTA" if directional > neutral_threshold_pct
        else "INCORRECTA" if directional < -neutral_threshold_pct
        else "PLANA"
    )
    return PaperSignalEvaluation(
        alert_id, strategy_id, bias, horizon,
        trigger.isoformat(), _utc(exit_bar["timestamp"]).isoformat(),
        entry_price, exit_price, round(raw_return, 6), round(directional, 6),
        round(favorable, 6), round(adverse, 6), result,
    )


def evaluate_available_signals(
    database_path: str | Path = DEFAULT_MARKET_DATABASE, *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    neutral_threshold_pct: float = 0.0,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    normalized_horizons = tuple(sorted({int(item) for item in horizons}))
    if not normalized_horizons or any(item <= 0 for item in normalized_horizons):
        raise ValueError("Los horizontes deben ser minutos positivos.")
    if neutral_threshold_pct < 0:
        raise ValueError("El umbral neutral no puede ser negativo.")
    repository = PaperSignalEvaluationRepository(database_path)
    normalized_symbols = tuple(sorted({
        str(item).strip().upper() for item in (symbols or ()) if str(item).strip()
    }))
    inserted = eligible = pending = 0
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        query = (
            "SELECT id, provider, feed, symbol, trigger_timestamp, payload_json "
            "FROM strategy_alerts WHERE confirmed_count > 0"
        )
        values: list[object] = []
        if normalized_symbols:
            query += " AND symbol IN (" + ",".join("?" for _ in normalized_symbols) + ")"
            values.extend(normalized_symbols)
        alerts = connection.execute(query + " ORDER BY id", values).fetchall()
        for alert in alerts:
            report = json.loads(alert["payload_json"])
            strategies = _confirmed_directional_strategies(report)
            trigger = _utc(alert["trigger_timestamp"])
            bars = connection.execute(
                "SELECT timestamp, high, low, close FROM minute_bars "
                "WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? "
                "ORDER BY timestamp",
                (alert["provider"], alert["feed"], alert["symbol"], trigger.isoformat()),
            ).fetchall()
            for strategy_id, bias in strategies:
                for horizon in normalized_horizons:
                    eligible += 1
                    evaluation = _evaluate_one(
                        alert_id=int(alert["id"]), strategy_id=strategy_id, bias=bias,
                        trigger=trigger, horizon=horizon, bars=bars,
                        neutral_threshold_pct=neutral_threshold_pct,
                    )
                    if evaluation is None:
                        pending += 1
                        continue
                    inserted += int(repository.save(
                        evaluation, str(report.get("methodology_version", ""))
                    ))
    return {
        "eligible_evaluations": eligible,
        "inserted": inserted,
        "pending": pending,
        "horizons": list(normalized_horizons),
        "neutral_threshold_pct": neutral_threshold_pct,
        "symbols": list(normalized_symbols),
        "summary": repository.summary(),
        "authority": "DESCRIPTIVA_PAPER_NO_AUTORIZA_OPERACION",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=str(DEFAULT_MARKET_DATABASE))
    parser.add_argument("--horizons", default="15,30,60")
    parser.add_argument("--neutral-threshold-pct", type=float, default=0.0)
    args = parser.parse_args(argv)
    result = evaluate_available_signals(
        args.database,
        horizons=[int(item) for item in args.horizons.split(",") if item.strip()],
        neutral_threshold_pct=args.neutral_threshold_pct,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
