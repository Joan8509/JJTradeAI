"""Intraminute timing, opening integrity, corrections and queue isolation."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from bollinger_tick_stream import TickGeometry, TickRepository, RealtimeBollingerWorker, eligible_trade
from bollinger_phone_worker import tick
from data_providers import prepare_market_frame
from live_market import MarketBar
from market_calendar import MarketSession, MarketSessionRepository
from market_store import MarketBarStore

UTC = timezone.utc
CANDLE = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)


def trade(price, stamp, identifier=1, **extra):
    return dict(T='t', S='AAPL', p=price, s=100, c=['@'], z='C', x='V', i=identifier,
                t=stamp.isoformat(), **extra)


def seed(database):
    sessions = tuple(MarketSession(day.date(), day.replace(hour=13, minute=30), day.replace(hour=20))
                     for day in (CANDLE-timedelta(days=1), CANDLE))
    MarketSessionRepository(database).upsert(sessions)
    starts = [CANDLE.replace(day=12, hour=15, minute=0)+timedelta(minutes=15*i) for i in range(20)]
    starts += [CANDLE.replace(hour=13, minute=30), CANDLE.replace(hour=13, minute=45)]
    closes = [99. if i % 2 == 0 else 101. for i in range(21)]+[100.]
    rows = [dict(date=start+timedelta(minutes=m),open=p,high=p,low=p,close=p,volume=100)
            for start,p in zip(starts,closes) for m in range(15)]
    store = MarketBarStore(database)
    store.upsert_frame(pd.DataFrame(rows),symbol='AAPL',provider='ALPACA',feed='iex')
    return store,closes[-20:]


class TickGeometryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name)/'market.db'
        self.store,self.closes = seed(self.database)
        self.now = CANDLE+timedelta(seconds=2)
        self.geometry = TickGeometry(self.database,'iex',now=lambda:self.now)
        self.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))

    def observe(self,price,offset,identifier):
        self.now=CANDLE+timedelta(seconds=offset)
        return self.geometry.observe(trade(price,self.now,identifier),self.now)

    def test_both_directions_inside_first_minute_match_existing_geometry(self):
        from bollinger_phone_worker import detect_exit
        for price,side in ((104.,'SUPERIOR'),(96.,'INFERIOR')):
            self.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
            self.observe(100.,1,100 if price==104 else 200)
            snapshot,reason=self.observe(price,2,101 if price==104 else 201)
            self.assertEqual(reason,'EXIT')
            self.assertEqual(snapshot['signal']['side'],side)
            self.assertEqual(snapshot['source_timestamp'],self.now.isoformat())
            # Same 20-period ddof=0 rule as the minute playback; no future close.
            frame=pd.DataFrame({'date':pd.date_range('2026-10-12T14:00Z',periods=21,freq='15min'),
                                'close':self.closes+[price],'open':[100.]*21})
            expected=detect_exit(prepare_market_frame(frame))
            self.assertEqual(snapshot['signal']['side'],expected['side'])
            self.assertAlmostEqual(snapshot['signal']['exposure_pct_bandwidth'],expected['exposure_pct_bandwidth'])

    def test_gap_and_retraction_do_not_become_qualified_exits(self):
        self.observe(104.,1,1)
        snapshot,_=self.observe(106.,2,2)
        self.assertIsNone(snapshot['signal'])
        self.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        self.observe(100.,3,3)
        self.assertIsNotNone(self.observe(104.,4,4)[0]['signal'])
        self.assertIsNone(self.observe(100.,5,5)[0]['signal'])

    def test_mid_candle_start_waits_for_true_opening(self):
        self.geometry.status('CONECTADO',CANDLE+timedelta(seconds=1))
        snapshot,reason=self.observe(104.,2,1)
        self.assertEqual(reason,'WAITING_FOR_OPEN_OR_HISTORY')
        self.assertIsNone(snapshot['opening'])
        self.store.upsert_bar(MarketBar('AAPL',CANDLE,100,105,99,102,100),provider='ALPACA',feed='iex')
        snapshot,reason=self.observe(104.,62,2)
        self.assertEqual(snapshot['opening'],100)
        self.assertEqual(reason,'EXIT')

    def test_missed_or_earlier_out_of_order_opening_waits_for_official_bar(self):
        self.now=CANDLE+timedelta(seconds=5)
        self.assertIsNone(self.geometry.observe(trade(100.,CANDLE,1),self.now)[0])
        snapshot,reason=self.observe(104.,6,2)
        self.assertIsNone(snapshot['opening'])
        self.assertEqual(reason,'WAITING_FOR_OPEN_OR_HISTORY')
        self.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        self.geometry.missed_openings.clear()
        self.observe(100.,7,3)
        snapshot,reason=self.geometry.observe(trade(99.,CANDLE+timedelta(seconds=6),4),self.now)
        self.assertEqual(reason,'OPENING_OUT_OF_ORDER')
        self.assertIsNone(snapshot['signal'])

    def test_stale_future_duplicates_out_of_order_and_after_close_are_excluded(self):
        self.observe(100.,1,1)
        self.now=CANDLE+timedelta(seconds=2)
        for stamp in (self.now-timedelta(seconds=4),self.now+timedelta(seconds=1)):
            self.assertIsNone(self.geometry.observe(trade(104.,stamp,9),self.now)[0])
        self.assertEqual(self.geometry.observe(trade(100.,CANDLE+timedelta(seconds=1),1),self.now)[1],'DUPLICATE')
        self.observe(104.,3,3)
        self.assertEqual(self.geometry.observe(trade(104.,CANDLE+timedelta(seconds=2),2),self.now)[1],'OUT_OF_ORDER')
        self.now=CANDLE.replace(hour=20)
        self.assertEqual(self.geometry.observe(trade(104.,self.now,4),self.now)[1],'OUTSIDE_SESSION')

    def test_both_bands_are_mandatory_even_on_fast_path(self):
        from bollinger_phone_worker import bands_at_open
        self.observe(100.,1,1)
        state=self.geometry.states['AAPL']
        # Prior window where an upper breakout shifts both
        # bands upward is not volatility expansion on both sides.
        state['history']=[95.4,98.6,103.58,102.09,95.99,95.55,99.08,104.94,95.74,103.34,
                          101.59,104.39,97.51,101.18,102.63,98.48,104.58,101.54,98.19,103.85]
        prior=state['history']
        old_upper,old_lower=bands_at_open(prior[:-1],prior[-1])
        candidate=None
        for price in range(101,125):
            upper,lower=bands_at_open(prior[1:],price)
            if price>upper and not (upper>old_upper and lower<old_lower):
                candidate=price
                break
        self.assertIsNotNone(candidate)
        state['opening']=sum(prior[1:])/19
        self.assertIsNone(self.observe(candidate,2,2)[0]['signal'])

    def test_correction_quarantines_candle_and_is_not_a_new_trade(self):
        self.observe(100.,1,1)
        self.observe(104.,2,2)
        correction={'T':'c','S':'AAPL','oi':2,'ci':3,'cp':110}
        self.assertEqual(self.geometry.observe(correction,self.now)[1],'CORRECTION_QUARANTINE')
        snapshot,reason=self.observe(105.,3,4)
        self.assertIsNone(snapshot['signal'])
        self.assertEqual(reason,'CORRECTION_QUARANTINE')

    def test_missing_previous_closing_minute_blocks_fast_signal(self):
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM minute_bars WHERE timestamp=?',((CANDLE-timedelta(minutes=1)).isoformat(),))
        db.close()
        self.observe(100.,1,1)
        self.assertEqual(self.observe(104.,2,2)[1],'WAITING_FOR_OPEN_OR_HISTORY')

    def test_session_first_candle_can_trigger_before_first_minute_closes(self):
        opening=CANDLE.replace(hour=13,minute=30)
        self.now=opening+timedelta(seconds=1)
        geometry=TickGeometry(self.database,'iex',now=lambda:self.now)
        geometry.status('CONECTADO',opening-timedelta(seconds=1))
        geometry.observe(trade(100.,self.now,1),self.now)
        self.now+=timedelta(seconds=1)
        snapshot,reason=geometry.observe(trade(104.,self.now,2),self.now)
        self.assertEqual(reason,'EXIT')
        self.assertEqual(snapshot['signal']['candle'],opening.isoformat())

    def test_price_condition_filters_odd_lot_reference_and_unknown_sales(self):
        message=trade(104.,self.now)
        self.assertTrue(eligible_trade(message))
        for condition in ('I','P','Z','Q','T','W','UNKNOWN'):
            self.assertFalse(eligible_trade(dict(message,c=[condition])),condition)
        self.assertFalse(eligible_trade(dict(message,p=float('nan'))))
        self.assertFalse(eligible_trade(dict(message,s=0)))


class TickNoticeTests(unittest.TestCase):
    def test_retracted_price_at_send_is_not_notified(self):
        now=CANDLE+timedelta(seconds=2)
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            seed(database)
            geometry=TickGeometry(database,'iex',now=lambda:now)
            geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
            geometry.observe(trade(100.,now-timedelta(seconds=1),1),now-timedelta(seconds=1))
            snapshot,_=geometry.observe(trade(104.,now,2),now)
            repo=TickRepository(database)
            repo.flush({'AAPL':snapshot},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=now)
            support=Mock()
            def retract(*args):
                snapshot['signal']=None
                repo.flush({'AAPL':snapshot},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=now)
            support.submit.side_effect=retract
            sender=Mock()
            with patch('bollinger_phone_worker.enabled',return_value=True), \
                 patch('bollinger_phone_worker.connection',return_value={'chat_id':'test'}):
                self.assertEqual(tick(database,as_of=now,sender=sender,support_worker=support)['sent'],0)
            sender.assert_not_called()

    def test_background_support_uses_exact_tick_time_not_next_minute(self):
        from bollinger_phone_worker import SignalSupportWorker
        now=CANDLE+timedelta(seconds=2)
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            seed(database)
            event={'side':'SUPERIOR','price':104,'candle':CANDLE.isoformat(),
                   'source_timestamp':now.isoformat(),'source_kind':'TRADE',
                   'symbol':'AAPL','provider':'ALPACA','feed':'iex'}
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE bollinger_live_events(event_key TEXT PRIMARY KEY,detected_at TEXT,payload_json TEXT)')
                db.execute('CREATE TABLE bollinger_radar_state(symbol TEXT PRIMARY KEY,source_timestamp TEXT,payload_json TEXT)')
                db.execute('INSERT INTO bollinger_live_events VALUES(?,?,?)',('test',now.isoformat(),json.dumps(event)))
            db.close()
            with patch('bollinger_phone_worker.live_context',return_value={'state':'DESCRIPTIVO'}) as context, \
                 patch('bollinger_pattern_memory.historical_support',return_value={'state':'INSUFFICIENT'}) as history:
                worker=SignalSupportWorker()
                try:
                    worker.submit(database,'test',event)
                    worker.queue.join()
                    self.assertEqual(context.call_args.kwargs['available_at'],now)
                    self.assertEqual(history.call_args.kwargs['available_at'],now)
                finally:
                    worker.close()

    def test_tick_notification_no_minute_wait_dedupe_and_retraction(self):
        now=CANDLE+timedelta(seconds=2)
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            seed(database)
            geometry=TickGeometry(database,'iex',now=lambda:now)
            geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
            geometry.observe(trade(100.,now-timedelta(seconds=1),1),now-timedelta(seconds=1))
            snapshot,_=geometry.observe(trade(104.,now,2),now)
            repo=TickRepository(database)
            repo.flush({'AAPL':snapshot},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=now)
            sender=Mock(return_value={'message_id':1,'date':int(now.timestamp())})
            support=Mock()
            with patch('bollinger_phone_worker.enabled',return_value=True), \
                 patch('bollinger_phone_worker.connection',return_value={'chat_id':'test'}), \
                 patch('bollinger_phone_worker.live_context',side_effect=AssertionError('must be asynchronous')), \
                 patch('manual_trade_links.signal_link',return_value=None):
                self.assertEqual(tick(database,as_of=now,sender=sender,support_worker=support)['sent'],1)
                self.assertEqual(tick(database,as_of=now,sender=sender,support_worker=support)['sent'],0)
                sender.assert_called_once()
                with sqlite3.connect(database) as db:
                    timing=db.execute('SELECT source_ready_at,source_kind FROM bollinger_notice_timing').fetchone()
                db.close()
                self.assertEqual(timing,(now.isoformat(),'TRADE'))
                self.assertEqual(tick(database,as_of=now+timedelta(seconds=4),sender=sender,support_worker=support)['sent'],0)
                # Active ticks own the symbol; an old minute cannot resurrect it.
                snapshot['signal']=None
                repo.flush({'AAPL':snapshot},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=now)
                with patch('bollinger_phone_worker._minute_signal',side_effect=AssertionError('no minute fallback')):
                    self.assertEqual(tick(database,as_of=now,sender=sender,support_worker=support)['sent'],0)

    def test_slow_bar_analysis_does_not_block_trade_reception(self):
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            seed(database)
            worker=RealtimeBollingerWorker(database,'iex',['AAPL'])
            started,release=Event(),Event()
            def slow_analysis(bar):
                started.set()
                release.wait(5)
            try:
                worker.status('CONECTADO')
                worker.bar(MarketBar('AAPL',CANDLE,100,101,99,100,100),slow_analysis)
                self.assertTrue(started.wait(2))
                marker=trade(104.,datetime.now(UTC),999)
                worker.trade(marker)
                worker.queue.join()
                self.assertFalse(worker.failed.is_set())
                self.assertFalse(release.is_set())
                deadline=time.monotonic()+2
                observed=False
                while time.monotonic()<deadline:
                    with worker.repository.connect() as db:
                        observed=db.execute('SELECT COUNT(*) FROM bollinger_tick_audit').fetchone()[0]>0
                    if observed:
                        break
                    time.sleep(.02)
                self.assertTrue(observed,'trade must be recorded while bar analysis is blocked')
            finally:
                release.set()
                worker.close()


if __name__=='__main__':
    unittest.main()
