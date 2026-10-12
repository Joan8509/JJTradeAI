"""Auditoría de minutos sin barra y recuperación del mismo proveedor/feed."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import pandas as pd

from live_market import NoMarketDataError, normalize_minute_bars


def minute_ranges(missing):
    ranges = []
    for stamp in sorted(set(missing)):
        if ranges and stamp == ranges[-1][1] + timedelta(minutes=1):
            ranges[-1][1] = stamp
        else:
            ranges.append([stamp, stamp])
    return [{"start": start.isoformat(), "end": end.isoformat(),
             "minutes": int((end - start).total_seconds() / 60) + 1} for start, end in ranges]


def audit_session(*, symbol, provider, feed, session_date, opens_at, closes_at, timestamps, as_of):
    if any(stamp.tzinfo is None for stamp in (opens_at, closes_at, as_of)):
        raise ValueError("El calendario debe incluir zona horaria.")
    opens_at, closes_at, as_of = (stamp.astimezone(timezone.utc) for stamp in (opens_at, closes_at, as_of))
    if closes_at <= opens_at:
        raise ValueError("Sesión inválida.")
    end = min(closes_at, as_of.replace(second=0, microsecond=0))
    expected = {opens_at + timedelta(minutes=minute) for minute in range(max(0, int((end - opens_at).total_seconds() / 60)))}
    actual = {stamp.astimezone(timezone.utc) for stamp in timestamps} & expected
    missing = expected - actual
    return {"symbol": symbol, "provider": provider, "feed": feed, "session_date": session_date,
            "opens_at": opens_at.isoformat(), "closes_at": closes_at.isoformat(), "audited_end": end.isoformat(),
            "expected_minutes": len(expected), "observed_minutes": len(actual), "missing_minutes": len(missing),
            "coverage_pct": round(len(actual) / len(expected) * 100, 2) if expected else None,
            "status": "SIN_MINUTOS_CERRADOS" if not expected else "SIN_COBERTURA_LOCAL" if not actual else "MINUTOS_SIN_BARRA" if missing else "COMPLETA",
            "ranges": minute_ranges(missing), "cause": "NO_DETERMINADA" if missing else None}


def build_gap_audit(connection, *, as_of, sessions=20):
    calendar = connection.execute(
        "SELECT session_date,opens_at,closes_at FROM market_sessions WHERE julianday(opens_at)<julianday(?) "
        "ORDER BY session_date DESC LIMIT ?", (as_of.isoformat(), sessions),
    ).fetchall()
    health = connection.execute("SELECT provider,feed,symbols_json FROM live_service_health WHERE service_id='live_strategy_scanner'").fetchone()
    identities = [(health["provider"], health["feed"], symbol) for symbol in json.loads(health["symbols_json"])] if health else [tuple(row) for row in connection.execute("SELECT DISTINCT provider,feed,symbol FROM minute_bars")]
    rows = []
    for provider, feed, symbol in identities:
        for session in calendar:
            opens_at = datetime.fromisoformat(session["opens_at"])
            closes_at = datetime.fromisoformat(session["closes_at"])
            timestamps = [datetime.fromisoformat(row[0]) for row in connection.execute(
                "SELECT timestamp FROM minute_bars WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? AND timestamp<?",
                (provider, feed, symbol, opens_at.astimezone(timezone.utc).isoformat(), closes_at.astimezone(timezone.utc).isoformat()),
            )]
            rows.append(audit_session(symbol=symbol, provider=provider, feed=feed, session_date=session["session_date"],
                                      opens_at=opens_at, closes_at=closes_at, timestamps=timestamps, as_of=as_of))
    return {"as_of": as_of.astimezone(timezone.utc).isoformat(), "session_limit": sessions,
            "calendar_status": "DISPONIBLE" if calendar else "SIN_CALENDARIO", "rows": rows,
            "missing_minutes": sum(row["missing_minutes"] for row in rows),
            "interpretation": "Minutos sin barra local, no pérdidas confirmadas. El proveedor puede no generar barra si no hay operaciones elegibles."}


def recover_session_gaps(store, provider, *, audit, provider_name, feed):
    if audit["provider"] != provider_name or audit["feed"] != feed:
        raise ValueError("La recuperación debe usar el mismo proveedor y feed.")
    if getattr(getattr(provider, "config", None), "feed", feed) != feed:
        raise ValueError("El adaptador está configurado para otro feed.")
    start = datetime.fromisoformat(audit["opens_at"])
    end = datetime.fromisoformat(audit["audited_end"])
    if end <= start or audit["missing_minutes"] == 0:
        return {"status": "SIN_RECUPERACION_NECESARIA", "inserted": 0, "remaining": audit["missing_minutes"]}
    try:
        frame = provider.fetch_minute_bars(audit["symbol"], start=start, end=end - timedelta(minutes=1))
    except NoMarketDataError:
        frame = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    inserted = 0
    if not frame.empty:
        frame = normalize_minute_bars(frame)
        frame = frame[(frame["date"] >= start) & (frame["date"] < end)]
        if not frame.empty:
            inserted = store.upsert_frame(frame, symbol=audit["symbol"], provider=provider_name, feed=feed, only_missing=True)
    current = store.load_frame(symbol=audit["symbol"], provider=provider_name, feed=feed, start=start, end=end - timedelta(minutes=1))
    after = audit_session(symbol=audit["symbol"], provider=provider_name, feed=feed, session_date=audit["session_date"],
                          opens_at=start, closes_at=datetime.fromisoformat(audit["closes_at"]),
                          timestamps=[stamp.to_pydatetime() for stamp in current["date"]], as_of=end)
    return {"status": "RECUPERADA" if after["missing_minutes"] == 0 else "CONSULTADA_CON_MINUTOS_SIN_BARRA",
            "inserted": inserted, "remaining": after["missing_minutes"], "cause": "NO_DETERMINADA" if after["missing_minutes"] else None}
