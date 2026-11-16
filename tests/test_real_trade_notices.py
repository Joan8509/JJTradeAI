"""Confirmed REAL notices with a memory vault and synthetic Telegram receipts."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock,patch
from tests import test_real_execution_service as cycle
from tests import test_real_order_ledger as journal
from real_trade_notices import RealTradeNotices


class RealNoticeTests(TestCase):
    def test_uncertain_buy_alerts_without_fill_or_repeat_post_or_historical_replay(self):
        row=self.f.enter(target='10')
        # The real fixture exposes its journal through ledger.store_factory.
        store=self.f.ledger.store_factory()
        store.data['requests'][row['id']].update(state='SUBMITTING',broker_id=None)
        self.f.now+=timedelta(seconds=6)
        self.notices.step();self.notices.step()
        self.sender.assert_called_once()
        self.assertIn('CONFIRMACIÓN REAL PENDIENTE',self.sender.call_args.args[0])
        self.assertNotIn('COMPRA REAL CONFIRMADA',self.sender.call_args.args[0])

    def test_real_sender_uses_existing_vps_profile_without_injecting_environment(self):
        profile=dict(TELEGRAM_BOT_TOKEN='SYNTHETIC_TOKEN',TELEGRAM_CHAT_ID='123')
        with patch('vps_private_runtime.load_config',return_value=profile),patch('telegram_alerts.call',
                return_value={'message_id':5}) as send,patch('os.environ',{}) as environment:
            self.assertEqual(RealTradeNotices._send('TEST'),{'message_id':5})
            self.assertEqual(RealTradeNotices.local_readiness(),'LISTO_LOCAL')
            self.assertEqual(dict(environment),{})
        send.assert_called_once_with('SYNTHETIC_TOKEN','sendMessage',chat_id='123',text='TEST')

    def setUp(self):
        self.f=cycle.RealExecutionCycleTests();self.f.setUp()
        self.store=journal.Vault();self.sender=Mock(return_value={'message_id':123})
        self.notices=self.make();self.notices.initialize()

    def make(self):
        return RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:self.store,
            sender=self.sender,clock=lambda:self.f.now)

    def test_order_receipt_never_notifies_until_confirmed_fill_then_restart_deduplicates(self):
        buy=self.f.enter(target='10');self.notices.step();self.sender.assert_not_called()
        from tests.test_schwab_execution_snapshot import snapshot
        self.f.responses[buy['broker_id']]=snapshot(buy,[(1,'1',self.f.now.isoformat()),
            (1,'1',self.f.now.isoformat())],'FILLED')
        self.f.service.poll();self.notices.step()
        self.sender.assert_called_once()
        text=self.sender.call_args.args[0]
        self.assertIn('COMPRA REAL CONFIRMADA',text);self.assertIn('Objetivo 10%',text)
        self.assertIn('Stop 20%',text);self.assertEqual(len(text.splitlines()),4)
        restarted=self.make();restarted.initialize();restarted.step()
        self.sender.assert_called_once()

    def test_old_trades_are_fenced_once_but_restart_does_not_hide_a_new_fill(self):
        self.f.own();self.f.now+=timedelta(seconds=1)
        other=journal.Vault()
        notices=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:other,
            sender=self.sender,clock=lambda:self.f.now)
        notices.initialize();notices.step();self.sender.assert_not_called()
        self.assertEqual(notices.status()['counts'],{'HISTORICAL_NOT_SENT':1})
        self.f.bid='1.2';self.f.ask='1.22';sale=self.f.service.poll()[-1]
        self.f.broker(sale,2,'FILLED','1.2');self.f.service.poll()
        restarted=RealTradeNotices(journal.BINDING,self.f.ledger,store_factory=lambda:other,
            sender=self.sender,clock=lambda:self.f.now+timedelta(seconds=5))
        restarted.initialize();restarted.step()
        self.sender.assert_called_once();self.assertIn('VENTA REAL CONFIRMADA',self.sender.call_args.args[0])

    def test_timeout_or_claimed_delivery_is_never_sent_twice(self):
        self.f.own();self.sender.side_effect=TimeoutError('PRIVATE_TRANSPORT_BODY')
        self.notices.step();self.assertEqual(self.sender.call_count,1)
        self.assertEqual(self.notices.status()['counts'],{'DELIVERY_UNCONFIRMED':1})
        restarted=self.make();restarted.initialize();restarted.step()
        self.assertEqual(self.sender.call_count,1)
        self.assertNotIn('PRIVATE_TRANSPORT_BODY',str(self.store.data))

    def test_partial_fill_updates_notify_only_new_cumulative_execution(self):
        buy=self.f.enter(target='10');self.f.broker(buy,1,'WORKING');self.f.service.poll()
        self.notices.step();self.notices.step();self.assertEqual(self.sender.call_count,1)
        from tests.test_schwab_execution_snapshot import snapshot
        self.f.responses[buy['broker_id']]=snapshot(buy,[(1,'1',self.f.now.isoformat()),
            (1,'1',self.f.now.isoformat())],'FILLED')
        self.f.service.poll();self.notices.step()
        self.assertEqual(self.sender.call_count,2)
        self.assertIn('2 contratos',self.sender.call_args.args[0])

    def test_simulation_and_other_account_never_read_or_sent(self):
        ledger=Mock();ledger.requests.return_value=[]
        notices=RealTradeNotices(journal.BINDING,ledger,store_factory=lambda:self.store,sender=self.sender,clock=lambda:self.f.now)
        notices.initialize();notices.step()
        ledger.requests.assert_called_once_with(journal.BINDING);self.sender.assert_not_called()

    def test_explicit_rate_rejection_waits_but_uncertain_deliveries_never_retry(self):
        from telegram_alerts import TelegramError
        self.f.own()
        self.sender.side_effect=[TelegramError('SYNTHETIC',code='HTTP_429',retry_after_seconds=5),{'message_id':124}]
        self.notices.step();self.notices.step()
        self.assertEqual(self.sender.call_count,1)
        self.assertEqual(self.notices.status()['state'],'WAITING_RETRY')
        self.f.now+=timedelta(seconds=5);self.notices.step();self.notices.step()
        self.assertEqual(self.sender.call_count,2)
        self.assertEqual(self.notices.status()['counts'],{'TELEGRAM_ACCEPTED':1})

    def test_claim_saved_before_network_survives_crash_without_duplicate_send(self):
        self.f.own();self.notices.step()
        profile=self.store.data['profiles'][journal.BINDING]
        next(iter(profile['events'].values()))['state']='DELIVERY_CLAIMED'
        self.sender.reset_mock()
        restarted=self.make();restarted.initialize();restarted.step()
        self.sender.assert_not_called()
        self.assertEqual(restarted.status()['state'],'DELIVERY_REQUIRES_REVIEW')

    def test_rate_limited_partial_notice_survives_later_full_fill_and_restart(self):
        from telegram_alerts import TelegramError
        buy=self.f.enter(target='10');self.f.broker(buy,1,'WORKING');self.f.service.poll()
        self.sender.side_effect=[TelegramError('SYNTHETIC',code='HTTP_429',retry_after_seconds=5),
            {'message_id':124},{'message_id':125}]
        self.notices.step()
        from tests.test_schwab_execution_snapshot import snapshot
        self.f.responses[buy['broker_id']]=snapshot(buy,[(1,'1',self.f.now.isoformat()),
            (1,'1',self.f.now.isoformat())],'FILLED')
        self.f.service.poll()
        restarted=self.make();restarted.initialize();restarted.step()
        self.f.now+=timedelta(seconds=5);restarted.step();restarted.step()
        self.assertEqual(self.sender.call_count,3)
        self.assertEqual(restarted.status()['counts'],{'TELEGRAM_ACCEPTED':2})

    def test_obsolete_rate_limited_target_message_is_retired_without_sending(self):
        from telegram_alerts import TelegramError
        self.f.own();self.notices.step();self.sender.reset_mock()
        parent=self.f.ledger.requests(journal.BINDING)[0]
        self.notices.target_status_provider=lambda:{parent['contract']:dict(error=True,
            parent_id=parent['id'],checked_at=self.f.now.isoformat())}
        self.sender.side_effect=TelegramError('SYNTHETIC',code='HTTP_429',retry_after_seconds=5)
        self.notices.step();self.notices.target_status_provider=lambda:{}
        self.f.now+=timedelta(seconds=5);self.notices.step()
        self.assertEqual(self.sender.call_count,1)
        self.assertEqual(self.notices.status()['state'],'CURRENT')
        self.assertEqual(self.notices.status()['counts']['SUPERSEDED_NOT_SENT'],1)

    def test_manual_close_in_app_is_labeled_as_requested_by_user(self):
        buy=self.f.own();self.notices.step()
        self.f.bid='1.01';self.f.ask='1.03'
        sale=self.f.service.close_manually(buy['id'])
        self.f.broker(sale,2,'FILLED','1.01');self.f.service.poll();self.notices.step()
        text=self.sender.call_args.args[0]
        self.assertIn('VENTA REAL CONFIRMADA',text)
        self.assertIn('Cierre solicitado en la app',text)
