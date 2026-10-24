"""Readonly operational evidence; never changes prices, clocks or signals."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3


def _stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp sin zona horaria')
    return result.astimezone(timezone.utc)


def fast_feed_health(database, *, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now requiere zona horaria')
    result = {'state': 'SIN_EVIDENCIA', 'sample_count': 0, 'reasons': {},
              'future_count': 0, 'max_future_ms': 0, 'window_seconds': 60}
    with closing(sqlite3.connect(f'file:{Path(database).resolve().as_posix()}?mode=ro', uri=True, timeout=2)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'bollinger_tick_runtime' not in tables:
            return result
        runtime = db.execute('SELECT state,heartbeat FROM bollinger_tick_runtime WHERE id=1').fetchone()
        if not runtime or runtime[0] != 'CONECTADO':
            result['state'] = 'DESCONECTADO'
            return result
        try:
            age = (now-_stamp(runtime[1])).total_seconds()
        except (ValueError, TypeError):
            result['state'] = 'HEARTBEAT_INVALIDO'
            return result
        if age < 0:
            result['state'] = 'HEARTBEAT_FUTURO'
            return result
        if age > 3:
            result['state'] = 'HEARTBEAT_ATRASADO'
            return result
        if 'bollinger_tick_audit' not in tables:
            return result
        rows = db.execute('SELECT received_at,source_timestamp,reason FROM bollinger_tick_audit '
                          'WHERE received_at >= ? ORDER BY received_at DESC LIMIT 1000',
                          ((now-timedelta(seconds=60)).isoformat(),)).fetchall()
    counts = Counter()
    future_ms = []
    for received, source, reason in rows:
        try:
            received = _stamp(received)
            # Ignore far-future audit records after a clock correction.
            if not -3 <= (now-received).total_seconds() <= 60:
                continue
            counts[reason] += 1
            if source and reason in {'DISCONNECTED_OR_STALE', 'STALE_AT_RECEIPT', 'READY_NO_EXIT', 'EXIT'}:
                ahead = (_stamp(source)-received).total_seconds()*1000
                if ahead > 0:
                    future_ms.append(ahead)
        except (ValueError, TypeError):
            counts['TIMESTAMP_INVALIDO'] += 1
    result.update(sample_count=sum(counts.values()), reasons=dict(counts),
                  future_count=len(future_ms), max_future_ms=round(max(future_ms, default=0), 2))
    if len(future_ms) >= 5:
        result['state'] = 'REVISAR_RELOJ'
    elif counts['DISCONNECTED_OR_STALE'] + counts['STALE_AT_RECEIPT']:
        result['state'] = 'RECHAZOS_DE_FRESCURA'
    elif counts['EXIT'] + counts['READY_NO_EXIT']:
        result['state'] = 'DATOS_APTOS_OBSERVADOS'
    return result
