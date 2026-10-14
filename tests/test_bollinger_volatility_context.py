"""Known-at-signal Hour/Daily geometry, calendar boundaries and unknown data."""
import unittest
from pathlib import Path
import tempfile
import sqlite3
import pandas as pd
from bollinger_volatility_context import HigherVolatilityHistory,measure_volatility,live_volatility_context,_live_history
from scripts.study_bollinger_higher_volatility import context_conditions,independent_rows,stats


def fixture():
    sessions={};rows=[]
    dates=pd.bdate_range('2026-08-25',periods=24)
    for day,index in zip(dates,range(24)):
        opening=day.tz_localize('America/New_York')+pd.Timedelta(hours=9,minutes=30)
        close=opening+pd.Timedelta(minutes=390)
        key=day.date().isoformat();sessions[key]=(opening.tz_convert('UTC'),close.tz_convert('UTC'))
        price=101. if index%2==0 else 99.
        for minute in range(390):
            value=104. if index==23 and minute in (16,59,389) else price
            rows.append({'date':opening.tz_convert('UTC')+pd.Timedelta(minutes=minute),
                         'open':value,'high':value,'low':value,'close':value,'volume':100})
    return pd.DataFrame(rows),sessions


def event(sessions,minute=16):
    day=sorted(sessions)[-1];start=sessions[day][0]
    stamp=start+pd.Timedelta(minutes=minute)
    return {'source_timestamp':stamp.isoformat(),'detected_at':(stamp+pd.Timedelta(minutes=1)).isoformat(),
            'side':'SUPERIOR','price':104.}


