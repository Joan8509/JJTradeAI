"""Bounded read-only explanation of market geometry. Never authorizes trading.

Used only by the dashboard on explicit refresh. No broker/config/queue writes,
background worker, historical scan or network call belongs in this module.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import re
import sqlite3
import time

from bollinger_expansion import MINIMUM_BAND_EXPANSION_PCT, measure_band_expansion
from bollinger_phone_worker import STRATEGY_VERSION, detect_values

MAX_SYMBOLS = 30
MAX_READ_SECONDS = .25


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return stamp.astimezone(timezone.utc)


def read_snapshot(database, symbols, now):
    """One small SQLite snapshot. The source must exist; never initializes it."""
    if now.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    symbols = list(dict.fromkeys(symbols))
    if not symbols or len(symbols) > MAX_SYMBOLS or any(
            not isinstance(s, str) or not re.fullmatch(r'[A-Z0-9.]{1,12}', s) for s in symbols):
        raise ValueError('INVALID_SYMBOLS')
    from zoneinfo import ZoneInfo
    day = now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    begun = time.monotonic()
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',
                                    uri=True, timeout=.1)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: time.monotonic()-begun > MAX_READ_SECONDS, 100)
            db.execute('BEGIN')
            runtime = db.execute('SELECT state,heartbeat,feed FROM bollinger_tick_runtime WHERE id=1').fetchone()
            session = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?', (day,)).fetchone()
            payloads = db.execute('SELECT symbol,payload_json FROM bollinger_tick_latest WHERE symbol IN ('+
                                  ','.join('?' for _ in symbols)+')', symbols).fetchall()
        ticks = {}
        for symbol, payload in payloads:
            if len(payload) > 65536:
                continue
            try:
                tick = json.loads(payload)
                if isinstance(tick, dict) and tick.get('symbol') == symbol:
                    ticks[symbol] = tick
            except (TypeError, ValueError):
                pass
        return dict(available=True, captured_at=now.isoformat(), runtime=dict(
            state=runtime[0], heartbeat=runtime[1], feed=runtime[2]) if runtime else None,
            session=session, ticks=ticks, symbols=symbols)
    except (sqlite3.Error, OSError, ValueError):
        return dict(available=False, captured_at=now.isoformat(), symbols=symbols,
                    ticks={}, runtime=None, session=None)


def describe(snapshot, symbol, now):
    """Explain each condition, keeping geometry separate from freshness/session."""
    row = dict(symbol=symbol, status='UNAVAILABLE', geometry_side=None, missing=[],
               source_at=None, age_seconds=None, upper_pct=None, lower_pct=None,
               required_pct=MINIMUM_BAND_EXPANSION_PCT, checks={},
               opening=None, price=None, upper=None, lower=None, feed=None,
               authority='DIAGNOSTIC_ONLY')
    try:
        if now.tzinfo is None:
            raise ValueError('TIMEZONE_REQUIRED')
        tick = snapshot.get('ticks', {}).get(symbol)
        if not snapshot.get('available') or not tick:
            return row
        if tick.get('symbol') != symbol:
            return row
        row['source_at'] = tick.get('source_timestamp')
        age = (now-_stamp(row['source_at'])).total_seconds()
        row['age_seconds'] = age
        row['feed'] = tick.get('feed')
        g = tick.get('geometry') or {}
        names = ('upper', 'lower', 'previous_upper', 'previous_lower', 'mid', 'previous_mid', 'opening', 'price')
        values = {k: float(g[k]) for k in names}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError('INVALID_GEOMETRY')
        expansion = measure_band_expansion(*(values[k] for k in
            ('upper', 'lower', 'previous_upper', 'previous_lower')))
        row.update({k: values[k] for k in ('opening', 'price', 'upper', 'lower')})
        row.update(upper_pct=expansion.upper_pct, lower_pct=expansion.lower_pct)
        opening_inside = values['lower'] <= values['opening'] <= values['upper']
        up = values['price'] > values['upper'] and values['price'] > values['opening']
        down = values['price'] < values['lower'] and values['price'] < values['opening']
        direction = up or down
        midpoint = (up and values['mid'] > values['previous_mid']) or (down and values['mid'] < values['previous_mid'])
        row['checks'] = dict(opening_inside=opening_inside,
            upper_expansion=expansion.upper_pct >= MINIMUM_BAND_EXPANSION_PCT,
            lower_expansion=expansion.lower_pct >= MINIMUM_BAND_EXPANSION_PCT,
            directional_exit=direction, midpoint=midpoint)
        row['missing'] = [k for k, passed in row['checks'].items() if not passed]
        # Reuse the strategy's actual arithmetic instead of making a new gate.
        row['geometry_side'] = detect_values(values['opening'], values['previous_upper'],
            values['previous_lower'], values['previous_mid'], values['price'], values['upper'],
            values['lower'], values['mid'], opening=values['opening'])
        runtime = snapshot.get('runtime') or {}
        session = snapshot.get('session')
        if tick.get('version') != STRATEGY_VERSION:
            row['status'] = 'VERSION_MISMATCH'
        elif runtime.get('feed') != tick.get('feed'):
            row['status'] = 'FEED_MISMATCH'
        elif not session or not _stamp(session[0]) <= now < _stamp(session[1]):
            row['status'] = 'OUTSIDE_SESSION'
        elif runtime.get('state') != 'CONECTADO' or not 0 <= (now-_stamp(runtime['heartbeat'])).total_seconds() <= 3:
            row['status'] = 'COLLECTOR_NOT_CURRENT'
        elif not 0 <= age <= 3:
            row['status'] = 'TRADE_NOT_CURRENT'
        elif tick.get('reason') != 'EXIT':
            row['status'] = 'DETECTOR_NOT_EXIT' if row['geometry_side'] else 'NO_MATCH'
        elif not row['geometry_side'] or (tick.get('signal') or {}).get('side') != row['geometry_side']:
            row['status'] = 'DETECTOR_MISMATCH'
        else:
            row['status'] = 'GEOMETRY_MATCH'
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        row['status'] = 'INVALID_OR_INCOMPLETE'
    return row
