"""Thirty seconds from the first opportunity, not from its latest trade."""
from datetime import timedelta,datetime
from unittest import TestCase
from unittest.mock import patch
from tests import test_automatic_entry_queue as fixtures
from tests.test_manual_trade_service import state_fixture
from automatic_entry_queue import QueueStore
from automatic_entry_execution import signal_entry_deadline


class SignalEntryWindowTests(TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.start=self.h.f.now
        self.h.arm();self.plan=self.h.plan()

    def observe(self,seconds):
        now=self.start+timedelta(seconds=seconds)
        state=state_fixture(now)
        state['session']=(self.plan['opens_at'],self.plan['closes_at'])
        return self.h.runner._signal(self.plan,state,now)

    def test_latest_trade_does_not_renew_window_and_exact_thirty_is_expired(self):
        first=self.observe(0)
        self.assertEqual(self.observe(29.999)['first_signal_at'],first['first_signal_at'])
        with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):
            self.observe(30)
        self.assertEqual(self.h.f.engine.ledger.orders(),[])

    def test_retraction_restart_and_new_store_do_not_reset_clock(self):
        first=self.observe(0);now=self.start+timedelta(seconds=20)
        state=state_fixture(now);state['tick']['signal']=None
        with self.assertRaises(Exception):self.h.runner._signal(self.plan,state,now)
        stored=QueueStore(self.h.store.path).first_signal_source(first['key'],
            (self.start+timedelta(seconds=31)).isoformat(),self.start+timedelta(seconds=31))
        self.assertEqual(stored,self.start)
        self.h.runner.first_signal_sources.clear()
        with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_WINDOW_EXPIRED'):self.observe(31)

    def test_expired_signal_does_not_consume_authorization_for_a_new_candle(self):
        self.observe(0)
        with self.assertRaisesRegex(ValueError,'EXPIRED'):self.observe(31)
        later=self.start+timedelta(minutes=15)
        fresh=self.h.runner._signal(self.plan,state_fixture(later),later)
        self.assertEqual(fresh['first_signal_at'],later.isoformat())
        self.assertEqual(len(self.h.store.read('SELECT * FROM queue_signal_windows')),2)
        self.assertEqual(self.h.store.read('SELECT * FROM queue_attempts'),[])

    def test_failed_contract_checks_cannot_buy_at_minute_eleven(self):
        h=self.h
        with patch('automatic_entry_queue.manual_candidates',return_value=(None,None,())):
            h.runner.step()
        self.assertEqual(h.f.engine.ledger.orders(),[])
        h.f.quote(seconds=31);h.runner.step()
        self.assertEqual(h.plan()['reason'],'SIGNAL_ENTRY_WINDOW_EXPIRED')
        h.f.quote(seconds=700);h.runner.step()
        self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),[])

    def test_lookup_crossing_window_cannot_dispatch(self):
        self.observe(0);self.h.f.quote(seconds=29)
        original=self.h.f.market.get_catalog_chain
        def slow(*args,**kwargs):
            result=original(*args,**kwargs)
            self.h.f.quote(seconds=30)
            return result
        with patch.object(self.h.f.market,'get_catalog_chain',side_effect=slow):self.h.runner.step()
        self.assertEqual(self.h.f.engine.ledger.orders(),[])
        self.assertEqual(self.h.plan()['reason'],'SIGNAL_ENTRY_WINDOW_EXPIRED')

    def test_order_dispatched_at_second_twenty_nine_cannot_fill_after_thirty(self):
        self.observe(0);self.h.f.quote(seconds=29);self.h.runner.step()
        key=self.h.plan()['client_key'];order=self.h.f.engine.ledger.order(key)['order']
        self.assertEqual(datetime.fromisoformat(order['entry_deadline']),self.start+timedelta(seconds=30))
        self.assertEqual(order['entry_signal_window_seconds'],30)
        self.h.f.quote(seconds=30);self.h.f.service.observe()
        self.assertEqual(self.h.f.engine.ledger.order(key)['status'],'CANCELED')
        self.assertEqual(self.h.f.engine.ledger.order(key)['filled_quantity'],0)
        self.h.runner.step();self.assertEqual(len(self.h.f.engine.ledger.orders()),1)

    def test_window_does_not_prevent_a_timely_fill(self):
        self.h.runner.step();key=self.h.plan()['client_key']
        self.h.f.quote(seconds=1);self.h.f.service.observe()
        self.assertEqual(self.h.f.engine.ledger.order(key)['status'],'FILLED')

    def test_signal_expiry_cancels_only_unfilled_remainder(self):
        self.observe(0);self.h.f.quote(seconds=25);self.h.runner.step()
        key=self.h.plan()['client_key']
        self.h.f.quote(seconds=26,size=1);self.h.f.service.observe()
        self.assertEqual(self.h.f.engine.ledger.order(key)['filled_quantity'],1)
        self.h.f.quote(seconds=30,size=1);self.h.f.service.observe()
        row=self.h.f.engine.ledger.order(key)
        self.assertEqual(row['status'],'CANCELED');self.assertEqual(row['filled_quantity'],1)
        self.assertEqual(self.h.f.service.positions()[0]['quantity'],1)

    def test_future_clock_is_blocked(self):
        with self.assertRaisesRegex(ValueError,'SIGNAL_ENTRY_CLOCK_INVALID'):
            signal_entry_deadline(self.start+timedelta(seconds=1),self.start)
