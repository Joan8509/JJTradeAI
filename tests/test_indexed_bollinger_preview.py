from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import patch
from indexed_bollinger_preview import preview_for_bar
from live_bollinger_preview import evaluate_live_bollinger_preview
from live_market import MarketBar
from tests.test_bollinger_tick_stream import CANDLE,seed

class IndexedPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'market.db';self.store,_=seed(self.db)
    def bar(self,price,stamp=CANDLE):
        b=MarketBar('AAPL',stamp,100,max(100,price),min(100,price),price,100)
        self.store.upsert_bar(b,provider='ALPACA',feed='iex');return b
    def compare(self,b):
        frame=self.store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex',end=b.timestamp)
        old=evaluate_live_bollinger_preview(frame,symbol='AAPL',as_of=b.timestamp)
        new=preview_for_bar(self.db,b,feed='iex')
        for k in ('symbol','timeframe','status','bias','price','as_of','minutes_to_close','confirmed','can_operate','authority'):self.assertEqual(new[k],old[k],k)
        for k in ('bollinger_upper','bollinger_lower'):self.assertAlmostEqual(new[k],old[k],places=8)
    def test_parity_inside_upper_lower_and_partial_minutes(self):
        for price in (100,104,96):
            for minute in (0,7,14):self.compare(self.bar(price,CANDLE+timedelta(minutes=minute)))
    def test_official_same_minute_correction_uses_canonical_stored_price(self):
        old=self.bar(104);self.bar(100);self.compare(old)
    def test_session_open_uses_previous_official_session(self):
        self.compare(self.bar(100,CANDLE.replace(hour=13,minute=30)))
    def test_calendar_et_offsets_preserve_parity_with_utc_minute_keys(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with closing(sqlite3.connect(self.db)) as db:
            rows=db.execute('SELECT session_date,opens_at,closes_at FROM market_sessions').fetchall()
            with db:
                for day,a,b in rows:db.execute('UPDATE market_sessions SET opens_at=?,closes_at=? WHERE session_date=?',
                    (datetime.fromisoformat(a).astimezone(ZoneInfo('America/New_York')).isoformat(),datetime.fromisoformat(b).astimezone(ZoneInfo('America/New_York')).isoformat(),day))
        self.compare(self.bar(104))
    def test_missing_required_period_never_substitutes_an_older_one(self):
        b=self.bar(100);missing=CANDLE.replace(day=12,hour=18,minute=0)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('DELETE FROM minute_bars WHERE timestamp>=? AND timestamp<?',(missing.isoformat(),(missing+timedelta(minutes=15)).isoformat()))
        r=preview_for_bar(self.db,b,feed='iex');self.assertEqual(r['status'],'NO_DISPONIBLE');self.assertFalse(r['can_operate'])
    def test_missing_previous_official_final_minute_is_unavailable(self):
        b=self.bar(100)
        with closing(sqlite3.connect(self.db)) as db,db:db.execute('DELETE FROM minute_bars WHERE timestamp=?',((CANDLE-timedelta(minutes=1)).isoformat(),))
        self.assertEqual(preview_for_bar(self.db,b,feed='iex')['status'],'NO_DISPONIBLE')
    def test_no_pandas_or_archive_frame_needed(self):
        b=self.bar(104)
        with patch('pandas.DataFrame',side_effect=AssertionError('No archive frames')):
            self.assertEqual(preview_for_bar(self.db,b,feed='iex')['status'],'EXPUESTO_SUPERIOR')

if __name__=='__main__':unittest.main()
