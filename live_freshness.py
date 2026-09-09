"""Compuerta auditable de frescura para barras recibidas en tiempo real."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

from analysis_models import GateStatus
from live_market import MarketBar, normalize_minute_bars
from market_store import find_internal_minute_gaps


@dataclass(frozen=True)
class LiveDataFreshness:
    """Evidencia objetiva de si una barra puede considerarse actual."""

    status: GateStatus
    checked_at: datetime
    bar_timestamp: datetime
    age_seconds: float
    feed: str
    latest_persisted_matches: bool
    recent_gap_count: int
    issues: tuple[str, ...]


def evaluate_live_freshness(
    bar: MarketBar,
    persisted_frame: pd.DataFrame,
    *,
    feed: str,
    checked_at: datetime | None = None,
    max_age: timedelta = timedelta(minutes=3),
    gap_window: timedelta = timedelta(minutes=15),
) -> LiveDataFreshness:
    """Rechaza feeds retrasados, barras viejas, abiertas o no persistidas."""
    now = checked_at or datetime.now(timezone.utc)
    if now.tzinfo is None or bar.timestamp.tzinfo is None:
        raise ValueError("Las fechas de frescura deben incluir zona horaria.")
    if max_age.total_seconds() <= 0 or gap_window.total_seconds() <= 0:
        raise ValueError("Las ventanas de frescura deben ser positivas.")
    normalized_feed = feed.strip().lower()
    issues: list[str] = []
    if normalized_feed not in {"iex", "sip", "delayed_sip"}:
        issues.append(f"Feed de acciones no reconocido: {normalized_feed or 'vacío'}.")
    if normalized_feed == "delayed_sip":
        issues.append("El feed delayed_sip tiene retraso y no se considera actual.")
    if not bar.complete:
        issues.append("La barra todavía está abierta.")

    bar_time = bar.timestamp.astimezone(timezone.utc)
    age_seconds = (now.astimezone(timezone.utc) - bar_time).total_seconds()
    if age_seconds < -5:
        issues.append("La barra tiene un timestamp futuro.")
    if age_seconds > max_age.total_seconds():
        issues.append(
            f"La barra excede la antigüedad máxima: {age_seconds:.0f} segundos."
        )

    latest_matches = False
    gap_count = 0
    if persisted_frame.empty:
        issues.append("No existe historial persistido para verificar la barra.")
    else:
        persisted = normalize_minute_bars(persisted_frame)
        latest = persisted.iloc[-1]["date"].to_pydatetime()
        latest_matches = latest == bar_time
        if not latest_matches:
            issues.append("La última barra persistida no coincide con el evento recibido.")
        window_start = bar_time - gap_window
        recent = persisted[persisted["date"] >= window_start]
        if not recent.empty:
            gap_count = len(find_internal_minute_gaps(recent))

    return LiveDataFreshness(
        status=GateStatus.RECHAZADO if issues else GateStatus.APROBADO,
        checked_at=now.astimezone(timezone.utc),
        bar_timestamp=bar_time,
        age_seconds=round(age_seconds, 3),
        feed=normalized_feed,
        latest_persisted_matches=latest_matches,
        recent_gap_count=gap_count,
        issues=tuple(issues),
    )
