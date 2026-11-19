from datetime import datetime,timedelta,timezone
from unittest import TestCase
from bollinger_breakout_clock import observe_breakout,breakout_deadline
from bollinger_tick_stream import TickGeometry,TickRepository
from tests import test_bollinger_tick_stream as fixtures
from tests.test_bollinger_tick_stream import CANDLE,trade


class BreakoutClockTests(TestCase):
    def test_first_exit_is_aged_before_full_strategy_and_does_not_renew(self):
        firsts={};start=datetime(2026,11,6,20,tzinfo=timezone.utc)
        self.assertIsNone(observe_breakout(firsts,100,103,97,start))
        self.assertTrue(observe_breakout(firsts,104,103,97,start)['current'])
        self.assertIsNone(observe_breakout(firsts,100,103,97,start+timedelta(seconds=20)))
        self.assertFalse(observe_breakout(firsts,105,104,96,start+timedelta(seconds=30))['current'])
        self.assertEqual(firsts['SUPERIOR'],start.isoformat())
        self.assertTrue(observe_breakout(firsts,95,104,96,start+timedelta(seconds=40))['current'])

    def test_downstream_rejects_deadline_extension_future_and_exact_thirty(self):
        start=datetime(2026,11,6,20,tzinfo=timezone.utc)
        s=dict(candle=start.isoformat(),first_breakout_at=start.isoformat(),breakout_deadline=(start+timedelta(seconds=30)).isoformat())
        self.assertEqual(breakout_deadline(s,start+timedelta(seconds=29.999)),start+timedelta(seconds=30))
        for now,bad in ((start+timedelta(seconds=30),s),(start-timedelta(seconds=1),s),
                        (start,dict(s,breakout_deadline=(start+timedelta(seconds=31)).isoformat()))):
            with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):breakout_deadline(bad,now)

    def test_unknown_first_exit_after_reconnection_cannot_start_new_clock(self):
        now=datetime(2026,11,6,20,tzinfo=timezone.utc);firsts={}
        self.assertIsNone(observe_breakout(firsts,104,103,97,now,allow_new=False))
        self.assertEqual(firsts,{})

    def harness(self):
        h=fixtures.TickGeometryTests();h.setUp();self.addCleanup(h.doCleanups);return h

    def weak_and_strong(self,h):
        from bollinger_phone_worker import bands_at_open
        h.observe(100,1,1);prior=h.geometry.states['AAPL']['history'];pu,pl=bands_at_open(prior[:-1],prior[-1])
        weak=None
        for cents in range(10001,11001):
            price=cents/100;u,l=bands_at_open(prior[1:],price)
            if price>u and u>pu and l<pl:
                expansion=100*min(u-pu,pl-l)/(pu-pl)
                if expansion<3:weak=price
                elif weak is not None:return weak,price
        self.fail('No test prices')

    def test_first_complete_strategy_remains_new_after_earlier_raw_cross(self):
        h=self.harness();weak,strong=self.weak_and_strong(h)
        first,reason=h.observe(weak,2,2);self.assertIsNone(first['signal'])
        late,reason=h.observe(strong,33,3)
        self.assertEqual(reason,'EXIT');self.assertIsNotNone(late['signal'])
        self.assertEqual(late['signal']['first_strategy_at'],(CANDLE+timedelta(seconds=33)).isoformat())
        self.assertEqual(late['breakout_firsts']['SUPERIOR'],(CANDLE+timedelta(seconds=2)).isoformat())

    def test_early_three_percent_remains_immediate_and_survives_retraction(self):
        h=self.harness();weak,strong=self.weak_and_strong(h)
        h.observe(weak,2,2);early,reason=h.observe(strong,3,3)
        self.assertEqual(reason,'EXIT');self.assertEqual(early['signal']['first_breakout_at'],(CANDLE+timedelta(seconds=2)).isoformat())
        h.observe(100,20,4);late,reason=h.observe(strong,33,5)
        self.assertEqual(reason,'STRATEGY_ENTRY_WINDOW_EXPIRED')

    def test_async_persist_and_process_recreation_keep_original_clock(self):
        h=self.harness();weak,strong=self.weak_and_strong(h)
        h.observe(weak,2,2);s,_=h.observe(strong,3,3)
        repo=TickRepository(h.database);repo.flush({'AAPL':s},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=h.now)
        s['breakout_firsts']['SUPERIOR']=(CANDLE+timedelta(seconds=20)).isoformat()
        repo.flush({'AAPL':s},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=h.now)
        h.geometry=TickGeometry(h.database,'iex',now=lambda:h.now)
        h.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        h.observe(100,39,4);s,reason=h.observe(strong,40,5)
        self.assertEqual(reason,'STRATEGY_ENTRY_WINDOW_EXPIRED')
        self.assertEqual(s['breakout_firsts']['SUPERIOR'],(CANDLE+timedelta(seconds=2)).isoformat())

    def test_reconnect_before_publisher_flush_does_not_renew_clock(self):
        h=self.harness();weak,strong=self.weak_and_strong(h)
        h.observe(weak,2,2);h.geometry.status('CONECTADO',CANDLE-timedelta(seconds=1))
        h.observe(100,39,4);s,reason=h.observe(strong,40,5)
        self.assertEqual(reason,'EXIT')
        self.assertEqual(s['signal']['first_strategy_at'],(CANDLE+timedelta(seconds=40)).isoformat())

    def test_simulation_and_shared_real_reader_reject_fresh_tick_with_old_breakout(self):
        from tests.test_manual_trade_service import state_fixture
        from tests.test_schwab_simulation import NOW
        from manual_trade_service import current_manual_signal,ManualDataError
        from schwab_simulation import validated_signal,DataControls,ExecutionBlocked
        now=NOW+timedelta(seconds=40);state=state_fixture(now)
        first=NOW.replace(second=1)
        state['tick']['signal'].update(first_breakout_at=first.isoformat(),
            breakout_deadline=(first+timedelta(seconds=30)).isoformat())
        with self.assertRaisesRegex(ManualDataError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):
            current_manual_signal(state,'AMZN',now)
        controls=DataControls(True,True,True,NOW.replace(hour=13,minute=30,second=0),NOW.replace(hour=20,minute=0,second=0))
        with self.assertRaisesRegex(ExecutionBlocked,'SIGNAL_ENTRY_WINDOW_EXPIRED'):
            validated_signal(state['tick'],state['runtime'],controls,now)
