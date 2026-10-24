"""Read-only, bounded dashboard snapshot; never starts services or sends notices."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import time


def read_snapshot(database, session_date):
    started = time.monotonic()
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',
                                uri=True, timeout=2)) as db:
        db.set_progress_handler(lambda: time.monotonic()-started > 2, 1000)
        db.execute('BEGIN')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        session = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',
                             (session_date.isoformat(),)).fetchone() if 'market_sessions' in tables else None
        states = db.execute('SELECT payload_json FROM bollinger_radar_state').fetchall() if 'bollinger_radar_state' in tables else []
        events = db.execute('SELECT payload_json FROM bollinger_live_events ORDER BY detected_at DESC LIMIT 50').fetchall() if 'bollinger_live_events' in tables else []
    # Decode after releasing the read transaction, including large contexts.
    return {'session': session, 'states': [json.loads(row[0]) for row in states],
            'events': [json.loads(row[0]) for row in events]}
