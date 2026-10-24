"""Estudio exclusivo de continuidad de salida Bollinger 15m, sin órdenes."""
import argparse
import json
import math
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from bollinger_phone_worker import detect_values, bands_at_open, STRATEGY_VERSION
from data_providers import prepare_market_frame
from live_market import aggregate_minute_bars
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore
from paper_signal_evaluator import _wilson_interval
from scanner_instance import ScannerInstanceLease
from watchlist_config import load_watchlist

OUTPUT = Path(__file__).resolve().parent / "exports" / "bollinger_study"
HORIZONS = (5, 15, 30, 60)


def replay_events(bars, *, symbol, provider, feed):
    """Reconstruye cada minuto sin usar el cierre final de la vela en formación."""
    aggregates = prepare_market_frame(aggregate_minute_bars(bars, "15m"))
    positions = {pd.Timestamp(row.date): index for index, row in aggregates.iterrows()}
    records = aggregates.to_dict("records")
    closes = aggregates["close"].tolist()
    previous_cache = {}
    seen, events = set(), []
    for row in bars.itertuples(index=False):
        stamp = pd.Timestamp(row.date)
        local = stamp.tz_convert("America/New_York")
        if not ("09:30" <= local.strftime("%H:%M") < "16:00"):
            continue
        candle = stamp.floor("15min")
        position = positions.get(candle, 0)
        if position < 20:
            continue
        if position not in previous_cache:
            previous_cache[position] = (records[position-1], closes[position-19:position])
        previous, prior_closes = previous_cache[position]
        # Bandas parciales: 19 cierres completos anteriores + el precio conocido ahora.
        values = prior_closes + [float(row.close)]
        mid = sum(values) / 20
        variance = sum((value-mid)**2 for value in values) / 20
        deviation = math.sqrt(variance)
        opening = records[position]["open"]
        opening_upper, opening_lower = bands_at_open(prior_closes, opening)
        side = detect_values(previous["close"], previous["bollinger_upper"], previous["bollinger_lower"], previous["bollinger_mid"],
                             row.close, mid+2*deviation, mid-2*deviation, mid, opening=opening,
                             opening_upper=opening_upper, opening_lower=opening_lower)
        key = (candle, side)
        if side is None or key in seen:
            continue
        seen.add(key)
        events.append({"symbol": symbol, "provider": provider, "feed": feed, "version": STRATEGY_VERSION, "side": side,
                       "candle": candle.isoformat(), "price": float(row.close), "source_timestamp": stamp.isoformat(),
                       "detected_at": (stamp+pd.Timedelta(minutes=1)).isoformat(), "origin": "RECONSTRUIDA"})
    return events


def evaluate_event(event, indexed, session_close, *, as_of, horizon):
    source = pd.Timestamp(event["source_timestamp"])
    available = pd.Timestamp(event["detected_at"])
    # La observación en vivo puede haberse recibido tarde: no usa precios ya pasados como salida.
    if event.get('source_kind')=='TRADE':
        # Exact trade timestamps have seconds. The first full minute after
        # detection is observable; adding one minute to the tick would create
        # non-minute timestamps and make every result appear incomplete.
        start=max(source,available).floor('min')+pd.Timedelta(minutes=1)
    else:
        start = max(source + pd.Timedelta(minutes=1), available.floor("min") + pd.Timedelta(minutes=1)) if event.get("origin") == "EN_VIVO" else source + pd.Timedelta(minutes=1)
    end = start + pd.Timedelta(minutes=horizon-1)
    result = {**event, "horizon": horizon, "start": start.isoformat(), "end": end.isoformat()}
    if session_close is None or end + pd.Timedelta(minutes=1) > session_close:
        return {**result, "status": "SIN_RECORRIDO_ANTES_DEL_CIERRE"}
    if end + pd.Timedelta(minutes=1) > pd.Timestamp(as_of):
        return {**result, "status": "PENDIENTE"}
    expected = pd.date_range(start, end, freq="min")
    if not expected.isin(indexed.index).all():
        return {**result, "status": "DATOS_INCOMPLETOS"}
    window = indexed.loc[expected]
    for row in window.itertuples():
        if not all(math.isfinite(float(value)) and value > 0 for value in (row.open, row.high, row.low, row.close)) or not row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high:
            return {**result, "status": "DATOS_INVALIDOS"}
    reference = float(event["price"])
    if not math.isfinite(reference) or reference <= 0:
        return {**result, "status": "DATOS_INVALIDOS"}
    sign = 1 if event["side"] == "SUPERIOR" else -1
    change = sign * (float(window.iloc[-1].close)/reference-1)*100
    favorable = (float(window.high.max())/reference-1)*100 if sign == 1 else (1-float(window.low.min())/reference)*100
    adverse = (1-float(window.low.min())/reference)*100 if sign == 1 else (float(window.high.max())/reference-1)*100
    return {**result, "status": "EVALUADA", "directional_return_pct": change,
            "favorable_excursion_pct": max(0, favorable), "adverse_excursion_pct": max(0, adverse),
            "result": "POSITIVO" if change > 0 else "NEGATIVO" if change < 0 else "SIN_CAMBIO"}


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["origin"], row["provider"], row["feed"], row["symbol"], row["side"], row["horizon"])].append(row)
    summary = []
    for (origin, provider, feed, symbol, side, horizon), group in sorted(groups.items()):
        independent = []
        last_end = None
        for row in sorted((r for r in group if r["status"] == "EVALUADA"), key=lambda r:r["start"]):
            if last_end is None or pd.Timestamp(row["start"]) > last_end:
                independent.append(row)
                last_end = pd.Timestamp(row["end"])
        count = len(independent)
        positive = sum(r["result"] == "POSITIVO" for r in independent)
        negative = sum(r["result"] == "NEGATIVO" for r in independent)
        lower, upper = _wilson_interval(positive, count)
        dates = sorted({pd.Timestamp(r["source_timestamp"]).tz_convert("America/New_York").date().isoformat() for r in independent})
        summary.append({"origin": origin, "provider": provider, "feed": feed, "symbol": symbol, "side": side, "horizon": horizon,
                        "detected": len(group), "sample": count, "sessions": len(dates), "positive": positive, "negative": negative,
                        "unchanged": count-positive-negative, "positive_pct": round(positive/count*100,2) if count else None,
                        "average_return_pct": round(sum(r["directional_return_pct"] for r in independent)/count,4) if count else None,
                        "interval_low": round(lower*100,2), "interval_high": round(upper*100,2),
                        "status": "MUESTRA_INSUFICIENTE" if count < 20 or len(dates) < 5 else "DESCRIPTIVO_NO_CALIBRADO",
                        "excluded": {str(k): int(v) for k, v in pd.Series([r["status"] for r in group if r["status"] != "EVALUADA"]).value_counts().items()}})
    return summary


