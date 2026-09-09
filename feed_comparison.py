"""Compara Alpaca IEX contra SIP historico sin ejecutar ordenes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from alpaca_market_data import AlpacaMarketConfig, AlpacaMarketDataProvider
from analysis_pipeline import AnalysisContext, run_detection_pipeline
from safe_diagnostics import sanitize_diagnostic_detail


TIMEFRAMES = ("15m", "1H", "1D")
PRICE_FIELDS = ("open", "high", "low", "close")


def _detector_snapshot(datasets: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, object]]:
    pipeline = run_detection_pipeline(AnalysisContext(datasets=datasets))
    return {
        f"{item.strategy_id}@{item.timeframe}": {
            "detected": bool(item.detected),
            "bias": item.bias.value,
            "required_criteria_satisfied": bool(item.required_criteria_satisfied),
        }
        for item in pipeline.evaluations
    }


def _datasets_at_15m_close(
    datasets: Mapping[str, pd.DataFrame], bar_start: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    """Corta cada temporalidad sin permitir informacion posterior al cierre."""
    start = pd.Timestamp(bar_start)
    if start.tzinfo is None:
        raise ValueError("bar_start debe incluir zona horaria.")
    start = start.tz_convert("UTC")
    evaluation_time = start + pd.Timedelta(minutes=15)
    result: dict[str, pd.DataFrame] = {}
    for timeframe in TIMEFRAMES:
        frame = datasets[timeframe].copy()
        dates = pd.to_datetime(frame["date"], utc=True)
        local_starts = dates.dt.tz_convert("America/New_York")
        if timeframe == "15m":
            mask = dates <= start
        elif timeframe == "1H":
            normal_ends = local_starts + pd.Timedelta(hours=1)
            session_ends = local_starts.dt.normalize() + pd.Timedelta(hours=16)
            period_ends = pd.Series(
                [min(end, session_end) for end, session_end in zip(normal_ends, session_ends)],
                index=frame.index,
            )
            mask = period_ends.dt.tz_convert("UTC") <= evaluation_time
        else:
            session_ends = local_starts.dt.normalize() + pd.Timedelta(hours=16)
            mask = session_ends.dt.tz_convert("UTC") <= evaluation_time
        result[timeframe] = frame.loc[mask].reset_index(drop=True)
    return result


def compare_historical_detectors(
    iex_datasets: Mapping[str, pd.DataFrame],
    sip_datasets: Mapping[str, pd.DataFrame],
    *, sessions: int = 5,
    snapshotter: Callable[[Mapping[str, pd.DataFrame]], dict[str, dict[str, object]]] = _detector_snapshot,
) -> dict[str, Any]:
    """Reproduce cierres recientes y cuenta divergencias metodologicas."""
    if sessions <= 0:
        return {"session_count": 0, "evaluated_close_count": 0, "divergent_close_count": 0, "divergence_rate_pct": 0.0, "by_detector": [], "examples": []}
    iex_dates = pd.to_datetime(iex_datasets["15m"]["date"], utc=True)
    sip_dates = pd.to_datetime(sip_datasets["15m"]["date"], utc=True)
    shared = pd.DatetimeIndex(sorted(set(iex_dates).intersection(set(sip_dates))))
    if shared.empty:
        return {"session_count": 0, "evaluated_close_count": 0, "divergent_close_count": 0, "divergence_rate_pct": 0.0, "by_detector": [], "examples": []}
    local_days = pd.Index(shared.tz_convert("America/New_York").date)
    selected_days = tuple(dict.fromkeys(local_days))[-sessions:]
    selected = [timestamp for timestamp, day in zip(shared, local_days) if day in selected_days]
    divergent_closes = 0
    divergence_episodes = 0
    detector_counts: dict[str, int] = {}
    detector_episodes: dict[str, int] = {}
    previous_changed: set[str] = set()
    examples = []
    for timestamp in selected:
        left = snapshotter(_datasets_at_15m_close(iex_datasets, timestamp))
        right = snapshotter(_datasets_at_15m_close(sip_datasets, timestamp))
        changed = [key for key in sorted(set(left).union(right)) if left.get(key) != right.get(key)]
        if not changed:
            previous_changed = set()
            continue
        divergent_closes += 1
        changed_set = set(changed)
        if not previous_changed:
            divergence_episodes += 1
        for detector_id in changed:
            detector_counts[detector_id] = detector_counts.get(detector_id, 0) + 1
            if detector_id not in previous_changed:
                detector_episodes[detector_id] = detector_episodes.get(detector_id, 0) + 1
        if len(examples) < 20:
            examples.append({
                "bar_start": timestamp.isoformat(),
                "detectors": changed,
                "iex": {key: left.get(key) for key in changed},
                "sip": {key: right.get(key) for key in changed},
            })
        previous_changed = changed_set
    evaluated = len(selected)
    return {
        "session_count": len(selected_days),
        "evaluated_close_count": evaluated,
        "divergent_close_count": divergent_closes,
        "divergence_rate_pct": round((divergent_closes / evaluated) * 100, 4) if evaluated else 0.0,
        "unique_divergence_episode_count": divergence_episodes,
        "by_detector": [
            {
                "detector": key,
                "divergent_close_count": value,
                "unique_episode_count": detector_episodes.get(key, 0),
            }
            for key, value in sorted(detector_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "examples": examples,
    }


def compare_feed_bundles(
    iex: object, sip: object, *, symbol: str, replay_sessions: int = 0,
) -> dict[str, Any]:
    """Produce diferencias descriptivas reproducibles entre dos bundles."""
    timeframe_rows: dict[str, dict[str, object]] = {}
    for timeframe in TIMEFRAMES:
        left = iex.datasets[timeframe].copy()
        right = sip.datasets[timeframe].copy()
        left["date"] = pd.to_datetime(left["date"], utc=True)
        right["date"] = pd.to_datetime(right["date"], utc=True)
        merged = left.merge(right, on="date", how="outer", suffixes=("_iex", "_sip"), indicator=True)
        matched = merged[merged["_merge"] == "both"].copy()
        metrics: dict[str, object] = {
            "iex_bar_count": int(len(left)),
            "sip_bar_count": int(len(right)),
            "matched_bar_count": int(len(matched)),
            "iex_only_count": int((merged["_merge"] == "left_only").sum()),
            "sip_only_count": int((merged["_merge"] == "right_only").sum()),
        }
        for field in PRICE_FIELDS:
            differences = (matched[f"{field}_iex"] - matched[f"{field}_sip"]).abs()
            metrics[f"{field}_mean_abs_difference"] = float(differences.mean()) if len(differences) else None
            metrics[f"{field}_max_abs_difference"] = float(differences.max()) if len(differences) else None
        if len(matched):
            close_denominator = matched["close_sip"].abs().replace(0, pd.NA)
            close_bps = ((matched["close_iex"] - matched["close_sip"]).abs() / close_denominator) * 10000
            volume_denominator = matched["volume_sip"].abs().replace(0, pd.NA)
            volume_pct = ((matched["volume_iex"] - matched["volume_sip"]).abs() / volume_denominator) * 100
            metrics["close_max_difference_bps"] = float(close_bps.max()) if close_bps.notna().any() else None
            metrics["volume_mean_abs_difference_pct"] = float(volume_pct.mean()) if volume_pct.notna().any() else None
        else:
            metrics["close_max_difference_bps"] = None
            metrics["volume_mean_abs_difference_pct"] = None
        timeframe_rows[timeframe] = metrics

    iex_detectors = _detector_snapshot(iex.datasets)
    sip_detectors = _detector_snapshot(sip.datasets)
    detector_differences = []
    for detector_id in sorted(set(iex_detectors).union(sip_detectors)):
        left = iex_detectors.get(detector_id)
        right = sip_detectors.get(detector_id)
        if left != right:
            detector_differences.append({"detector": detector_id, "iex": left, "sip": right})
    historical = compare_historical_detectors(
        iex.datasets, sip.datasets, sessions=replay_sessions
    )
    return {
        "symbol": symbol.strip().upper(),
        "status": "DIFERENCIAS_DETECTOR" if detector_differences else "DETECTORES_COINCIDEN",
        "authority": "COMPARACION_DESCRIPTIVA_NO_AUTORIZA_OPERACIONES",
        "timeframes": timeframe_rows,
        "detector_difference_count": len(detector_differences),
        "detector_differences": detector_differences,
        "historical_replay": historical,
    }


def run_comparison(
    symbols: tuple[str, ...], *, days: int, output: Path,
    replay_sessions: int = 5,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if days <= 0:
        raise ValueError("days debe ser mayor que cero.")
    base = AlpacaMarketConfig.from_env()
    end = datetime.now(timezone.utc) - timedelta(minutes=16)
    start = end - timedelta(days=days)
    iex_provider = AlpacaMarketDataProvider(AlpacaMarketConfig(base.api_key, base.api_secret, "iex", base.base_url))
    sip_provider = AlpacaMarketDataProvider(AlpacaMarketConfig(base.api_key, base.api_secret, "sip", base.base_url))
    results = []
    errors = []
    for symbol in symbols:
        try:
            if progress:
                progress(f"{symbol}: descargando IEX ({days} dias)...")
            iex = iex_provider.fetch_bundle(symbol, start=start, end=end)
            if progress:
                progress(f"{symbol}: IEX listo; descargando SIP historico...")
            sip = sip_provider.fetch_bundle(symbol, start=start, end=end)
            if progress:
                progress(f"{symbol}: comparando velas, indicadores y estrategias...")
            results.append(compare_feed_bundles(
                iex, sip, symbol=symbol, replay_sessions=replay_sessions
            ))
            if progress:
                progress(f"{symbol}: comparacion terminada.")
        except Exception as error:
            errors.append({"symbol": symbol, "detail": sanitize_diagnostic_detail(error)})
            if progress:
                progress(f"{symbol}: no disponible; el detalle seguro quedara en el reporte.")
    payload = {
        "status": "COMPLETO" if results and not errors else "PARCIAL" if results else "NO_DISPONIBLE",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "sip_delay_minutes": 16},
        "paper_only": True,
        "symbols": list(symbols),
        "results": results,
        "errors": errors,
        "secrets_exposed": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="SPY,QQQ")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--output", default="exports/feed_comparison.json")
    parser.add_argument("--replay-sessions", type=int, default=5)
    args = parser.parse_args()
    symbols = tuple(dict.fromkeys(item.strip().upper() for item in args.symbols.split(",") if item.strip()))
    if not symbols:
        raise SystemExit("Indica al menos un simbolo.")
    payload = run_comparison(
        symbols, days=args.days, output=Path(args.output),
        replay_sessions=args.replay_sessions, progress=print
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] != "NO_DISPONIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
