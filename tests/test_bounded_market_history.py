from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from bounded_market_history import load_history
from tests.test_bollinger_tick_stream import seed, CANDLE


class BoundedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'isolated.db'
        seed(self.database)
        self.start, self.end = CANDLE-timedelta(days=2), CANDLE

    def load(self, **kwargs):
        return load_history(self.database, symbol='AAPL', provider='ALPACA', feed='iex',
                            start=self.start, end=self.end, page_size=19, **kwargs)

    def test_paging_matches_original_query_and_releases_lock_for_live_writer(self):
        with closing(sqlite3.connect(self.database)) as db:
            expected = pd.read_sql_query('SELECT timestamp AS date,open,high,low,close,volume '
                'FROM minute_bars WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? '
                'AND timestamp<=? ORDER BY timestamp', db,
                params=('ALPACA', 'iex', 'AAPL', self.start.isoformat(), self.end.isoformat()))
        commits = []
        def writer():
            with closing(sqlite3.connect(self.database, timeout=.01)) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS writer_progress(id INTEGER)')
                db.execute('INSERT INTO writer_progress VALUES(1)')
            commits.append(True)
        actual = self.load(after_page=writer)
        pd.testing.assert_frame_equal(expected, actual)
        self.assertGreater(len(commits), 1)

    def test_receipt_filter_preserves_availability_across_empty_pages(self):
        available = CANDLE.isoformat()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE minute_bars SET received_at=?', ((CANDLE+timedelta(days=1)).isoformat(),))
            db.execute('UPDATE minute_bars SET received_at=? WHERE timestamp>=?',
                       (available, (CANDLE-timedelta(minutes=30)).isoformat()))
            expected = pd.read_sql_query('SELECT timestamp AS date,open,high,low,close,volume '
                'FROM minute_bars WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? '
                'AND timestamp<=? AND received_at<=? ORDER BY timestamp', db,
                params=('ALPACA','iex','AAPL',self.start.isoformat(),self.end.isoformat(),available))
        actual = self.load(received_by=CANDLE)
        pd.testing.assert_frame_equal(expected, actual)

    def test_full_range_without_time_bounds_still_uses_paged_reads(self):
        with closing(sqlite3.connect(self.database)) as db:
            expected = pd.read_sql_query('SELECT timestamp AS date,open,high,low,close,volume '
                'FROM minute_bars WHERE provider=? AND feed=? AND symbol=? ORDER BY timestamp',
                db, params=('ALPACA','iex','AAPL'))
        actual = load_history(self.database, symbol='AAPL', provider='ALPACA', feed='iex',
                              start=None, end=None, page_size=19)
        pd.testing.assert_frame_equal(expected, actual)


if __name__ == '__main__':
    unittest.main()
