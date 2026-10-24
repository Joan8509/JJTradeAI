"""Real temporary queue/engine: evidence and retry behavior, no live services."""
from datetime import timedelta
import unittest
from unittest.mock import patch
from tests.test_automatic_entry_queue import AutomaticQueueTests
from queue_entry_diagnostics import check_caption


class EntryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.h=AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def test_eligible_signal_buys_without_telegram_and_keeps_evidence(self):
        h=self.h;h.runner.service=None;h.arm();h.runner.step()
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        check=h.store.last_catalog_check(h.plan()['id'])
        self.assertGreater(check['details']['eligible'],0)
        self.assertEqual(check['details']['side'],'CALL')
        self.assertIn('Es la última revisión guardada',check_caption(check))
        h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.orders()[0]['filled_quantity'],2)

    def test_waiting_eligibility_recovers_automatically_without_new_notice(self):
        h=self.h;h.arm();quote=h.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        quote.update(bid=3,ask=3.01);h.runner.step()
        self.assertEqual(h.plan()['state'],'ARMED');self.assertEqual(h.f.engine.ledger.orders(),[])
        self.assertEqual(h.store.last_catalog_check(h.plan()['id'])['details']['eligible'],0)
        h.f.quote(seconds=6);h.runner.step()  # Same live EXIT, new actual quotes.
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(len(h.f.engine.ledger.orders()),1)
        self.assertGreater(h.store.last_catalog_check(h.plan()['id'])['details']['eligible'],0)

    def test_eight_cent_spread_allows_queue_purchase_but_overage_waits(self):
        h=self.h;h.arm()
        quote=h.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        quote.update(bid=1.919999,ask=2.00);h.runner.step()
        self.assertEqual(h.plan()['state'],'ARMED')
        self.assertEqual(h.f.engine.ledger.orders(),[])
        h.f.quote(seconds=6)
        quote.update(bid=1.92,ask=2.00);h.runner.step()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
        self.assertEqual(len(h.f.engine.ledger.orders()),1)

    def test_reason_transitions_are_retained_instead_of_overwritten(self):
        h=self.h;identity=h.arm()
        for reason in ('NO_CURRENT_SIGNAL','NO_CURRENT_SIGNAL','TRADE_NOT_CURRENT','NO_CURRENT_SIGNAL'):
            h.store.waiting(identity,reason,h.f.now)
        rows=h.store.read("SELECT reason FROM queue_decisions WHERE stage='WAITING' ORDER BY id")
        self.assertEqual([r['reason'] for r in rows],['NO_CURRENT_SIGNAL','TRADE_NOT_CURRENT','NO_CURRENT_SIGNAL'])

    def test_provider_failure_is_safe_and_timed_without_private_error_text(self):
        h=self.h;h.arm()
        with patch.object(h.f.market,'get_catalog_chain',side_effect=RuntimeError('SECRET_TOKEN')):
            h.runner.step()
        rows=h.store.read('SELECT * FROM queue_decisions ORDER BY id')
        self.assertNotIn('SECRET_TOKEN',str(rows));self.assertTrue(any(r['reason']=='CHECK_REQUIRED' for r in rows))
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_slow_catalog_is_audited_but_cannot_dispatch_stale_signal(self):
        h=self.h;h.arm();original=h.f.market.get_catalog_chain
        def slow(*args):
            value=original(*args);h.f.now+=timedelta(seconds=4);return value
        with patch.object(h.f.market,'get_catalog_chain',side_effect=slow):h.runner.step()
        self.assertIsNotNone(h.store.last_catalog_check(h.plan()['id']))
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_optional_catalog_diagnostic_failure_does_not_block_valid_entry(self):
        h=self.h;h.arm()
        with patch('queue_entry_diagnostics.catalog_check',side_effect=ValueError('synthetic')):h.runner.step()
        self.assertEqual(h.plan()['state'],'SUBMITTED')

    def test_maintenance_fences_new_entries_and_honors_user_pause(self):
        h=self.h;identity=h.arm()
        with h.store.transaction() as db:
            db.execute('UPDATE queue_control SET maintenance=1 WHERE id=1')
            db.execute("UPDATE queue_plans SET state='PAUSED',reason='MAINTENANCE' WHERE id=?",(identity,))
        h.runner.step();self.assertEqual(h.f.engine.ledger.orders(),[])
        with self.assertRaisesRegex(ValueError,'QUEUE_MAINTENANCE'):h.arm()
        h.store.pause(identity)
        self.assertEqual(h.plan()['reason'],'PAUSED_BY_USER')

    def test_final_direct_quote_rejection_replaces_earlier_catalog_success(self):
        h=self.h;direct=h.f.client.quotes.side_effect
        def changed(symbols,now):
            result=direct(symbols,now);result[symbols[1]]['quote'].update(bidPrice=2.35,askPrice=2.4)
            return result
        h.f.client.quotes.side_effect=changed
        h.arm();h.runner.step()
        rows=h.store.read("SELECT stage,details_json FROM queue_decisions WHERE stage IN ('CATALOG_RESULT','ENTRY_REFRESH_RESULT') ORDER BY id")
        import json
        self.assertGreater(json.loads(rows[0]['details_json'])['eligible'],0)
        self.assertEqual(json.loads(rows[-1]['details_json'])['eligible'],0)
        self.assertEqual(h.store.last_catalog_check(h.plan()['id'])['details']['nearest_ask'],'2.4')
        self.assertEqual(h.f.engine.ledger.orders(),[])

    def test_optional_evidence_does_not_wait_for_a_writer_lock(self):
        import time
        h=self.h;identity=h.arm()
        with h.store.transaction():
            begun=time.monotonic()
            self.assertFalse(h.store.decision(identity,'SIGNAL_READY',h.f.now))
            self.assertLess(time.monotonic()-begun,.5)
        h.runner.step()
        self.assertEqual(h.plan()['state'],'SUBMITTED')
