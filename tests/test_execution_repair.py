"""Synthetic quotes, temporary SQLite only; no API/Telegram/private profile."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json,sqlite3,tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch
from manual_trade_service import detector_first_source,ManualDataError
from observation_journal import observation_error_code
from tests import test_automatic_entry_queue as queued
from tests import test_position_quote_refresh as owned
from tests.test_manual_trade_service import state_fixture,NOW
from schwab_connection import SchwabError


class DetectorClockRepairTests(TestCase):
    def test_first_exit_survives_delayed_consumer_and_missing_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'market.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript('CREATE TABLE bollinger_tick_audit(received_at TEXT,symbol TEXT,source_timestamp TEXT,reason TEXT,message_json TEXT);'
                    'CREATE INDEX idx_bollinger_tick_audit_time ON bollinger_tick_audit(received_at);')
                candle=NOW.replace(minute=15*(NOW.minute//15),second=0,microsecond=0)
                tick=state_fixture()['tick'];tick['signal']['candle']=candle.isoformat()
                db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',((candle-timedelta(seconds=1)).isoformat(),'AMZN',candle.isoformat(),'READY_NO_EXIT','{}'))
                for offset,side,reason in [(1,'INFERIOR','EXIT'),(2,'SUPERIOR','READY_NO_EXIT'),(3,'SUPERIOR','EXIT'),(59,'SUPERIOR','EXIT')]:
                    stamp=(candle+timedelta(seconds=offset)).isoformat()
                    db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',(stamp,'AMZN',stamp,reason,json.dumps({'_jjtrade':{'geometry':{'side':side}}})))
                db.commit()
                self.assertEqual(detector_first_source(db,path,tick),(candle+timedelta(seconds=3)).isoformat())
                # Retraction/coalescing does not move the first source.
                self.assertEqual(detector_first_source(db,path,tick),(candle+timedelta(seconds=3)).isoformat())
                other=deepcopy(tick);other['symbol']='SPY'
                self.assertIsNone(detector_first_source(db,path,other))

    def test_expired_detector_signal_cannot_buy_when_monitor_finally_ready(self):
        h=queued.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm();h.f.state['detector_first_at']=(h.f.now-timedelta(seconds=59)).isoformat()
        h.runner.step()
        self.assertEqual(h.plan()['reason'],'SIGNAL_ENTRY_WINDOW_EXPIRED')
        self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),[])
        self.assertEqual(h.store.read('SELECT first_source_at FROM queue_signal_windows')[0]['first_source_at'],h.f.state['detector_first_at'])

    def test_persisted_window_can_only_move_earlier_never_later(self):
        h=queued.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        now=h.f.now;store=h.store
        store.first_signal_source('key',now.isoformat(),now)
        earlier=now-timedelta(seconds=59)
        self.assertEqual(store.first_signal_source('key',earlier.isoformat(),now),earlier)
        self.assertEqual(store.first_signal_source('key',now.isoformat(),now),earlier)


class QuoteFailureScopeTests(TestCase):
    def test_invalid_background_catalog_does_not_freeze_owned_position(self):
        f=owned.PositionQuoteRefreshTests();h,client,data=f.fixture()
        client.full_chain.return_value={'private':'invalid response'}
        later=NOW+timedelta(minutes=5)
        with self.assertRaises(ManualDataError) as caught:data.prepare_calendar('SPY','CALL',later)
        self.assertEqual(observation_error_code(caught.exception),'OPTION_RESPONSE_INVALID')
        client.quotes.reset_mock()
        data.get_position_chain('AMZN','CALL',h.code,later)
        client.quotes.assert_called_once()
        self.assertIsNone(data.retry_at)
        with self.assertRaisesRegex(ManualDataError,'COOLDOWN'):data.prepare_calendar('SPY','CALL',later)

    def test_rate_limit_still_blocks_every_scope_until_retry_after(self):
        f=owned.PositionQuoteRefreshTests();h,client,data=f.fixture()
        later=NOW+timedelta(minutes=5)
        client.full_chain.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        with self.assertRaisesRegex(ManualDataError,'RATE_LIMITED'):data.prepare_calendar('SPY','CALL',later)
        client.quotes.reset_mock()
        with self.assertRaisesRegex(ManualDataError,'COOLDOWN'):data.get_position_chain('AMZN','CALL',h.code,later+timedelta(seconds=59))
        client.quotes.assert_not_called()
        data.get_position_chain('AMZN','CALL',h.code,later+timedelta(seconds=60))
        client.quotes.assert_called_once()


class ExitPricingRepairTests(TestCase):
    def fixture(self,target='20'):
        h=queued.AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        h.arm(target=target);h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(h.f.service.positions()[0]['quantity'],2)
        return h

    def test_stop_fills_at_next_lower_bid_with_partial_fills_and_no_duplicate(self):
        h=self.fixture();f=h.f
        f.quote(bid=1.50,ask=1.55,seconds=2,size=1);f.service.observe()
        pending=f.service.pending_orders()[0]
        self.assertEqual(pending['order']['exit_pricing_policy'],'NEXT_VALID_BID_STOP_V1')
        self.assertEqual(pending['filled_quantity'],0)
        f.quote(bid=1.20,ask=1.25,seconds=3,size=1);f.service.observe()
        self.assertEqual(f.service.positions()[0]['quantity'],1)
        self.assertEqual(f.engine.ledger.order(pending['client_key'])['filled_quantity'],1)
        f.service.observe()  # Same quote has no second usable unit.
        self.assertEqual(f.service.positions()[0]['quantity'],1)
        f.quote(bid=1.10,ask=1.15,seconds=4,size=1);f.service.observe()
        self.assertEqual(f.service.positions(),[])
        self.assertEqual(len(f.engine.ledger.orders()),2)
        f.engine.reconcile(f.now)
        self.assertEqual(f.engine.ledger.order(pending['client_key'])['filled_quantity'],2)

    def test_target_keeps_goal_floor_instead_of_higher_trigger_bid(self):
        h=self.fixture();f=h.f
        f.quote(bid=2.50,ask=2.55,seconds=2);f.service.observe()
        pending=f.service.pending_orders()[0]
        self.assertEqual(Decimal(pending['order']['limit']),Decimal('2.4'))
        f.quote(bid=2.39,ask=2.44,seconds=3);f.service.observe()
        self.assertTrue(f.service.positions())
        f.quote(bid=2.40,ask=2.45,seconds=4);f.service.observe()
        self.assertEqual(f.service.positions(),[])
        self.assertEqual(len(f.engine.ledger.orders()),2)

    def test_partial_target_is_cancelled_before_stop_sells_only_remainder(self):
        h=self.fixture();f=h.f
        f.quote(bid=2.50,ask=2.55,seconds=2);f.service.observe()
        target=f.service.pending_orders()[0]['client_key']
        f.quote(bid=2.45,ask=2.50,seconds=3,size=1);f.service.observe()
        self.assertEqual(f.engine.ledger.order(target)['filled_quantity'],1)
        f.quote(bid=1.50,ask=1.55,seconds=4);f.service.observe()
        self.assertEqual(f.engine.ledger.order(target)['status'],'CANCELED')
        stop=f.service.pending_orders()[0]
        self.assertEqual(stop['order']['exit_reason'],'LOSS_LIMIT')
        self.assertEqual(stop['order']['quantity'],1)
        f.quote(bid=1.30,ask=1.35,seconds=5);f.service.observe()
        self.assertEqual(f.service.positions(),[])
        self.assertEqual(len(f.engine.ledger.orders()),3)
        f.engine.reconcile(f.now)

    def test_latch_survives_crash_before_cancel_and_recovery_of_price(self):
        h=self.fixture();f=h.f
        f.quote(bid=2.50,ask=2.55,seconds=2);f.service.observe()
        f.quote(bid=1.50,ask=1.55,seconds=3)
        with patch.object(f.engine.broker,'acknowledge_cancel',side_effect=RuntimeError('simulated interruption')):
            with self.assertRaises(RuntimeError):f.service.observe()
        self.assertEqual(len(f.engine.ledger.orders()),2)
        f.service=f.build()
        f.quote(bid=2.45,ask=2.50,seconds=4);f.service.observe()
        stop=f.service.pending_orders()[0]
        self.assertEqual(stop['order']['exit_reason'],'LOSS_LIMIT')
        f.quote(bid=2.44,ask=2.49,seconds=5);f.service.observe()
        self.assertEqual(f.service.positions(),[])
        self.assertEqual(len(f.engine.ledger.orders()),3)
