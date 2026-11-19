"""Prepared policy: act now on first complete geometry, never renew its age."""
from datetime import timedelta,datetime,timezone
from contextlib import closing
from copy import deepcopy
import sqlite3
from unittest import TestCase
from tests import test_bollinger_tick_stream as tick_fixtures
from tests import test_bollinger_breakout_clock as clock_fixtures
from tests.test_bollinger_tick_stream import CANDLE
from bollinger_tick_stream import TickRepository,TickGeometry
from bollinger_breakout_clock import breakout_deadline
from manual_trade_service import detector_first_source


class CompleteStrategyClockTests(TestCase):
    def harness(self):
        h=tick_fixtures.TickGeometryTests();h.setUp();self.addCleanup(h.doCleanups)
        prices=clock_fixtures.BreakoutClockTests().weak_and_strong(h)
        return h,*prices

    def test_first_complete_tick_after_ten_minutes_is_immediate_without_renewing_raw_cross(self):
        h,weak,strong=self.harness();h.observe(weak,2,2)
        tick,reason=h.observe(strong,602,3)
        self.assertEqual(reason,'EXIT')
        self.assertEqual(tick['signal']['first_breakout_at'],(CANDLE+timedelta(seconds=2)).isoformat())
        self.assertEqual(tick['signal']['first_strategy_at'],(CANDLE+timedelta(seconds=602)).isoformat())
        self.assertEqual(breakout_deadline(tick['signal'],h.now),CANDLE+timedelta(seconds=632))

    def test_retraction_and_reactivation_expire_at_exact_thirty_from_complete(self):
        h,weak,strong=self.harness();h.observe(weak,2,2);h.observe(strong,602,3)
        h.observe(100.,610,4)
        tick,reason=h.observe(strong,631.999,5)
        self.assertEqual(reason,'EXIT')
        self.assertEqual(tick['signal']['first_strategy_at'],(CANDLE+timedelta(seconds=602)).isoformat())
        tick,reason=h.observe(strong,632,6)
        self.assertEqual(reason,'STRATEGY_ENTRY_WINDOW_EXPIRED');self.assertIsNone(tick['signal'])

    def test_clock_is_durable_without_raw_audit_and_later_snapshots_cannot_extend_it(self):
        h,weak,strong=self.harness();h.observe(weak,2,2);tick,_=h.observe(strong,602,3)
        repository=TickRepository(h.database)
        repository.flush({'AAPL':tick},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=h.now)
        with closing(sqlite3.connect(h.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM bollinger_tick_audit').fetchone()[0],0)
            first=detector_first_source(db,h.database,tick,cache={})
            self.assertEqual(datetime.fromisoformat(first),CANDLE+timedelta(seconds=602))
        later=deepcopy(tick)
        later['strategy_firsts']['SUPERIOR']=(CANDLE+timedelta(seconds=610)).isoformat()
        later['signal'].update(first_strategy_at=(CANDLE+timedelta(seconds=610)).isoformat(),
                               strategy_deadline=(CANDLE+timedelta(seconds=640)).isoformat())
        later['source_timestamp']=(CANDLE+timedelta(seconds=611)).isoformat()
        repository.flush({'AAPL':later},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=h.now)
        with closing(sqlite3.connect(h.database)) as db:
            self.assertIsNone(detector_first_source(db,h.database,later,cache={}))
            self.assertEqual(datetime.fromisoformat(db.execute('SELECT first_at FROM bollinger_full_strategy_clock').fetchone()[0]),
                             CANDLE+timedelta(seconds=602))

    def test_reader_refuses_uncommitted_or_mismatched_first_complete_clock(self):
        h,weak,strong=self.harness();h.observe(weak,2,2);tick,_=h.observe(strong,602,3)
        with closing(sqlite3.connect(h.database)) as db:
            self.assertIsNone(detector_first_source(db,h.database,tick,cache={}))

    def test_restart_and_memory_reconnect_preserve_first_complete(self):
        h,weak,strong=self.harness();h.observe(weak,2,2);tick,_=h.observe(strong,602,3)
        TickRepository(h.database).flush({'AAPL':tick},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=h.now)
        h.geometry=TickGeometry(h.database,'iex',now=lambda:h.now)
        h.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        h.observe(100.,620,4);tick,reason=h.observe(strong,632,5)
        self.assertIsNone(tick['signal']);self.assertEqual(reason,'STRATEGY_ENTRY_WINDOW_EXPIRED')

    def test_manual_simulation_and_real_deadline_use_complete_not_expired_raw_clock(self):
        from tests.test_manual_trade_service import state_fixture
        from tests.test_schwab_simulation import NOW
        from manual_trade_service import current_manual_signal,ManualDataError
        from schwab_simulation import validated_signal,DataControls
        from real_trade_preparation import RealPreparationSession
        now=NOW+timedelta(seconds=40);state=state_fixture(now)
        first=NOW.replace(second=1)
        state['detector_first_at']=now.isoformat()
        state['tick']['signal'].update(first_breakout_at=first.isoformat(),
            breakout_deadline=(first+timedelta(seconds=30)).isoformat(),first_strategy_at=now.isoformat(),
            strategy_deadline=(now+timedelta(seconds=30)).isoformat())
        self.assertEqual(current_manual_signal(state,'AMZN',now)['signal']['side'],'SUPERIOR')
        controls=DataControls(True,True,True,NOW.replace(hour=13,minute=30,second=0),NOW.replace(hour=20,minute=0,second=0))
        self.assertIsNotNone(validated_signal(state['tick'],state['runtime'],controls,now))
        # REAL uses the same first-source plus complete-deadline minimum.
        from tests.test_real_trade_preparation import RealPreparationTests
        real=RealPreparationTests();real.setUp();self.addCleanup(real.doCleanups)
        geometry=real.state['tick']['geometry']
        real.h.f.now+=timedelta(seconds=40)
        real.state=state_fixture(real.h.f.now)
        real.state['tick']['geometry']=geometry
        real.state['detector_first_at']=real.h.f.now.isoformat()
        real.state['tick']['signal'].update(first_breakout_at=(real.h.f.now-timedelta(seconds=40)).isoformat(),
            breakout_deadline=(real.h.f.now-timedelta(seconds=10)).isoformat(),
            first_strategy_at=real.h.f.now.isoformat(),strategy_deadline=(real.h.f.now+timedelta(seconds=30)).isoformat())
        _,_,deadline=real.service._signal('AMZN')
        self.assertEqual(deadline,real.h.f.now+timedelta(seconds=30))

    def test_deadline_shape_missing_fields_future_and_renewal_are_rejected(self):
        h,weak,strong=self.harness();h.observe(weak,2,2);tick,_=h.observe(strong,602,3)
        signal=tick['signal'];now=h.now
        for field in ('first_strategy_at','strategy_deadline'):
            bad=deepcopy(signal);bad.pop(field)
            with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):breakout_deadline(bad,now)
        bad=deepcopy(signal);bad['strategy_deadline']=(now+timedelta(seconds=31)).isoformat()
        with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):breakout_deadline(bad,now)
        with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):breakout_deadline(signal,now-timedelta(seconds=1))

    def test_simulation_queue_authorizes_from_complete_clock_not_old_cross(self):
        from tests import test_automatic_entry_queue as queue_fixtures
        from tests.test_manual_trade_service import state_fixture
        from automatic_entry_execution import signal_entry_deadline
        h=queue_fixtures.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm();plan=h.plan();now=h.f.now+timedelta(seconds=40)
        state=state_fixture(now);state['session']=(plan['opens_at'],plan['closes_at'])
        state['detector_first_at']=now.isoformat()
        crossing=h.f.now
        state['tick']['signal'].update(first_breakout_at=crossing.isoformat(),
            breakout_deadline=(crossing+timedelta(seconds=30)).isoformat(),
            first_strategy_at=now.isoformat(),strategy_deadline=(now+timedelta(seconds=30)).isoformat())
        signal=h.runner._signal(plan,state,now)
        self.assertEqual(datetime.fromisoformat(signal['first_signal_at']),now)
        self.assertEqual(signal_entry_deadline(datetime.fromisoformat(signal['first_signal_at']),now),now+timedelta(seconds=30))
        self.assertEqual(datetime.fromisoformat(signal['signal_deadline']),now+timedelta(seconds=30))

    def test_gap_and_subthreshold_geometry_never_start_complete_clock(self):
        h,weak,strong=self.harness();tick,_=h.observe(weak,2,2)
        self.assertEqual(tick['strategy_firsts'],{})
        h.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        h.observe(104.,1,101);tick,_=h.observe(110.,602,102)
        self.assertIsNone(tick['signal']);self.assertEqual(tick['strategy_firsts'],{})
