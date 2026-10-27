"""Retire expired unexecuted attempts; preserve uncertainty and durable claims."""
from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path
from unittest import TestCase
from automatic_entry_queue import signal_key
from automatic_entry_panel import clear_queue_rows
from schwab_simulation import ExecutionBlocked
from tests import test_automatic_entry_queue as fixtures


class UncertainArchiveTests(TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.identity=self.h.arm();self.key=signal_key(self.h.f.state['tick'])
        self.now=datetime.fromisoformat(self.h.plan()['closes_at'])+timedelta(minutes=2)

    def uncertain(self):
        with self.h.store.transaction() as db:
            db.execute("UPDATE queue_plans SET state='UNCERTAIN',reason='RECONCILIATION_REQUIRED',client_key=NULL WHERE id=?",(self.identity,))
            db.execute("INSERT OR REPLACE INTO queue_attempts(signal_key,plan_id,state,claimed_at,client_key,notice_state) VALUES(?,?,'UNCERTAIN',?,NULL,'WAITING')",
                (self.key,self.identity,self.h.f.now.isoformat()))

    def retire(self,**kwargs):
        self.h.store.archive_unexecuted_uncertain(self.identity,now=kwargs.pop('now',self.now),
            ledger_path=kwargs.pop('ledger_path',self.h.f.engine.ledger.path),
            broker_path=kwargs.pop('broker_path',self.h.f.engine.broker.path),**kwargs)

    def test_absent_from_both_local_books_can_hide_without_clearing_claim(self):
        self.uncertain();before=self.h.store.read('SELECT * FROM queue_plans');attempts=self.h.store.read('SELECT * FROM queue_attempts')
        ledger=self.h.f.engine.ledger.path.read_bytes();broker=self.h.f.engine.broker.path.read_bytes()
        self.retire();self.retire()
        self.assertEqual(self.h.store.plans(),[])
        self.assertEqual(self.h.store.read('SELECT * FROM queue_plans'),before)
        self.assertEqual(self.h.store.read('SELECT * FROM queue_attempts'),attempts)
        self.assertEqual(self.h.store.read('SELECT previous_state FROM queue_archives')[0]['previous_state'],'UNCERTAIN')
        self.assertEqual(self.h.f.engine.ledger.path.read_bytes(),ledger)
        self.assertEqual(self.h.f.engine.broker.path.read_bytes(),broker)
        self.h.runner.step();self.assertEqual(self.h.f.engine.ledger.orders(),[])
        with self.assertRaisesRegex(ValueError,'UNCERTAIN'):self.h.arm()

    def test_clear_all_reviews_expired_uncertain_but_keeps_it_durable(self):
        self.uncertain()
        removed,kept=clear_queue_rows(self.h.store,now=self.now,ledger_path=self.h.f.engine.ledger.path)
        self.assertEqual((removed,kept),(1,0))
        self.assertEqual(self.h.store.read('SELECT state FROM queue_attempts')[0]['state'],'UNCERTAIN')

    def test_ongoing_session_and_recent_claim_are_not_hidden(self):
        self.uncertain()
        with self.assertRaises(ExecutionBlocked):self.retire(now=self.h.f.now)
        with self.h.store.transaction() as db:
            db.execute('UPDATE queue_attempts SET claimed_at=?',((self.now-timedelta(seconds=10)).isoformat(),))
        with self.assertRaises(ExecutionBlocked):self.retire()
        self.assertEqual(len(self.h.store.plans()),1)

    def test_any_ledger_order_for_key_blocks_retirement(self):
        self.h.runner.step();self.uncertain()
        with self.assertRaises(ExecutionBlocked):self.retire()
        self.assertEqual(len(self.h.store.plans()),1)

    def test_broker_only_order_blocks_even_when_ledger_is_empty(self):
        self.h.runner.step();self.uncertain()
        with self.h.f.engine.ledger.transaction() as db:db.execute('DELETE FROM simulated_orders')
        self.assertEqual(self.h.f.engine.ledger.orders(),[])
        with self.assertRaises(ExecutionBlocked):self.retire()
        self.assertEqual(len(self.h.store.plans()),1)

    def test_known_client_key_or_notice_claim_stays_visible(self):
        self.uncertain()
        with self.h.store.transaction() as db:db.execute("UPDATE queue_attempts SET notice_state='CLAIMED'")
        with self.assertRaises(ExecutionBlocked):self.retire()
        with self.h.store.transaction() as db:
            db.execute("UPDATE queue_attempts SET notice_state='WAITING'")
            db.execute("UPDATE queue_plans SET client_key='known'")
        with self.assertRaises(ExecutionBlocked):self.retire()

    def test_missing_foreign_or_same_database_never_passes(self):
        self.uncertain();missing=self.h.f.root/'missing.db'
        for path in (missing,self.h.store.path,self.h.f.engine.ledger.path):
            with self.subTest(path=path),self.assertRaises(ExecutionBlocked):self.retire(broker_path=path)
        self.assertFalse(missing.exists())
        with self.assertRaises(ExecutionBlocked):self.retire(ledger_path=self.h.f.engine.broker.path)
        self.assertEqual(self.h.store.read('SELECT * FROM queue_archives'),[])

    def test_other_open_position_in_same_company_blocks_even_with_different_key(self):
        self.h.runner.step();self.h.f.quote(seconds=1);self.h.f.service.observe();self.uncertain()
        with self.h.store.transaction() as db:
            db.execute("UPDATE queue_attempts SET signal_key=?",('f'*64,))
        with self.assertRaises(ExecutionBlocked):self.retire()
        self.assertEqual(len(self.h.store.plans()),1)

    def test_unreconciled_ledger_does_not_prove_absence(self):
        self.uncertain()
        with self.h.f.engine.ledger.transaction() as db:
            db.execute("UPDATE simulation_settings SET value='1' WHERE key='reconciliation_blocked'")
        with self.assertRaises(ExecutionBlocked):self.retire()
