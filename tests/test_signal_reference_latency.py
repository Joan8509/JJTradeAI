"""Reference parity and latency evidence on isolated SQLite databases only."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from bollinger_tick_stream import TickGeometry, RealtimeBollingerWorker, record_ingest_revision
from live_market import aggregate_minute_bars
from market_calendar import MarketSession, MarketSessionRepository
from market_store import MarketBarStore
from tests.test_bollinger_tick_stream import CANDLE, seed, trade

UTC = timezone.utc


class SignalReferenceLatencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'isolated.db'
        self.store, self.closes = seed(self.database)
        self.now = CANDLE+timedelta(seconds=1)
        self.geometry = TickGeometry(self.database, 'iex', now=lambda:self.now)
        self.geometry.status('CONECTADO', CANDLE-timedelta(seconds=1))
        self.geometry.session = self.geometry.calendar.session(CANDLE.date())

    def test_required_twenty_closes_equal_legacy_aggregation_without_loading_minute_frames(self):
        original = self.store.load_frame(symbol='AAPL', provider='ALPACA', feed='iex',
            start=CANDLE-timedelta(days=7), end=CANDLE-timedelta(minutes=1))
        expected = aggregate_minute_bars(original,'15m').close.tail(20).astype(float).tolist()
        # Current/future prices, a different feed and symbol must not leak in.
        with closing(sqlite3.connect(self.database)) as db, db:
            for symbol, feed, stamp in (
                    ('AAPL','iex',CANDLE), ('OTHER','iex',CANDLE-timedelta(minutes=1)),
                    ('AAPL','sip',CANDLE-timedelta(minutes=1)),
                    ('AAPL','iex',CANDLE.replace(hour=12))):
                db.execute('INSERT INTO minute_bars VALUES(?,?,?,?,?,?,?,?,?,?)',
                    ('ALPACA',feed,symbol,stamp.isoformat(),999.,999.,999.,999.,1.,self.now.isoformat()))
        with patch.object(self.geometry.store,'load_frame',side_effect=AssertionError('heavy history load')):
            self.assertEqual(self.geometry._history('AAPL',CANDLE,self.now), expected)

    def test_sparse_older_period_preserves_its_actual_last_close(self):
        period = CANDLE.replace(day=12,hour=18,minute=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp>? AND timestamp<?',
                ((period+timedelta(minutes=5)).isoformat(),(period+timedelta(minutes=15)).isoformat()))
        original = self.store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex',
            start=CANDLE-timedelta(days=7),end=CANDLE-timedelta(minutes=1))
        expected = aggregate_minute_bars(original,'15m').close.tail(20).astype(float).tolist()
        self.assertEqual(self.geometry._history('AAPL',CANDLE,self.now),expected)

    def test_short_session_and_weekend_use_official_last_closing_minute(self):
        database = Path(self.temp.name)/'short_session.db'
        opening = datetime(2026,10,19,13,30,tzinfo=UTC)
        sessions = [MarketSession(opening.replace(day=15).date(),opening.replace(day=15),opening.replace(day=15,hour=20,minute=0)),
            MarketSession(opening.replace(day=16).date(),opening.replace(day=16),opening.replace(day=16,hour=17,minute=0)),
            MarketSession(opening.date(),opening,opening.replace(hour=20,minute=0))]
        MarketSessionRepository(database).upsert(tuple(sessions))
        rows=[];closes=[]
        for session in sessions[:-1]:
            period=session.opens_at
            while period<session.closes_at:
                p=100.+len(closes)/10;closes.append(p)
                for minute in range(15):
                    rows.append(dict(date=period+timedelta(minutes=minute),open=p,high=p,low=p,close=p,volume=1))
                period+=timedelta(minutes=15)
        store=MarketBarStore(database)
        store.upsert_frame(pd.DataFrame(rows),symbol='AAPL',provider='ALPACA',feed='iex')
        geometry=TickGeometry(database,'iex');geometry.session=sessions[-1]
        self.assertEqual(geometry._history('AAPL',opening,opening),closes[-20:])
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('DELETE FROM minute_bars WHERE timestamp=?',
                ((sessions[-2].closes_at-timedelta(minutes=1)).isoformat(),))
        self.assertIsNone(geometry._history('AAPL',opening,opening))

    def test_history_seeks_use_market_index_and_return_at_most_one_row_per_period(self):
        with closing(sqlite3.connect(self.database)) as db:
            plan=db.execute('EXPLAIN QUERY PLAN SELECT timestamp,close FROM minute_bars '
                'WHERE provider=? AND feed=? AND symbol=? AND timestamp>=? AND timestamp<=? '
                'ORDER BY timestamp DESC LIMIT 1',
                ('ALPACA','iex','AAPL',(CANDLE-timedelta(minutes=15)).isoformat(),
                 (CANDLE-timedelta(minutes=1)).isoformat())).fetchall()
        self.assertIn('SEARCH minute_bars USING INDEX', ' '.join(r[-1] for r in plan))

    def test_price_becoming_stale_during_history_work_cannot_publish_exit(self):
        self.geometry.observe(trade(100.,self.now,1),self.now)
        self.geometry.states['AAPL']['history']=None
        self.now+=timedelta(seconds=1)
        def delayed(*args):
            self.now+=timedelta(seconds=4)
            return self.closes
        with patch.object(self.geometry,'_history',side_effect=delayed):
            snapshot,reason=self.geometry.observe(trade(104.,self.now,2),self.now)
        self.assertIsNone(snapshot)
        self.assertEqual(reason,'DISCONNECTED_OR_STALE')
        self.now+=timedelta(seconds=1)
        snapshot,reason=self.geometry.observe(trade(104.,self.now,3),self.now)
        self.assertEqual(reason,'EXIT')
        self.assertEqual(snapshot['checked_at'],self.now.isoformat())

    def test_saved_geometry_explains_inside_opening_and_both_band_expansion(self):
        self.geometry.observe(trade(100.,self.now,1),self.now)
        self.now+=timedelta(seconds=1)
        snapshot,reason=self.geometry.observe(trade(104.,self.now,2),self.now)
        detail=snapshot['geometry']
        self.assertEqual(reason,'EXIT')
        self.assertLessEqual(detail['opening_lower'],detail['opening'])
        self.assertLessEqual(detail['opening'],detail['opening_upper'])
        self.assertGreater(detail['upper'],detail['previous_upper'])
        self.assertLess(detail['lower'],detail['previous_lower'])
        self.assertGreater(detail['price'],detail['upper'])
        self.assertGreater(detail['mid'],detail['previous_mid'])
        self.assertEqual(detail['side'],snapshot['signal']['side'])

    def test_raw_audit_preserves_trade_and_separates_receipt_from_processing(self):
        worker=RealtimeBollingerWorker(self.database,'iex',['AAPL'])
        received=datetime.now(UTC);message=trade(104.,received,88)
        try:
            worker.trade(message)
            worker.queue.join()
        finally:
            worker.close()
        with closing(sqlite3.connect(self.database)) as db:
            row=db.execute('SELECT received_at,message_json FROM bollinger_tick_audit ORDER BY id DESC LIMIT 1').fetchone()
        saved=json.loads(row[1]);detail=saved.pop('_jjtrade')
        self.assertEqual(saved,message)
        self.assertNotIn('_jjtrade',message)
        self.assertGreaterEqual(datetime.fromisoformat(detail['processing_started_at']),datetime.fromisoformat(row[0]))
        self.assertGreaterEqual(datetime.fromisoformat(detail['processed_at']),datetime.fromisoformat(detail['processing_started_at']))
        self.assertFalse(detail['connected'])

    def test_loaded_receipt_has_only_fixed_revision_identity_and_source_digest(self):
        import hashlib
        import os
        import bollinger_tick_stream
        record_ingest_revision(self.database)
        receipt=json.loads((self.database.parent/'trade_review/ingest_runtime/loaded.json').read_text())
        self.assertEqual(set(receipt),{'utc','pid','revision','source_sha256','sqlite_version'})
        self.assertEqual(receipt['sqlite_version'],sqlite3.sqlite_version)
        self.assertEqual(receipt['pid'],os.getpid())
        self.assertEqual(receipt['source_sha256'],hashlib.sha256(Path(bollinger_tick_stream.__file__).read_bytes()).hexdigest())


if __name__=='__main__':
    unittest.main()
