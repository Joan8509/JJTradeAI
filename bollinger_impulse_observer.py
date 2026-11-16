"""Offline evidence only. Reads collector SQLite; never connects to a broker/feed.

The source cursor and captured rows commit together in a separate SQLite file.
No strategy input, alert, order, account, or production setting is written.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

UTC = timezone.utc


def stamp():
    return datetime.now(UTC).isoformat()


def open_source(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=.05)
    db.execute('PRAGMA query_only=ON')
    deadline = time.monotonic() + .20
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return db


def open_archive(path):
    db = sqlite3.connect(path, timeout=1)
    db.executescript('''
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS ticks(id INTEGER PRIMARY KEY, received TEXT,
        symbol TEXT, source_time TEXT, reason TEXT, message TEXT);
      CREATE INDEX IF NOT EXISTS ticks_symbol_time ON ticks(symbol,source_time);
      CREATE TABLE IF NOT EXISTS events(event_key TEXT PRIMARY KEY,detected_at TEXT,payload TEXT);
      CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS gaps(recorded_at TEXT,after_id INTEGER,before_id INTEGER);
    ''')
    return db


def capture(source, archive, batch=1000, capture_events=True):
    previous = archive.execute("SELECT value FROM state WHERE key='cursor'").fetchone()
    cursor = int(previous[0]) if previous else 0
    with closing(open_source(source)) as src:
        rows = src.execute('SELECT id,received_at,symbol,source_timestamp,reason,message_json '
                           'FROM bollinger_tick_audit WHERE id>? ORDER BY id LIMIT ?',
                           (cursor, batch)).fetchall()
        events = src.execute('SELECT event_key,detected_at,payload_json FROM bollinger_live_events').fetchall() if capture_events else []
    kept = []
    for row in rows:
        try:
            msg = json.loads(row[5])
            # Preserve every computed geometry, including neutral/reentry trades.
            # Excluded prints have no geometry and cannot establish price velocity.
            if isinstance(msg.get('_jjtrade', {}).get('geometry'), dict):
                kept.append(row)
        except (ValueError, TypeError):
            # Raw malformed evidence stays identifiable, never becomes eligible.
            kept.append(row)
    gap = bool(previous and rows and rows[0][0] > cursor + 1)
    with archive:
        if gap:
            archive.execute('INSERT INTO gaps VALUES (?,?,?)', (stamp(),cursor,rows[0][0]))
        archive.executemany('INSERT OR IGNORE INTO ticks VALUES (?,?,?,?,?,?)', kept)
        archive.executemany('INSERT OR IGNORE INTO events VALUES (?,?,?)', events)
        if rows:
            archive.execute("INSERT OR REPLACE INTO state VALUES ('cursor',?)", (str(rows[-1][0]),))
        if previous is None and rows:
            archive.execute("INSERT OR IGNORE INTO state VALUES ('initial_retained_id',?)", (str(rows[0][0]),))
        archive.execute("INSERT OR REPLACE INTO state VALUES ('heartbeat',?)", (stamp(),))
    return {'scanned': len(rows), 'preserved': len(kept), 'cursor': rows[-1][0] if rows else cursor,
            'retention_gap': gap, 'last_source_received': rows[-1][1] if rows else None}


def trailing_velocity(ticks, decision_received, source_time, seconds, direction, width):
    """Only prices known by decision time. None when a trailing anchor is absent."""
    available = sorted((t for t in ticks if t['received'] <= decision_received
                        and t['time'] <= source_time), key=lambda t: t['time'])
    if not available or width <= 0:
        return None
    cutoff = source_time - seconds
    anchors = [t for t in available if cutoff - 1 <= t['time'] <= cutoff]
    if not anchors or source_time - available[-1]['time'] > 1:
        return None
    anchor = anchors[-1]
    end = available[-1]
    if end['time'] <= anchor['time']:
        return None
    return direction * (end['price'] - anchor['price']) / width


def inventory_report(archive):
    versions, cohorts, days = Counter(), Counter(), Counter()
    for key, detected, raw in archive.execute('SELECT * FROM events'):
        event = json.loads(raw)
        version = event.get('version', 'missing')
        versions[version] += 1
        if version == 'v5_apertura_dentro_bandas_actuales':
            expansion = event.get('band_expansion', {})
            cohorts[str(expansion.get('required_pct', 'missing')) + '|' +
                    str(event.get('feed')) + '|' + str(event.get('reference_scope'))] += 1
            days[detected[:10]] += 1
    count, first, last = archive.execute('SELECT count(*),min(source_time),max(source_time) FROM ticks').fetchone()
    return {'created_at': stamp(), 'mode': 'OBSERVATION_ONLY',
            'events_by_version': dict(versions), 'current_version_cohorts': dict(cohorts),
            'current_version_days': dict(days), 'geometry_ticks': count,
            'tick_source_range': [first,last],
            'retention_gaps': archive.execute('SELECT count(*) FROM gaps').fetchone()[0],
            'conclusion': 'No new filter selected. Opening second-level evidence must be collected prospectively.',
            'limitations': ['Underlying price is not option P&L.',
                           'Minute OHLC cannot establish a 1-second entry or exit.',
                           'IEX observations do not establish Nasdaq Basic parity.',
                           'Initial retained audit boundary is not complete historical coverage.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='exports/market_data.db')
    parser.add_argument('--output', default='exports/trade_review/2026-11-06_impulse_study')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    # Windows singleton, released automatically even on a crash.
    lock = open(folder / 'observer.lock', 'a+b')
    if os.name == 'nt':
        import msvcrt
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
    archive = open_archive(folder / 'impulse_evidence.sqlite3')
    last_events = 0
    total = 0
    last_received = None
    failures = 0
    last_error = None
    while True:
        health = {'at': stamp(), 'pid': os.getpid(), 'mode': 'OBSERVATION_ONLY'}
        try:
            if shutil.disk_usage(folder).free < 2 * 1024**3:
                raise RuntimeError('Recording paused: less than 2 GiB free')
            if (folder / 'impulse_evidence.sqlite3').stat().st_size > 2 * 1024**3:
                raise RuntimeError('Recording paused: archive reached 2 GiB; review retention')
            now = time.monotonic()
            result = capture(args.source, archive, capture_events=now-last_events >= 30)
            if now-last_events >= 30:
                last_events = now
                (folder / 'initial_report.json').write_text(json.dumps(inventory_report(archive),indent=2),encoding='utf-8')
            total += result['preserved']
            last_received = result['last_source_received'] or last_received
            health.update(result, status='RUNNING', preserved_this_process=total,
                          last_source_received=last_received)
        except Exception as exc:
            failures += 1
            last_error = {'at':stamp(),'error':type(exc).__name__ + ': ' + str(exc)}
            health.update(status='ERROR', error=last_error['error'])
        health.update(read_failures_this_process=failures,last_error=last_error)
        temp = folder / 'observer_health.tmp'
        # A diagnostic reader/antivirus may briefly hold a Windows file open.
        # Health publishing must never kill evidence collection.
        try:
            temp.write_text(json.dumps(health,indent=2),encoding='utf-8')
            for attempt in range(4):
                try:
                    temp.replace(folder / 'observer_health.json')
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(.02)
        except OSError:
            pass
        if args.once:
            break
        time.sleep(.05 if health.get('scanned') == 1000 else .5)


if __name__ == '__main__':
    main()