def build_report(database=DEFAULT_MARKET_DATABASE, *, as_of=None, days=30):
    now = as_of or datetime.now(timezone.utc)
    with closing(sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=ro", uri=True)) as db:
        sources = db.execute("SELECT DISTINCT symbol,provider,feed FROM minute_bars WHERE timestamp>=?", ((now-timedelta(days=days)).isoformat(),)).fetchall()
        sessions = {row[0]: pd.Timestamp(row[1]) for row in db.execute("SELECT session_date,closes_at FROM market_sessions")}
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='bollinger_live_events'").fetchone()
        live = [dict(json.loads(row[0]), origin="EN_VIVO") for row in db.execute("SELECT payload_json FROM bollinger_live_events WHERE detected_at>=? AND detected_at<=?", ((now-timedelta(days=days)).isoformat(),now.isoformat()))] if exists else []
    allowed = set(load_watchlist()["symbols"])
    # Legacy ET/UTC rows may describe the same event. Keep the first actual
    # observation, without deleting the original private audit records.
    unique_live = {}
    for event in sorted(live, key=lambda e: pd.Timestamp(e['detected_at'])):
        identity = (event.get('version'), event['symbol'], event['provider'], event['feed'],
                    pd.Timestamp(event['candle']).tz_convert('UTC'), event['side'])
        unique_live.setdefault(identity, event)
    live = list(unique_live.values())
    store = MarketBarStore(database)
    observations, event_count = [], 0
    for symbol, provider, feed in sources:
        if symbol not in allowed:
            continue
        bars = store.load_frame(symbol=symbol, provider=provider, feed=feed, start=now-timedelta(days=days+7), end=now-timedelta(minutes=1))
        if bars.empty:
            continue
        events = [e for e in replay_events(bars, symbol=symbol, provider=provider, feed=feed) if pd.Timestamp(e["detected_at"]) >= pd.Timestamp(now-timedelta(days=days))]
        events += [e for e in live if e.get("version") == STRATEGY_VERSION and (e["symbol"],e["provider"],e["feed"]) == (symbol,provider,feed)]
        indexed = bars.set_index("date")
        event_count += len(events)
        for event in events:
            date = pd.Timestamp(event["source_timestamp"]).tz_convert("America/New_York").date().isoformat()
            source_available=pd.Timestamp(event['source_timestamp'])+(pd.Timedelta(0) if event.get('source_kind')=='TRADE' else pd.Timedelta(minutes=1))
            if sessions.get(date) is not None and source_available > sessions[date]:
                event_count -= 1
                continue
            for horizon in HORIZONS:
                observations.append(evaluate_event(event, indexed, sessions.get(date), as_of=now, horizon=horizon))
    return {"generated_at": now.isoformat(), "days": days, "version": STRATEGY_VERSION, "event_count": event_count,
            "summary": summarize(observations), "observations": observations,
            "definition": "Positivo = precio final del subyacente a favor de la salida respecto al precio observado. No es ganancia del contrato ni incluye costos.",
            "authority": "ESTUDIO_DESCRIPTIVO_NO_AUTORIZA_OPERACIONES"}


def update(database=DEFAULT_MARKET_DATABASE):
    report = build_report(database)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT / "latest.tmp"
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUTPUT / "latest.json")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if not args.watch:
        report = update()
        print(f"Estudio actualizado: {report['event_count']} observaciones detectadas")
    else:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        with ScannerInstanceLease(OUTPUT / "worker.lock"):
            while True:
                try:
                    update()
                except Exception as error:
                    print(f"Informe pendiente: {type(error).__name__}", flush=True)
                for _ in range(60):
                    time.sleep(5)
