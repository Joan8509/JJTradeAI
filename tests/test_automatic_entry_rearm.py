"""Repeat only after settled local operations, with a distinct fresh signal."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta,datetime
from unittest import TestCase
from unittest.mock import patch
from tests import test_automatic_entry_queue as fixtures


class AutomaticRearmTests(TestCase):
    def setUp(self):
        self.h=fixtures.AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def arm(self):
        h=self.h;day=datetime.fromisoformat(h.f.state['session'][0]).date().isoformat()
        return h.store.arm('AMZN',2,'MANUAL',day,now=h.f.now-timedelta(seconds=1),
            sessions=[(day,*h.f.state['session'])],repeat=True)

    def closed(self):
        h=self.h;parent=self.arm();h.runner.step()
        h.f.quote(seconds=1);h.f.service.observe()
        review=h.f.service.prepare_close('owner',h.f.code)
        h.f.service.confirm('owner',review['id'])
        h.f.quote(bid=2.1,ask=2.15,seconds=3);h.f.service.observe()
        self.assertEqual(h.f.service.positions(),[])
        self.assertEqual(h.f.service.pending_orders(),[])
        return parent

    def test_repeats_only_when_explicitly_authorized(self):
        h=self.h;h.arm();h.runner.step();h.f.quote(seconds=11);h.f.service.observe()
        self.assertEqual(h.runner.rearm_settled(),0)
        self.assertEqual(len(h.store.plans()),1)

    def test_open_pending_and_pending_close_never_rearm(self):
        h=self.h;self.arm();h.runner.step()
        self.assertEqual(h.runner.rearm_settled(),0)
        h.f.quote(seconds=1);h.f.service.observe()
        self.assertEqual(h.runner.rearm_settled(),0)
        review=h.f.service.prepare_close('owner',h.f.code);h.f.service.confirm('owner',review['id'])
        self.assertEqual(h.runner.rearm_settled(),0)

    def test_closed_trade_preserves_history_and_waits_for_new_candle(self):
        h=self.h;parent=self.closed()
        orders=h.f.engine.ledger.orders();attempts=h.store.read('SELECT * FROM queue_attempts')
        self.assertEqual(h.runner.rearm_settled(),1)
        child=h.store.active()[0]
        self.assertNotEqual(child['id'],parent)
        self.assertEqual((child['quantity'],child['target'],child['max_cost']),(2,'MANUAL','460.00'))
        self.assertEqual(len(h.store.plans()),1)  # Previous result remains in history.
        h.runner.step();self.assertEqual(h.f.engine.ledger.orders(),orders)
        self.assertEqual(h.store.read('SELECT * FROM queue_attempts'),attempts)
        self.assertEqual(h.runner.rearm_settled(),0)
        h.f.quote(seconds=901);h.runner.step()
        self.assertEqual(len(h.store.read('SELECT * FROM queue_attempts')),2)
        self.assertEqual(len([o for o in h.f.engine.ledger.orders() if o['order']['instruction']=='BUY_TO_OPEN']),2)

    def test_cancel_without_fill_requires_new_signal(self):
        h=self.h;self.arm();h.runner.step();h.f.quote(seconds=11);h.f.service.observe()
        self.assertEqual(h.f.engine.ledger.orders()[0]['status'],'CANCELED')
        self.assertEqual(h.runner.rearm_settled(),1)
        h.runner.step();self.assertEqual(len(h.f.engine.ledger.orders()),1)

    def test_pause_after_close_prevents_repeat(self):
        h=self.h;parent=self.closed();h.store.pause(parent)
        self.assertEqual(h.runner.rearm_settled(),0);self.assertEqual(h.store.active(),[])

    def test_pause_parent_after_rearm_pauses_child(self):
        h=self.h;parent=self.closed();h.runner.rearm_settled();h.store.pause(parent)
        self.assertEqual(h.store.active(),[])
        self.assertFalse(any(row['enabled'] for row in h.store.read('SELECT enabled FROM queue_repeat_permissions')))

    def test_delete_after_close_prevents_repeat(self):
        h=self.h;parent=self.closed();h.store.archive(parent,now=h.f.now,ledger_path=h.f.engine.ledger.path)
        self.assertEqual(h.runner.rearm_settled(),0);self.assertEqual(h.store.plans(),[])

    def test_uncertain_never_rearms_even_if_no_order_found(self):
        h=self.h;self.arm()
        with h.store.transaction() as db:db.execute("UPDATE queue_plans SET state='UNCERTAIN'")
        self.assertEqual(h.runner.rearm_settled(),0);self.assertEqual(len(h.store.plans()),1)

    def test_maintenance_shutdown_and_session_end_prevent_repeat(self):
        h=self.h;self.closed()
        with h.store.transaction() as db:db.execute('UPDATE queue_control SET maintenance=1')
        self.assertEqual(h.runner.rearm_settled(),0)
        with h.store.transaction() as db:db.execute('UPDATE queue_control SET maintenance=0')
        h.f.now=datetime.fromisoformat(h.plan()['closes_at'])
        self.assertEqual(h.runner.rearm_settled(),0)
        h.runner.close_entries();self.assertEqual(h.runner.rearm_settled(),0)

    def test_concurrent_settlement_only_creates_one_child(self):
        h=self.h;self.closed()
        with ThreadPoolExecutor(max_workers=2) as pool:counts=list(pool.map(lambda _:h.runner.rearm_settled(),range(2)))
        self.assertEqual(sum(counts),1);self.assertEqual(len(h.store.active()),1)

    def test_range_change_does_not_expand_previous_authorization(self):
        h=self.h;self.closed()
        with patch('automatic_entry_rearm.optimal_option_premium',return_value=('1','9')):
            self.assertEqual(h.runner.rearm_settled(),0)

    def test_repeat_permission_cannot_be_duplicated_by_another_arm(self):
        self.closed()
        with self.assertRaisesRegex(ValueError,'QUEUE_ALREADY_ARMED_OR_UNCERTAIN'):self.arm()

    def test_pause_during_rearm_transaction_wins(self):
        h=self.h;parent=self.closed();original=h.store.can_archive
        def pause(*args,**kwargs):
            settled=original(*args,**kwargs);h.store.pause(parent);return settled
        with patch.object(h.store,'can_archive',side_effect=pause):
            self.assertEqual(h.runner.rearm_settled(),0)
        self.assertEqual(h.store.active(),[])
