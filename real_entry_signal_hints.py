"""One bounded read to skip idle companies; never an entry authorization."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import time


def entry_signal_symbols(database,symbols):
    symbols=tuple(dict.fromkeys(symbols))
    if not symbols:return frozenset()
    if len(symbols)>100:return None
    started=time.monotonic()
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',
                                     uri=True,timeout=.05)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda:time.monotonic()-started>.05,100)
            rows=db.execute('SELECT symbol,payload_json FROM bollinger_tick_latest WHERE symbol IN ('+
                ','.join('?' for _ in symbols)+')',symbols).fetchall()
        found={}
        for symbol,payload in rows:
            tick=json.loads(payload)
            if not isinstance(tick,dict):return None
            found[symbol]=tick.get('reason')=='EXIT' and bool(tick.get('signal'))
        # Missing rows and any error retain the full authoritative lookup.
        # A positive hint never substitutes geometry, freshness or dedup checks.
        return frozenset(symbol for symbol in symbols if found.get(symbol,True))
    except (sqlite3.Error,OSError,ValueError,TypeError):return None
