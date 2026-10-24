"""Bulk UI removal uses real isolated queue/ledger, never the active databases."""
import unittest
from unittest.mock import patch
from automatic_entry_panel import clear_queue_rows
from tests.test_automatic_entry_queue import AutomaticQueueTests


class QueueClearTests(unittest.TestCase):
    def setUp(self):
        self.h = AutomaticQueueTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def clear(self):
        return clear_queue_rows(self.h.store, now=self.h.f.now,
                                ledger_path=self.h.f.engine.ledger.path)

    def test_queued_paused_removed_without_orders_and_idempotent(self):
        self.h.arm()
        self.assertEqual(self.clear(), (1, 0))
        self.h.arm(); self.h.store.pause()
        self.assertEqual(self.clear(), (1, 0))
        self.assertEqual(self.clear(), (0, 0))
        self.h.runner.step()
        self.assertEqual(self.h.f.engine.ledger.orders(), [])
        self.assertEqual(len(self.h.store.read('SELECT * FROM queue_plans')), 2)

    def test_pending_and_open_preserved_then_closed_archived_with_history(self):
        self.h.arm(); self.h.runner.step()
        self.assertEqual(self.clear(), (0, 1))
        self.h.f.quote(seconds=1); self.h.f.service.observe()
        self.assertEqual(self.clear(), (0, 1))
        review = self.h.f.service.prepare_close('owner', self.h.f.code)
        self.h.f.service.confirm('owner', review['id'])
        self.assertEqual(self.clear(), (0, 1))  # pending sale
        self.h.f.quote(bid=2.7, ask=2.75, seconds=4); self.h.f.service.observe()
        path = self.h.f.engine.ledger.path
        before = path.read_bytes()
        orders = self.h.f.engine.ledger.orders()
        attempts = self.h.store.read('SELECT * FROM queue_attempts')
        self.assertEqual(self.clear(), (1, 0))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.h.f.engine.ledger.orders(), orders)
        self.assertEqual(self.h.store.read('SELECT * FROM queue_attempts'), attempts)
        self.assertEqual(self.h.store.plans(), [])

    def test_button_does_not_clear_until_clicked(self):
        from streamlit.testing.v1 import AppTest
        self.h.arm()
        with patch('automatic_entry_panel.queue_store', return_value=self.h.store):
            app = AppTest.from_string('from automatic_entry_panel import queue_store, render_queue_status\nrender_queue_status(queue_store())').run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(self.h.store.plans()), 1)
            app.button(key='auto_queue_clear_all').click().run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(self.h.store.plans(), [])
            self.assertEqual(self.h.f.engine.ledger.orders(), [])


if __name__ == '__main__':
    unittest.main()
