"""Contexto objetivo de ETFs de referencia para alertas en vivo."""

from dataclasses import dataclass
from datetime import datetime

from market_store import MarketBarStore
from live_market import aggregate_minute_bars, retain_closed_aggregates


@dataclass(frozen=True)
class BenchmarkSnapshot:
    symbol: str
    data_as_of: str | None
    synchronized: bool
    close: float | None
    change_pct_15m: float | None
    direction: str


def build_market_context(
    store: MarketBarStore,
    benchmarks: tuple[str, ...],
    *,
    provider: str,
    feed: str,
    trigger_timestamp: datetime,
    session_closes: dict | None = None,
) -> dict:
    """Mide acompañamiento sin aprobar ni rechazar el panorama."""
    snapshots = []
    for symbol in benchmarks:
        minutes = store.load_frame(
            symbol=symbol, provider=provider, feed=feed, end=trigger_timestamp
        )
        if minutes.empty:
            snapshots.append(BenchmarkSnapshot(symbol, None, False, None, None, "NO_DISPONIBLE"))
            continue
        bars = retain_closed_aggregates(
            aggregate_minute_bars(minutes, "15m"),
            "15m",
            latest_source_timestamp=minutes.iloc[-1]["date"].to_pydatetime(),
            session_closes=session_closes,
        )
        if bars.empty:
            snapshots.append(BenchmarkSnapshot(symbol, None, False, None, None, "NO_DISPONIBLE"))
            continue
        latest = bars.iloc[-1]
        change = None
        if len(bars) >= 2 and float(bars.iloc[-2]["close"]) != 0:
            change = (float(latest["close"]) / float(bars.iloc[-2]["close"]) - 1) * 100
        direction = "ALCISTA" if change is not None and change > 0 else "BAJISTA" if change is not None and change < 0 else "NEUTRAL"
        source_latest = minutes.iloc[-1]["date"].to_pydatetime()
        snapshots.append(
            BenchmarkSnapshot(
                symbol,
                latest["date"].isoformat(),
                source_latest == trigger_timestamp,
                float(latest["close"]),
                round(change, 4) if change is not None else None,
                direction,
            )
        )
    available = [item for item in snapshots if item.direction != "NO_DISPONIBLE"]
    return {
        "status": "REQUIERE_REVISION",
        "reason": "Contexto descriptivo; no aprueba panorama automáticamente.",
        "synchronized_count": sum(item.synchronized for item in snapshots),
        "bullish_count": sum(item.direction == "ALCISTA" for item in available),
        "bearish_count": sum(item.direction == "BAJISTA" for item in available),
        "benchmarks": [item.__dict__ for item in snapshots],
    }
