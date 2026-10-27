"""Contended isolated SQLite and blocked Telegram; no live providers."""
from contextlib import closing
from datetime import timedelta
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import Mock, patch
import sqlite3,time
from tests.test_automatic_entry_queue import AutomaticQueueTests
from tests.test_telegram_manual_runtime import TelegramRuntimeTests


class NonblockingMetadataTests(TestCase):
    def setUp(self):
        self.h=AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_busy_display_writes_return_without_waiting_for_writer(self):
        h=self.h;identity=h.arm()
        with closing(sqlite3.connect(h.store.path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            started=time.monotonic()
            self.assertFalse(h.store.heartbeat(h.f.now,'READY'))
            self.assertFalse(h.store.waiting(identity,'NO_CURRENT_SIGNAL',h.f.now))
            self.assertLess(time.monotonic()-started,.5)
            writer.rollback()
        self.assertTrue(h.store.waiting(identity,'NO_CURRENT_SIGNAL',h.f.now))
        self.assertEqual(h.plan()['reason'],'NO_CURRENT_SIGNAL')
        self.assertEqual(len(h.store.read("SELECT * FROM queue_decisions WHERE stage='WAITING'")),1)
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_unchanged_reason_needs_no_writer_and_no_duplicate_decision(self):
        h=self.h;identity=h.arm();h.store.waiting(identity,'NO_CURRENT_SIGNAL',h.f.now)
        with closing(sqlite3.connect(h.store.path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            self.assertFalse(h.store.waiting(identity,'NO_CURRENT_SIGNAL',h.f.now))
            writer.rollback()
        self.assertEqual(len(h.store.read("SELECT * FROM queue_decisions WHERE stage='WAITING'")),1)

    def test_heartbeat_throttles_only_same_state_and_reports_changes_immediately(self):
        h=self.h;h.store.heartbeat(h.f.now,'READY')
        h.store.heartbeat(h.f.now+timedelta(milliseconds=100),'READY')
        self.assertEqual(h.store.read('SELECT heartbeat FROM queue_runtime')[0]['heartbeat'],h.f.now.isoformat())
        h.store.heartbeat(h.f.now+timedelta(milliseconds=200),'MONITOR_NOT_READY')
        self.assertEqual(h.store.status(h.f.now+timedelta(milliseconds=200)),'MONITOR_NOT_READY')

    def test_blocked_telegram_does_not_block_real_local_registration_or_fill(self):
        h=self.h;h.arm()
        companion=TelegramRuntimeTests().companion()
        companion.monitor_ready=True;companion.queue_notifier=Mock();companion.notifier=Mock()
        entered=Event();release=Event()
        def slow_send():
            entered.set();release.wait(10);return 0
        companion.queue_notifier.pump.side_effect=slow_send
        companion.notifier.pump.return_value={'accepted':0,'unconfirmed':0,'retry_after_seconds':0}
        thread=Thread(target=companion._notifications,daemon=True);thread.start()
        try:
            self.assertTrue(entered.wait(2))
            h.runner.step()
            self.assertEqual(h.plan()['state'],'SUBMITTED')
            h.f.quote(seconds=1);h.f.service.observe()
            self.assertGreater(h.f.engine.ledger.orders()[0]['filled_quantity'],0)
            self.assertFalse(release.is_set())
        finally:
            companion.stop.set();companion.notice_wake.set();release.set();thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_observation_wakes_execution_notice_worker(self):
        companion=TelegramRuntimeTests().companion()
        def stop(*args):companion.stop.set()
        with patch.object(companion.monitor_wake,'wait',side_effect=stop),patch('telegram_manual_runtime._status'):
            companion._monitor()
        self.assertTrue(companion.notice_wake.is_set())

    def test_notice_wakeup_cannot_bypass_telegram_retry_after(self):
        companion=TelegramRuntimeTests().companion();companion.monitor_ready=True
        companion.queue_notifier=Mock();companion.queue_notifier.pump.return_value=75
        companion.notice_wake.set()
        def stop(*args):companion.stop.set()
        with patch.object(companion.stop,'wait',side_effect=stop) as waiting,patch.object(companion.notice_wake,'wait') as fast:
            companion._notifications()
        waiting.assert_called_once_with(75);fast.assert_not_called()
