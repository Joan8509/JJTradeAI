"""Causal stock playback and missing-data exclusions, with no live DB or API."""
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.study_global_stop_loss import isolated_source
from market_store import DEFAULT_MARKET_DATABASE
from stop_loss_research import (official_grid,reconstruct,evaluate_path,
    independent_paths,summarize_paths)


OPEN=pd.Timestamp('2026-10-16T13:30:00Z')
CLOSE=OPEN+pd.Timedelta(minutes=390)
EVENT=OPEN+pd.Timedelta(minutes=300)
SESSIONS={'2026-10-16':(OPEN,CLOSE)}


def flat_bars():
    dates=pd.date_range(OPEN,CLOSE,freq='min',inclusive='left')
    return pd.DataFrame({'date':dates,'open':100.,'high':100.,'low':100.,'close':100.})


class StopLossResearchTests(unittest.TestCase):
    def event(self,side='SUPERIOR'):
        return {'symbol':'TEST','side':side,'detected_at':(EVENT+pd.Timedelta(minutes=1)).isoformat()}

    def test_active_database_is_rejected_without_opening_it(self):
        with patch('sqlite3.connect',side_effect=AssertionError('Never open active DB')):
            with self.assertRaisesRegex(ValueError,'ISOLATED_COPY'):
                isolated_source(DEFAULT_MARKET_DATABASE)

    def test_no_future_minutes_or_final_candle_close_authorize_earlier_signal(self):
        bars=flat_bars();bars.loc[300,['high','close']]=105.
        now=EVENT+pd.Timedelta(minutes=1)
        first,_=reconstruct(official_grid(bars,SESSIONS,now),symbol='TEST',cutoff=OPEN)
        bars.loc[301:314,['open','high','low','close']]=1.
        second,_=reconstruct(official_grid(bars,SESSIONS,now),symbol='TEST',cutoff=OPEN)
        self.assertEqual(first,second);self.assertEqual(len(first),1)
        self.assertEqual(first[0]['side'],'SUPERIOR')
        self.assertEqual(pd.Timestamp(first[0]['detected_at']),now)

    def test_future_minutes_are_not_counted_as_historical_data_gaps(self):
        now=EVENT+pd.Timedelta(minutes=1)
        _,coverage=reconstruct(official_grid(flat_bars(),SESSIONS,now),symbol='TEST',cutoff=OPEN)
        self.assertEqual(coverage['official_minutes'],301)
        self.assertEqual(coverage['unavailable_future_minutes'],89)
        self.assertEqual(coverage['missing_or_invalid_minutes'],0)

    def test_missing_prior_minute_or_official_open_blocks_reconstruction(self):
        bars=flat_bars();bars.loc[300,['high','close']]=105.
        for missing in (10,300):
            with self.subTest(missing=missing):
                grid=official_grid(bars.drop(index=missing),SESSIONS,EVENT+pd.Timedelta(minutes=2))
                events,coverage=reconstruct(grid,symbol='TEST',cutoff=OPEN)
                self.assertEqual(events,[])
                self.assertGreater(coverage['missing_or_invalid_minutes'],0)

    def test_future_evaluation_starts_at_next_open_not_signal_close(self):
        bars=flat_bars();bars.loc[301:305,['high','low','close']]=[102.,99.,101.]
        grid=official_grid(bars,SESSIONS,CLOSE)
        for side in ('SUPERIOR','INFERIOR'):
            row,error=evaluate_path(self.event(side),grid,5,CLOSE)
            self.assertIsNone(error);self.assertEqual(row['entry_reference_stock_open'],100.)
            self.assertAlmostEqual(row['stock_mae_pct'],1. if side=='SUPERIOR' else 2.)
            self.assertAlmostEqual(row['stock_mfe_pct'],2. if side=='SUPERIOR' else 1.)
            self.assertAlmostEqual(row['stock_directional_close_pct'],1. if side=='SUPERIOR' else -1.)

    def test_gap_duplicate_and_invalid_ohlc_are_unknown_and_never_filled(self):
        bars=flat_bars()
        for modified in (bars.drop(index=303),pd.concat([bars,bars.iloc[[303]]]),
                bars.assign(low=bars.low.mask(bars.index==303,101.))):
            with self.subTest():
                grid=official_grid(modified,SESSIONS,CLOSE)
                row,error=evaluate_path(self.event(),grid,5,CLOSE)
                self.assertIsNone(row);self.assertEqual(error,'MISSING_OR_INVALID_PATH')

    def test_unavailable_future_and_session_close_are_censored(self):
        grid=official_grid(flat_bars(),SESSIONS,CLOSE)
        row,error=evaluate_path(self.event(),grid,5,EVENT+pd.Timedelta(minutes=3))
        self.assertIsNone(row);self.assertEqual(error,'FUTURE_NOT_AVAILABLE')
        event={**self.event(),'detected_at':(CLOSE-pd.Timedelta(minutes=1)).isoformat()}
        row,error=evaluate_path(event,grid,5,CLOSE)
        self.assertIsNone(row);self.assertEqual(error,'CROSSES_SESSION_CLOSE')

    def test_overlapping_windows_are_excluded_across_both_directions(self):
        grid=official_grid(flat_bars(),SESSIONS,CLOSE)
        a=self.event();b={**self.event('INFERIOR'),'detected_at':(EVENT+pd.Timedelta(minutes=2)).isoformat()}
        rows,excluded=independent_paths([a,b],grid,5,CLOSE)
        self.assertEqual(len(rows),1);self.assertEqual(excluded['OVERLAPPING_WINDOW_SAME_SYMBOL'],1)

    def test_missing_symbol_and_small_samples_do_not_produce_option_stop(self):
        bars=flat_bars().iloc[:0]
        grid=official_grid(bars,SESSIONS,CLOSE)
        events,coverage=reconstruct(grid,symbol='MISSING',cutoff=OPEN)
        self.assertEqual(events,[]);self.assertEqual(coverage['known_minutes'],0)
        row,_=evaluate_path(self.event(),official_grid(flat_bars(),SESSIONS,CLOSE),5,CLOSE)
        summary=summarize_paths([row])
        self.assertEqual(summary['status'],'INSUFFICIENT_STOCK_DATA')
        self.assertIsNone(summary['option_stop_recommendation_pct'])


if __name__=='__main__':unittest.main()
