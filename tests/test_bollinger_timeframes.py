"""Prevent timeframe coincidence, future data and missing-minute assumptions."""
import unittest
import pandas as pd
from scripts.study_bollinger_timeframes import (
    band_state, prepare_one_minute, prepare_fifteen, signal_features, path_outcomes)


START=pd.Timestamp('2026-10-13T13:30Z')
SESSIONS={'2026-10-13':(START,START+pd.Timedelta(minutes=390))}


def fixture():
    rows=[]
    for i in range(330):
        price=99. if (i//15)%2==0 else 101.
        if 285<=i<299:price=105.
        if i==299:price=100.
        if i>=300:price=104.
        rows.append(dict(date=START+pd.Timedelta(minutes=i),open=100. if i==300 else price,
                         high=max(price,100.) if i==300 else price,
                         low=min(price,100.) if i==300 else price,close=price,volume=100))
    return pd.DataFrame(rows)


def views(bars):
    frame=prepare_one_minute(bars,SESSIONS)
    records,positions=prepare_fifteen(frame,SESSIONS)
    row_positions={pd.Timestamp(stamp):i for i,stamp in enumerate(frame.date)}
    return frame,row_positions,records,positions


def event():
    stamp=START+pd.Timedelta(minutes=300)
    return {'symbol':'AAPL','provider':'ALPACA','feed':'iex','side':'SUPERIOR',
            'candle':stamp.isoformat(),'source_timestamp':stamp.isoformat(),
            'detected_at':(stamp+pd.Timedelta(minutes=1)).isoformat(),'price':104.}


class TimeframeTests(unittest.TestCase):
    def test_reentry_of_1m_band_can_happen_while_price_keeps_advancing(self):
        from scripts.review_bollinger_timeframes import reentry_review
        row={'symbol':'AAPL','side':'SUPERIOR','source_timestamp':START.isoformat(),
             'state_1m':'SAME_DIRECTION_OUTSIDE','outcomes':{'15':{'points':[
                 {'minute':1,'original_candle_15m':True,'state_1m':'INSIDE',
                  'state_original_15m':'SAME_DIRECTION_OUTSIDE','qualified_original_15m':True,
                  'directional_change_from_signal_pct':.1}]}}}
        result=reentry_review([row])
        self.assertEqual(result['n'],1)
        self.assertEqual(result['positive_close_count'],1)
        self.assertEqual(result['adverse_count'],0)

    def test_inside_from_start_is_not_counted_as_a_new_1m_reentry(self):
        from scripts.review_bollinger_timeframes import reentry_review
        row={'symbol':'AAPL','side':'SUPERIOR','source_timestamp':START.isoformat(),
             'state_1m':'INSIDE','outcomes':{'15':{'points':[
                 {'minute':1,'original_candle_15m':True,'state_1m':'INSIDE',
                  'state_original_15m':'SAME_DIRECTION_OUTSIDE','qualified_original_15m':True,
                  'directional_change_from_signal_pct':.1}]}}}
        self.assertEqual(reentry_review([row])['n'],0)

    def test_inside_1m_can_coexist_with_valid_15m_exit(self):
        feature,error=signal_features(event(),*views(fixture()))
        self.assertIsNone(error)
        self.assertEqual(feature['state_1m'],'INSIDE')
        self.assertGreater(feature['exposure_pct_bandwidth_15m'],0)
        self.assertFalse(feature['new_exit_rule_1m'])

    def test_future_1m_and_final_15m_closes_do_not_change_signal_features(self):
        bars=fixture()
        feature,error=signal_features(event(),*views(bars))
        bars.loc[301:,['open','high','low','close']]=9999.
        changed,changed_error=signal_features(event(),*views(bars))
        self.assertIsNone(error)
        self.assertIsNone(changed_error)
        self.assertEqual(feature,changed)

    def test_missing_1m_window_is_unknown_and_missing_15m_close_excluded(self):
        bars=fixture().drop(index=297).reset_index(drop=True)
        feature,error=signal_features(event(),*views(bars))
        self.assertIsNone(error)
        self.assertEqual(feature['state_1m'],'UNKNOWN')
        feature,error=signal_features(event(),*views(fixture().drop(index=299).reset_index(drop=True)))
        self.assertIsNone(feature)
        self.assertEqual(error,'MISSING_15M_REFERENCE_CLOSE')

    def test_original_candle_is_censored_when_it_ends(self):
        frame,rows,records,positions=views(fixture())
        result,error=path_outcomes(event(),frame,rows,records,positions,
            SESSIONS['2026-10-13'][1],START+pd.Timedelta(minutes=390),15)
        self.assertIsNone(error)
        self.assertEqual(result['original_15m_remaining_observed_minutes'],14)
        self.assertTrue(result['had_inside_1m_while_original_15m_outside'])
        self.assertFalse(result['points'][-1]['original_candle_15m'])
        self.assertIsNone(result['points'][-1]['state_original_15m'])

    def test_postsignal_gap_and_entry_return_are_distinct(self):
        bars=fixture()
        bars.loc[301:,['open','high','low','close']]=103.
        frame,rows,records,positions=views(bars)
        result,error=path_outcomes(event(),frame,rows,records,positions,
            SESSIONS['2026-10-13'][1],START+pd.Timedelta(minutes=390),5)
        self.assertIsNone(error)
        self.assertEqual(result['return_pct'],0)
        self.assertLess(result['return_from_signal_pct'],0)
        self.assertEqual(result['first_pullback_minutes'],1)

    def test_unknown_touch_and_opposite_states_are_not_same_exposure(self):
        self.assertEqual(band_state(104,105,95,'SUPERIOR'),'INSIDE')
        self.assertEqual(band_state(105,105,95,'SUPERIOR'),'INSIDE')
        self.assertEqual(band_state(94,105,95,'SUPERIOR'),'OPPOSITE_OUTSIDE')
        self.assertEqual(band_state(106,105,95,'SUPERIOR',known=False),'UNKNOWN')
        self.assertEqual(band_state(94,105,95,'INFERIOR'),'SAME_DIRECTION_OUTSIDE')


if __name__=='__main__':unittest.main()
