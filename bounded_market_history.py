"""Paged archive reads for descriptive context; release SQLite between pages."""
from contextlib import closing
from pathlib import Path
import sqlite3
import time

import pandas as pd


def load_history(database, *, symbol, provider, feed, start, end,
                 received_by=None, page_size=1000, after_page=None):
    if not isinstance(page_size, int) or not 1 <= page_size <= 1000:
        raise ValueError('History page must contain 1-1000 rows')
    uri = Path(database).resolve().as_uri()+'?mode=ro'
    records, last = [], None
    while True:
        started = time.monotonic()
        clauses = ['provider=?', 'feed=?', 'symbol=?']
        params = [provider, feed, symbol]
        for value, operator in ((start, '>='), (end, '<=')):
            if value is not None:
                clauses.append('timestamp'+operator+'?')
                params.append(pd.Timestamp(value).isoformat())
        if last is not None:
            clauses.append('timestamp>?')
            params.append(last)
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.set_progress_handler(lambda: time.monotonic()-started > 2, 1000)
            columns = 'timestamp,open,high,low,close,volume'
            if received_by is not None:
                columns += ',received_at'
            rows = db.execute('SELECT '+columns+' FROM minute_bars WHERE '+
                              ' AND '.join(clauses)+' ORDER BY timestamp LIMIT ?',
                              (*params, page_size)).fetchall()
        # No transaction survives the page; transformations and caller hooks
        # must run after closing the reader so live ingestion can commit.
        if not rows:
            break
        last = rows[-1][0]
        records.extend(row[:6] for row in rows if received_by is None or
                       row[6] is not None and row[6] <= pd.Timestamp(received_by).isoformat())
        if after_page is not None:
            after_page()
        if len(rows) < page_size:
            break
        time.sleep(.005)
    return pd.DataFrame(records, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
