"""Bounded read-only market queries; separate observational SQLite archive."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import hashlib
import sqlite3
import statistics
import time

from movement_strength import REVISION, evaluate, stamp, number

DEFAULT_ARCHIVE = Path(__file__).resolve().parent/'exports/movement_strength.sqlite3'


def identity(event):
    fields = ('symbol', 'source_timestamp', 'price', 'feed', 'side', 'version')
    return hashlib.sha256(json.dumps([event.get(k) for k in fields], separators=(',', ':')).encode()).hexdigest()


def read_source(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=.05)
    db.execute('PRAGMA query_only=ON')
    deadline = time.monotonic()+.20
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 100)
    return db


def evidence(path, event):
    """No backfilled future prices, provider calls, or writes to market DB."""
    source, decision = stamp(event['source_timestamp']), stamp(event['detected_at'])
    ticks = []
    with closing(read_source(path)) as db:
        # This audit has a received_at index; bound ALL symbols before filtering.
        rows = db.execute('SELECT symbol,received_at,source_timestamp,message_json FROM bollinger_tick_audit '
            'WHERE received_at>=? AND received_at<=? ORDER BY received_at DESC LIMIT 10001',
            ((source-timedelta(seconds=12)).astimezone(timezone.utc).isoformat(),
             decision.astimezone(timezone.utc).isoformat())).fetchall()
        if len(rows) == 10001:
            raise ValueError('AUDIT_WINDOW_TRUNCATED')
        for symbol, received, source_time, raw in rows:
            if symbol != event['symbol']:
                continue
            try:
                msg = json.loads(raw)
                extra = msg.get('_jjtrade', {})
                # Only accepted trade geometry in the collector's exact feed.
                # Non-trades, corrections and excluded prints have no geometry.
                if msg.get('T') != 't' or not isinstance(extra.get('geometry'), dict):
                    continue
                g = extra['geometry']
                ticks.append(dict(time=source_time, received=received,
                                  processed=extra['processed_at'], price=msg.get('p'),
                                  **{k:g.get(k) for k in ('upper','lower','previous_upper','previous_lower')}))
            except (ValueError, KeyError, TypeError):
                continue
        runtime = db.execute('SELECT feed FROM bollinger_tick_runtime WHERE id=1').fetchone()
        # Audit does not store feed per row: only trust the currently configured
        # stream for today's events. Historical feed changes cannot be inferred.
        if not runtime or runtime[0] != event.get('feed'):
            ticks = []
        minute = source.replace(second=0, microsecond=0)-timedelta(minutes=1)
        local = minute.astimezone(ZoneInfo('America/New_York'))
        volume = None
        # At the opening do not substitute yesterday or premarket for RTH.
        if (local.hour, local.minute) >= (9, 30) and (local.hour, local.minute) < (16, 0):
            candidates = [(local-timedelta(days=d)).astimezone(timezone.utc).isoformat() for d in range(41)]
            bars = db.execute('SELECT timestamp,volume,received_at FROM minute_bars '
                'WHERE provider=? AND feed=? AND symbol=? AND timestamp IN ('+
                ','.join('?' for _ in candidates)+')',
                (event['provider'], event['feed'], event['symbol'], *candidates)).fetchall()
            usable = []
            for at, size, received in bars:
                amount = number(size)
                if amount is not None and amount >= 0 and stamp(received) <= decision:
                    usable.append((stamp(at), amount, received))
            current = next((b for b in usable if b[0] == minute), None)
            previous = sorted((b for b in usable if b[0] < minute), reverse=True)[:20]
            median = statistics.median(b[1] for b in previous) if previous else 0
            if current and median > 0:
                volume = dict(ratio=current[1]/median, sessions=len(previous),
                    closed_at=(minute+timedelta(minutes=1)).isoformat(), known_at=current[2],
                    minute_start=minute.isoformat(), volume=current[1], median=median,
                    feed=event['feed'], scope='PREVIOUS_CLOSED_MINUTE_SAME_ET_TIME')
    return ticks, volume


def observe(path, event):
    try:
        ticks, volume = evidence(path, event)
        value = evaluate(event, ticks, volume)
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
        value = evaluate(event)
        value['evidence_status'] = 'READ_UNAVAILABLE_OR_INCOMPLETE'
    # Preserve context separately: a forward SMA is not automatically resistance.
    from ma_price_outlook import outlook
    context = event.get('ma_context')
    if isinstance(context, dict):
        try:
            if stamp(context['available_at']) <= stamp(event['source_timestamp']) and context.get('price') == event.get('price'):
                route = outlook(context, event.get('side'))
                value['ma_route'] = dict(nearest_limit=route.get('nearest_limit'),
                                        complete=route.get('complete'), reading=route.get('reading'))
        except (KeyError, ValueError, TypeError):
            pass
    return value


def archive_readings(events, *, archive=DEFAULT_ARCHIVE):
    """No creation as a side effect of displaying UI."""
    result = {}
    try:
        with closing(read_source(archive)) as db:
            for event in events:
                row = db.execute('SELECT payload FROM strength WHERE event_key=? AND revision=?',
                                 (identity(event), REVISION)).fetchone()
                if row:
                    result[identity(event)] = json.loads(row[0])
    except (sqlite3.Error, OSError, ValueError):
        pass
    return result


def capture(source, archive=DEFAULT_ARCHIVE, *, now=None):
    """Sample recent original signals. Isolated observer owns this archive."""
    from bollinger_phone_worker import STRATEGY_VERSION
    clock = now or datetime.now(timezone.utc)
    start = clock.astimezone(ZoneInfo('America/New_York')).replace(hour=0, minute=0, second=0, microsecond=0)
    with closing(read_source(source)) as db:
        rows = db.execute('SELECT event_key,detected_at,payload_json FROM bollinger_live_events '
            'WHERE detected_at>=? AND detected_at<=? ORDER BY detected_at DESC LIMIT 200',
            (start.astimezone(timezone.utc).isoformat(), clock.astimezone(timezone.utc).isoformat())).fetchall()
    Path(archive).parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with closing(sqlite3.connect(archive, timeout=.1)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS strength(event_key TEXT,revision TEXT,observed_at TEXT,'
                   'event_json TEXT,payload TEXT,evidence_json TEXT,PRIMARY KEY(event_key,revision))')
        db.execute('CREATE TABLE IF NOT EXISTS observer_status(id INTEGER PRIMARY KEY,heartbeat TEXT,events INTEGER)')
        for key, detected, raw in rows:
            event = json.loads(raw)
            if event.get('version') != STRATEGY_VERSION or event.get('source_kind') != 'TRADE':
                continue
            if stamp(event['source_timestamp']).astimezone(ZoneInfo('America/New_York')).date() != start.date():
                continue
            # Wait for asynchronous audit publication, never make trading wait.
            if clock-stamp(detected) < timedelta(seconds=2):
                continue
            archive_key = identity(event)
            existing = db.execute('SELECT observed_at FROM strength WHERE event_key=? AND revision=?', (archive_key, REVISION)).fetchone()
            if existing and (clock-stamp(existing[0]) < timedelta(seconds=30) or
                             clock-stamp(detected) > timedelta(minutes=2)):
                continue
            event = {**event, 'event_key': key, 'detected_at': detected}
            # Save the actual inputs to reproduce scores after audit retention.
            try:
                ticks, volume = evidence(source, event)
                value = evaluate(event, ticks, volume)
                inputs = dict(ticks=ticks, volume=volume)
            except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
                value = evaluate(event)
                value['evidence_status'] = 'READ_UNAVAILABLE_OR_INCOMPLETE'
                inputs = None
            db.execute('INSERT OR REPLACE INTO strength VALUES(?,?,?,?,?,?)',
                (archive_key, REVISION, clock.isoformat(), json.dumps(event), json.dumps(value), json.dumps(inputs)))
            count += 1
        db.execute('INSERT OR REPLACE INTO observer_status VALUES(1,?,?)', (clock.isoformat(), count))
        db.commit()
    return count
