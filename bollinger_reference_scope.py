"""Reference sessions only; signal math and regular trading hours stay unchanged.

Extended scope is staged separately from the active policy. Missing periods
never fall back to regular references. Half-day extended hours require explicit
verification before this scope can be used for those reference periods.
"""
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
REGULAR = 'REGULAR'
EXTENDED = 'EXTENDED_0400_2000_ET'
POLICY_PATH = Path(__file__).resolve().parent/'config/bollinger_reference_policy.json'


def active_reference_scope():
    if not POLICY_PATH.exists():
        return REGULAR
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    scope = policy['active_scope']
    if scope not in (REGULAR, EXTENDED):
        raise ValueError('UNKNOWN_REFERENCE_SCOPE')
    if scope == EXTENDED and policy.get('activation_state') != 'VERIFIED':
        raise ValueError('EXTENDED_REFERENCE_NOT_VERIFIED')
    return scope


def session_bounds(rows):
    return [(datetime.fromisoformat(a).astimezone(UTC),
             datetime.fromisoformat(b).astimezone(UTC)) for a, b in rows]


def regular_session(rows, stamp):
    return next(((a, b) for a, b in session_bounds(rows) if a <= stamp < b), None)


def required_periods(rows, anchor, *, count=20, scope=REGULAR):
    """Exact chronological periods on official dates, returned in UTC.

    No weekend/holiday/synthetic/older replacement periods are generated. A
    half-day only makes extended scope unavailable when it actually contributes
    to the requested reference window. Regular early closes remain supported.
    """
    if scope not in (REGULAR, EXTENDED):
        raise ValueError('UNKNOWN_REFERENCE_SCOPE')
    if anchor.tzinfo is None or not 1 <= count <= 20:
        raise ValueError('INVALID_REFERENCE_REQUEST')
    periods = []
    for opened, closed in sorted(session_bounds(rows)):
        if scope == EXTENDED:
            day = opened.astimezone(NY).date()
            start = datetime.combine(day, time(4), NY).astimezone(UTC)
            end = datetime.combine(day, time(20), NY).astimezone(UTC)
            verified = (opened.astimezone(NY).time() == time(9, 30)
                        and closed.astimezone(NY).time() == time(16))
        else:
            start, end, verified = opened, closed, True
        while start < min(end, anchor):
            stop = min(start+timedelta(minutes=15), end)
            if stop <= anchor:
                periods.append((start, stop, verified))
            start += timedelta(minutes=15)
    if len(periods) < count:
        return []
    selected = periods[-count:]
    if not all(verified for _, _, verified in selected):
        return []
    return [(a, b) for a, b, _ in selected]
