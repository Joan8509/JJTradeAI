from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3,tempfile,unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
import pandas as pd
from alpaca_market_data import AlpacaMarketConfig
from bollinger_reference_recovery import ReferenceRecovery,missing_reference_windows
from tests.test_bollinger_tick_stream import CANDLE,seed

class ReferenceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'market.db';self.store,_=seed(self.db)
        self.config=AlpacaMarketConfig('fixture-key','fixture-secret','iex')

    def remove(self,start,end):
        with closing(sqlite3.connect(self.db)) as db:
            with db:db.execute('DELETE FROM minute_bars WHERE timestamp>=? AND timestamp<?',(start.isoformat(),end.isoformat()))

    def test_previous_exact_final_minute_repaired_even_with_later_rows(self):
        minute=CANDLE-timedelta(minutes=1)
        frame=self.store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex',start=minute,end=minute)
        self.remove(minute,CANDLE)
        self.assertEqual(missing_reference_windows(self.db,'AAPL','iex',CANDLE),[(minute,CANDLE)])
        provider=Mock();provider.fetch_minute_bars.return_value=frame
        repair=ReferenceRecovery(self.config,self.store,['AAPL'],provider=provider)
        result=repair.sweep(CANDLE)
        self.assertEqual(result['symbols']['AAPL']['status'],'REPAIRED')
        self.assertEqual(result['symbols']['AAPL']['inserted'],1)
        self.assertEqual(result['signals_evaluated'],0)
        self.assertEqual(missing_reference_windows(self.db,'AAPL','iex',CANDLE),[])

    def test_missing_older_period_is_requested_without_substituting_an_old_one(self):
        start=CANDLE.replace(day=12,hour=18,minute=0);end=start+timedelta(minutes=15)
        self.remove(start,end)
        self.assertEqual(missing_reference_windows(self.db,'AAPL','iex',CANDLE),[(start,end)])

    def test_calendar_et_offsets_use_utc_keys_for_sql_seeks(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with closing(sqlite3.connect(self.db)) as db:
            rows=db.execute('SELECT session_date,opens_at,closes_at FROM market_sessions').fetchall()
            with db:
                for day,a,b in rows:db.execute('UPDATE market_sessions SET opens_at=?,closes_at=? WHERE session_date=?',
                    (datetime.fromisoformat(a).astimezone(ZoneInfo('America/New_York')).isoformat(),datetime.fromisoformat(b).astimezone(ZoneInfo('America/New_York')).isoformat(),day))
        self.assertEqual(missing_reference_windows(self.db,'AAPL','iex',CANDLE),[])

    def test_preopen_checks_preceding_session_final_minute(self):
        opening=CANDLE.replace(hour=13,minute=30)
        final=CANDLE.replace(day=12,hour=19,minute=59)
        self.remove(final,final+timedelta(minutes=1))
        self.assertEqual(missing_reference_windows(self.db,'AAPL','iex',opening-timedelta(minutes=1)),[(final,final+timedelta(minutes=1))])

    def test_provider_cannot_overwrite_existing_bars_or_insert_future_rows(self):
        minute=CANDLE-timedelta(minutes=1)
        frame=self.store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex',start=minute-timedelta(minutes=1),end=minute)
        self.remove(minute,CANDLE)
        provider=Mock();provider.fetch_minute_bars.return_value=frame
        repair=ReferenceRecovery(self.config,self.store,['AAPL'],provider=provider)
        self.assertEqual(repair.sweep(CANDLE)['symbols']['AAPL']['inserted'],1)
        self.assertEqual(len(self.store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex',start=minute-timedelta(minutes=1),end=minute)),2)

    def test_empty_provider_does_not_invent_bar(self):
        minute=CANDLE-timedelta(minutes=1);self.remove(minute,CANDLE)
        provider=Mock();provider.fetch_minute_bars.return_value=pd.DataFrame(columns=['date','open','high','low','close','volume'])
        result=ReferenceRecovery(self.config,self.store,['AAPL'],provider=provider).sweep(CANDLE)
        self.assertEqual(result['symbols']['AAPL']['status'],'PROVIDER_GAPS_REMAIN')
        self.assertEqual(result['symbols']['AAPL']['inserted'],0)

    def test_429_honors_retry_after_and_stops_sweep(self):
        provider=Mock();provider.fetch_minute_bars.side_effect=HTTPError('https://fixture.invalid',429,'fixture',{'Retry-After':'900'},None)
        repair=ReferenceRecovery(self.config,self.store,['MSFT','NVDA'],provider=provider)
        result=repair.sweep(CANDLE)
        self.assertEqual(provider.fetch_minute_bars.call_count,1)
        self.assertEqual(repair.retry_after,900)
        self.assertEqual(result['symbols']['MSFT']['http_status'],429)

    def test_sweep_request_budget_rotates_without_starving_later_symbols(self):
        provider=Mock();provider.fetch_minute_bars.return_value=pd.DataFrame(columns=['date','open','high','low','close','volume'])
        repair=ReferenceRecovery(self.config,self.store,['MSFT','NVDA','TSLA','QQQ','SLV'],provider=provider)
        self.assertEqual(repair.sweep(CANDLE)['requests'],4)
        second=repair.sweep(CANDLE)
        self.assertEqual(next(iter(second['symbols'])),'SLV')

    def test_stop_after_response_prevents_late_database_write(self):
        minute=CANDLE-timedelta(minutes=1)
        frame=self.store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex',start=minute,end=minute)
        self.remove(minute,CANDLE)
        provider=Mock();repair=ReferenceRecovery(self.config,self.store,['AAPL'],provider=provider)
        def response(*args,**kwargs):repair.stop.set();return frame
        provider.fetch_minute_bars.side_effect=response
        repair.sweep(CANDLE)
        self.assertTrue(missing_reference_windows(self.db,'AAPL','iex',CANDLE))

    def test_recovery_lifecycle_does_not_open_another_stream(self):
        from bollinger_tick_stream import RealtimeBollingerStream
        worker=Mock();worker.failed.is_set.return_value=False
        with patch('bollinger_reference_recovery.ReferenceRecovery') as recovery,patch('bollinger_tick_stream.AlpacaStockBarStream') as stream:
            stream.return_value.config=self.config
            adapter=RealtimeBollingerStream(self.config,worker)
            adapter.run(['AAPL'],Mock())
            stream.assert_called_once();stream.return_value.run.assert_called_once()
            recovery.return_value.start.assert_called_once();recovery.return_value.close.assert_called_once()

if __name__=='__main__':unittest.main()