class HigherVolatilityTests(unittest.TestCase):
    def test_first_tick_of_session_has_hour_day_context_before_first_minute_bar(self):
        bars,sessions=fixture();day=sorted(sessions)[-1];opening=sessions[day][0]
        known=bars[bars.date<opening]
        signal={'source_timestamp':(opening+pd.Timedelta(milliseconds=250)).isoformat(),
                'detected_at':(opening+pd.Timedelta(milliseconds=300)).isoformat(),
                'price':104.,'side':'SUPERIOR'}
        context=HigherVolatilityHistory(known,sessions).at(signal,available_at=signal['source_timestamp'])
        for tf in ('1H','1D'):
            self.assertEqual(context['frames'][tf]['observed']['state'],'DESCRIPTIVE')
            self.assertTrue(context['frames'][tf]['observed']['provisional'])
            self.assertFalse(context['frames'][tf]['observed']['opening_minute_observed'])
            self.assertEqual(context['frames'][tf]['last_closed']['state'],'DESCRIPTIVE')

    def test_live_snapshot_excludes_not_yet_closed_and_later_received_minutes(self):
        from market_store import MarketBarStore
        from market_calendar import MarketSession,MarketSessionRepository
        bars,sessions=fixture();signal=event(sessions,16)
        available=pd.Timestamp(signal['source_timestamp'])+pd.Timedelta(milliseconds=250)
        # A genuine current price can be observed within minute 16 before its
        # final minute-close history exists. Later daily values must not leak.
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            MarketSessionRepository(database).upsert(tuple(MarketSession(pd.Timestamp(key).date(),op.to_pydatetime(),close.to_pydatetime()) for key,(op,close) in sessions.items()))
            MarketBarStore(database).upsert_frame(bars,symbol='AAPL',provider='ALPACA',feed='iex')
            with sqlite3.connect(database) as db:
                db.execute("UPDATE minute_bars SET received_at='2026-08-01T00:00:00+00:00'")
                # Deliberately poison data whose interval has not closed yet.
                db.execute('UPDATE minute_bars SET close=9999,high=9999 WHERE timestamp>=?',(pd.Timestamp(signal['source_timestamp']).isoformat(),))
            db.close()
            _live_history.cache_clear()
            actual=live_volatility_context(database,'AAPL','ALPACA','iex',signal['source_timestamp'],signal,available_at=available)
            prefix=bars[bars.date+pd.Timedelta(minutes=1)<=available]
            expected=HigherVolatilityHistory(prefix,sessions).at(signal,available_at=available)
            self.assertEqual(actual,expected)
            # Losing a previous scheduled closing minute produces UNKNOWN,
            # not a fabricated confirmation or a low-volatility classification.
            prior_day=sorted(sessions)[-2];late=sessions[prior_day][1]-pd.Timedelta(minutes=1)
            with sqlite3.connect(database) as db:
                db.execute('UPDATE minute_bars SET received_at=? WHERE timestamp=?',
                    ((available+pd.Timedelta(seconds=1)).isoformat(),late.isoformat()))
            db.close()
            _live_history.cache_clear()
            later=live_volatility_context(database,'AAPL','ALPACA','iex',signal['source_timestamp'],signal,available_at=available)
            self.assertEqual(later['frames']['1D']['observed']['state'],'UNKNOWN')
            _live_history.cache_clear()

    def test_amplitude_is_separate_from_net_direction_and_not_intraminute_high(self):
        row={'source_timestamp':'2026-10-13T14:00:00+00:00',
             'outcomes':{'15':{'first_pullback_minutes':2,'points':[
                 {'directional_change_from_signal_pct':.5},
                 {'directional_change_from_signal_pct':-.5}]+[
                 {'directional_change_from_signal_pct':0.}]*13}}}
        result=stats([row])['outcomes_from_signal_price']
        self.assertEqual(result['2']['mean_max_favorable_close_pct'],.5)
        self.assertEqual(result['2']['mean_max_adverse_close_pct'],.5)
        self.assertEqual(result['15']['mean_directional_return_pct'],0.)
        self.assertEqual(result['15']['positive_pct'],0.)

    def test_current_hour_and_day_future_prices_cannot_change_context(self):
        bars,sessions=fixture();signal=event(sessions)
        expected=HigherVolatilityHistory(bars,sessions).at(signal)
        self.assertEqual(expected['frames']['1H']['observed']['state'],'DESCRIPTIVE')
        self.assertEqual(expected['frames']['1D']['observed']['state'],'DESCRIPTIVE')
        self.assertTrue(expected['frames']['1H']['observed']['provisional'])
        future=bars.date>pd.Timestamp(signal['source_timestamp'])
        bars.loc[future,['open','high','low','close']]=9999.
        actual=HigherVolatilityHistory(bars,sessions).at(signal)
        self.assertEqual(actual,expected)

    def test_both_bands_can_open_without_price_exposed_in_parent_timeframe(self):
        result=measure_volatility([101.,99.]*10,102.1,'SUPERIOR')
        self.assertTrue(result['both_bands_open'])
        self.assertTrue(result['midpoint_aligned'])
        self.assertEqual(result['price_location'],'UPPER_HALF')

    def test_wider_band_by_one_side_is_not_both_bands_open(self):
        prior=[95.4,98.6,103.58,102.09,95.99,95.55,99.08,104.94,95.74,103.34,
               101.59,104.39,97.51,101.18,102.63,98.48,104.58,101.54,98.19,103.85]
        result=measure_volatility(prior,108.,'SUPERIOR')
        self.assertTrue(result['width_increasing'])
        self.assertFalse(result['both_bands_open'])
        self.assertEqual(result['regime'],'WIDTH_GROWING_ONE_SIDE')

    def test_unknown_reference_is_not_counted_as_no_volatility(self):
        bars,sessions=fixture();signal=event(sessions)
        prior_day=sorted(sessions)[-2];closing=sessions[prior_day][1]-pd.Timedelta(minutes=1)
        missing=bars[bars.date!=closing]
        result=HigherVolatilityHistory(missing,sessions).at(signal)
        self.assertEqual(result['frames']['1D']['observed']['state'],'UNKNOWN')
        self.assertIsNone(context_conditions(result)['DAY_OBSERVED'])
        self.assertIsNone(context_conditions(result)['BOTH_OBSERVED'])

    def test_missing_preceding_day_cannot_reuse_an_older_daily_reference(self):
        bars,sessions=fixture();signal=event(sessions)
        missing_day=sorted(sessions)[-2]
        dates=bars.date.dt.tz_convert('America/New_York').dt.date.astype(str)
        result=HigherVolatilityHistory(bars[dates!=missing_day],sessions).at(signal)
        self.assertEqual(result['frames']['1D']['observed']['state'],'UNKNOWN')
        self.assertEqual(result['frames']['1D']['last_closed']['state'],'UNKNOWN')

    def test_exact_hour_boundary_and_last_short_hour_respect_calendar_close(self):
        bars,sessions=fixture();signal=event(sessions,59)
        context=HigherVolatilityHistory(bars,sessions).at(signal)
        self.assertFalse(context['frames']['1H']['observed']['provisional'])
        self.assertEqual(context['frames']['1H']['observed']['upper'],context['frames']['1H']['last_closed']['upper'])
        signal=event(sessions,389)
        context=HigherVolatilityHistory(bars,sessions).at(signal)
        self.assertFalse(context['frames']['1H']['observed']['provisional'])
        self.assertEqual(context['frames']['1H']['observed']['candle_end'],signal['detected_at'])
        self.assertFalse(context['frames']['1D']['observed']['provisional'])

    def test_hour_opening_direction_can_oppose_15m_side(self):
        result=measure_volatility([101.,99.]*10,102.1,'INFERIOR')
        self.assertTrue(result['both_bands_open'])
        self.assertFalse(result['midpoint_aligned'])


if __name__=='__main__':unittest.main()
