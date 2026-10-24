"""Operational recovery never invents data, overruns the session or retries 429."""
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from alpaca_market_data import AlpacaMarketConfig
from market_calendar import MarketSession, MarketSessionRepository
from market_store import MarketBarStore
import vps_private_runtime as runtime
from scripts.observe_vps_recovery import recover
from scripts.watch_vps_readiness import reference_coverage, read_observation

UTC = timezone.utc


class RecoveryObserverTests(unittest.TestCase):
    def test_existing_official_bars_do_not_open_write_repository(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory)/'db.sqlite'
            store = MarketBarStore(database)
            start = datetime(2026,10,15,13,30,tzinfo=UTC)
            MarketSessionRepository(database).upsert((MarketSession(start.date(), start, start.replace(hour=20,minute=0)),))
            frame = pd.DataFrame([dict(date=start,open=100.,high=101.,low=99.,close=100.,volume=100)])
            store.upsert_frame(frame,symbol='AAPL',provider='ALPACA',feed='iex')
            with patch.object(runtime,'DATABASE',database), \
                 patch('scripts.observe_vps_recovery.AlpacaMarketDataProvider.fetch_minute_bars',return_value=frame), \
                 patch('scripts.observe_vps_recovery.MarketBarStore') as writer:
                result = recover(AlpacaMarketConfig('test','test'),['AAPL'],as_of=start.replace(hour=22))
            writer.assert_not_called()
            self.assertEqual(result['symbols']['AAPL']['inserted'],0)
            self.assertEqual(result['symbols']['AAPL']['provider_rows_missing_locally'],0)

    def test_recovery_writes_only_missing_subset_without_overwriting_existing_price(self):
        import pandas as pd
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory)/'db.sqlite'
            store = MarketBarStore(database)
            start = datetime(2026,10,15,13,30,tzinfo=UTC)
            MarketSessionRepository(database).upsert((MarketSession(start.date(), start, start.replace(hour=20,minute=0)),))
            frame = pd.DataFrame([dict(date=start+timedelta(minutes=i),open=100.,high=101.,low=99.,close=100.,volume=100) for i in range(2)])
            store.upsert_frame(frame.iloc[:1],symbol='AAPL',provider='ALPACA',feed='iex')
            frame.loc[0,'close']=100.5  # Existing official row must remain untouched.
            with patch.object(runtime,'DATABASE',database), \
                 patch('scripts.observe_vps_recovery.AlpacaMarketDataProvider.fetch_minute_bars',return_value=frame), \
                 patch('scripts.observe_vps_recovery.MarketBarStore',return_value=store), \
                 patch.object(store,'upsert_frame',wraps=store.upsert_frame) as write:
                result = recover(AlpacaMarketConfig('test','test'),['AAPL'],as_of=start.replace(hour=22))
            self.assertEqual(len(write.call_args.args[0]),1)
            self.assertTrue(write.call_args.kwargs['only_missing'])
            saved=store.load_frame(symbol='AAPL',provider='ALPACA',feed='iex')
            self.assertEqual(saved.close.tolist(),[100.,100.])
            self.assertEqual(result['symbols']['AAPL']['inserted'],1)

    def test_transient_read_failure_removes_stale_readiness_evidence(self):
        import sqlite3
        with patch('scripts.watch_vps_readiness.snapshot', side_effect=sqlite3.OperationalError('interrupted')), \
             patch('scripts.watch_vps_readiness.reference_coverage') as coverage:
            result = read_observation(['AAPL'])
        self.assertFalse(result['observation_available'])
        self.assertIsNone(result['latest_snapshot'])
        self.assertEqual(result['reference_coverage'], {})
        coverage.assert_not_called()
        with patch('scripts.watch_vps_readiness.snapshot', return_value={'runtime': 'CONECTADO'}), \
             patch('scripts.watch_vps_readiness.reference_coverage', return_value={'AAPL': {'history_periods_present': False}}):
            result = read_observation(['AAPL'])
        self.assertTrue(result['observation_available'])
        self.assertFalse(result['reference_coverage']['AAPL']['history_periods_present'])

    def test_rate_limit_stops_sweep_and_preserves_retry_after(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory)/'db.sqlite'
            MarketBarStore(database)
            MarketSessionRepository(database).upsert((MarketSession(date(2026,10,15),
                datetime(2026,10,15,13,30,tzinfo=UTC),datetime(2026,10,15,20,tzinfo=UTC)),))
            failure = HTTPError('https://example.invalid',429,'rate limited',{'Retry-After':'600'},None)
            with patch.object(runtime,'DATABASE',database), patch('scripts.observe_vps_recovery.AlpacaMarketDataProvider.fetch_minute_bars',side_effect=failure) as fetch:
                result = recover(AlpacaMarketConfig('test','test'),['AAPL','SPY'],
                                 as_of=datetime(2026,10,15,22,tzinfo=UTC))
            self.assertTrue(result['rate_limited'])
            self.assertEqual(result['retry_after_seconds'],600)
            self.assertEqual(list(result['symbols']),['AAPL'])
            fetch.assert_called_once()
            self.assertEqual(result['end'],'2026-10-15T19:59:00+00:00')
            self.assertEqual(result['symbols']['AAPL']['inserted'],0)

    def test_reference_diagnostic_does_not_request_after_close_periods(self):
        from tests.test_bollinger_tick_stream import seed
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'db.sqlite'
            seed(database)
            with patch.object(runtime,'DATABASE',database):
                result=reference_coverage(['AAPL'],datetime(2026,10,13,22,tzinfo=UTC))['AAPL']
            self.assertFalse(result['market_open'])
            self.assertEqual(result['current_candle'],'2026-10-13T20:00:00+00:00')
            self.assertEqual(result['expected_periods'],20)
            self.assertTrue(all(t<'2026-10-13T20:00:00+00:00' for t in result['missing_15m_period_starts']))
            self.assertIn('previous_Bollinger_20_closes',result['blocked_calculations'])
