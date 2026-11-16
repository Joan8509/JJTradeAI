"""Fault injection after a real-style successful POST; no production I/O."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock,patch
from datetime import timedelta
from tests import test_real_order_ledger as journal
from tests.test_real_order_ledger import Vault,BINDING
from real_order_ledger import RealOrderCoordinator,RealOrderLedger,RealOrderBlocked
from real_submission_receipts import RealSubmissionReceipts
from real_live_storage import RealEncryptedStore


class WindowsPublicationTests(TestCase):
    def test_transient_windows_replace_failure_retries_publication_only(self):
        error=OSError('SYNTHETIC');error.winerror=32
        temporary=Mock();temporary.replace.side_effect=[error,None]
        store=RealEncryptedStore.__new__(RealEncryptedStore);store.path='SYNTHETIC'
        with patch('real_live_storage.time.sleep') as sleep:store._replace_file(temporary)
        self.assertEqual(temporary.replace.call_count,2);sleep.assert_called_once_with(.01)

    def test_unrelated_failure_never_retried_and_sharing_retry_is_bounded(self):
        store=RealEncryptedStore.__new__(RealEncryptedStore);store.path='SYNTHETIC'
        for code,count in ((112,1),(5,7)):
            error=OSError('SYNTHETIC');error.winerror=code
            temporary=Mock();temporary.replace.side_effect=error
            with patch('real_live_storage.time.sleep'),self.assertRaises(OSError):store._replace_file(temporary)
            self.assertEqual(temporary.replace.call_count,count)


class SubmissionRecoveryTests(TestCase):
    def setUp(self):
        self.f=journal.RealOrderJournalTests();self.f.setUp()
        self.vault=Vault();self.receipts=RealSubmissionReceipts(lambda:self.vault)
        self.coordinator=RealOrderCoordinator(self.f.ledger,self.f.gateway,lambda *a:True,receipts=self.receipts)

    def fail_ack(self):
        original=self.f.vault.save
        def save(doc):
            if any(r['state']=='ACKNOWLEDGED' for r in doc['requests'].values()):raise OSError('SYNTHETIC_SHARING')
            original(doc)
        self.f.vault.save=save
        return original

    def test_lost_journal_publish_recovers_exact_receipt_after_restart_without_post(self):
        row=self.f.prepare();original=self.fail_ack()
        with self.assertRaises(OSError):self.coordinator.submit(BINDING,row['id'])
        self.assertEqual(self.f.ledger.requests(BINDING)[0]['state'],'SUBMITTING')
        self.assertEqual(self.receipts.read(BINDING)[0]['broker_id'],'100')
        self.f.vault.save=original
        restarted=RealOrderCoordinator(self.f.ledger,self.f.gateway,lambda *a:True,receipts=self.receipts)
        restarted.recover_receipts(BINDING);restarted.recover_receipts(BINDING)
        row=self.f.ledger.requests(BINDING)[0]
        self.assertEqual((row['state'],row['broker_id']),('ACKNOWLEDGED','100'))
        self.f.gateway.submit.assert_called_once()

    def test_receipt_cannot_bind_changed_request_or_foreign_account(self):
        row=self.f.prepare();original=self.fail_ack()
        with self.assertRaises(OSError):self.coordinator.submit(BINDING,row['id'])
        self.f.vault.save=original
        self.f.vault.data['requests'][row['id']]['quantity']=99
        with self.assertRaisesRegex(RealOrderBlocked,'IDENTITY_MISMATCH'):self.coordinator.recover_receipts(BINDING)
        self.assertIsNone(self.f.ledger.requests(BINDING)[0]['broker_id'])
        self.assertEqual(self.receipts.read('b'*64),[])

    def test_in_memory_receipt_survives_both_local_persistence_failures(self):
        row=self.f.prepare();original=self.fail_ack()
        self.receipts.record=Mock(side_effect=OSError('SYNTHETIC_DISK'))
        with self.assertRaises(OSError):self.coordinator.submit(BINDING,row['id'])
        self.f.vault.save=original;self.coordinator.recover_receipts(BINDING)
        self.assertEqual(self.f.ledger.requests(BINDING)[0]['broker_id'],'100')
        self.f.gateway.submit.assert_called_once()

    def test_uncertain_post_has_no_invented_receipt_and_is_never_retried(self):
        row=self.f.prepare();self.f.gateway.submit.side_effect=TimeoutError('SYNTHETIC')
        self.assertEqual(self.coordinator.submit(BINDING,row['id'])['state'],'UNCERTAIN')
        self.coordinator.recover_receipts(BINDING)
        self.assertEqual(self.receipts.read(BINDING),[])
        self.f.gateway.submit.assert_called_once()

    def test_order_observer_can_recover_receipt_before_submit_returns(self):
        row=self.f.prepare();original=self.receipts.record
        def record(request,broker_id):
            original(request,broker_id);self.coordinator.recover_receipts(BINDING)
        self.receipts.record=record
        result=self.coordinator.submit(BINDING,row['id'])
        self.assertEqual(result['state'],'ACKNOWLEDGED')
        self.f.gateway.submit.assert_called_once()

    def test_recovered_receipt_get_starts_notice_and_twenty_percent_stop(self):
        from tests import test_real_execution_service as cycle
        from tests import test_schwab_execution_snapshot as evidence
        from real_trade_notices import RealTradeNotices
        f=cycle.RealExecutionCycleTests();f.setUp()
        f.coordinator.receipts=self.receipts
        notices_vault=Vault();sender=Mock(return_value={'message_id':123})
        notices=RealTradeNotices(BINDING,f.ledger,store_factory=lambda:notices_vault,
            sender=sender,clock=lambda:f.now);notices.initialize()
        original=f.vault.save
        def save(doc):
            if any(r['state']=='ACKNOWLEDGED' for r in doc['requests'].values()):raise OSError('SYNTHETIC_SHARING')
            original(doc)
        f.vault.save=save
        with self.assertRaises(OSError):f.enter(target='10')
        row=f.ledger.requests(BINDING)[0];f.vault.save=original
        recovered=dict(row,broker_id='100')
        f.responses['100']=evidence.snapshot(recovered,[(2,'1',f.now.isoformat())],'FILLED')
        f.service.observe_orders();notices.step()
        self.assertIn('COMPRA REAL CONFIRMADA',sender.call_args.args[0])
        self.assertEqual(f.ledger.available_to_close(BINDING,row['contract']),2)
        f.bid='.80';f.ask='.82';close=f.service.monitor_positions()[-1]
        self.assertEqual((close['instruction'],close['limit']),('SELL_TO_CLOSE','0.8'))
        self.assertEqual(f.gateway.submit.call_count,2) # one buy, one stop

    def test_recovered_buy_places_profit_limit_without_waiting_for_price_touch(self):
        from tests import test_real_broker_target as target
        f=target.BrokerTargetTests();f.setUp();cycle=f.f
        cycle.coordinator.receipts=self.receipts
        original=cycle.vault.save
        def save(doc):
            if any(r['state']=='ACKNOWLEDGED' for r in doc['requests'].values()):raise OSError('SYNTHETIC_SHARING')
            original(doc)
        cycle.vault.save=save
        with self.assertRaises(OSError):cycle.enter(target='10')
        row=cycle.ledger.requests(BINDING)[0];cycle.vault.save=original
        cycle.broker(dict(row,broker_id='100'),2,'FILLED')
        cycle.service.observe_orders();f.targets.step()
        child=cycle.ledger.requests(BINDING)[-1]
        self.assertEqual((child['instruction'],child['limit'],child['exit_role']),
            ('SELL_TO_CLOSE','1.10','BROKER_TARGET'))
        self.assertEqual(cycle.gateway.submit.call_count,2)
