"""Automatic queue: real local engine/temporary databases, synthetic quotes only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import json
import sqlite3
import unittest

from automatic_entry_queue import QueueStore, QueueRunner, QueueNotifier, official_sessions
from manual_trade_service import ManualDataError
from schwab_simulation import ManualPracticePolicy, ExecutionBlocked
from tests import test_manual_execution as manual_fixture
from telegram_manual import TelegramManualService, TelegramManualStore
from tests.test_telegram_manual import signed, TOKEN, OWNER


class AutomaticQueueTests(unittest.TestCase):
    def setUp(self):
        self.f = manual_fixture.ManualExecutionTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.engine.policy = ManualPracticePolicy()
        self.f.market.increments = {}; self.f.market.fee_per_contract = None
        self.f.market.direct_quotes = True
        def direct_quote(symbols, now):
            q=next(q for mapping in ('callExpDateMap','putExpDateMap') for strikes in self.f.payload[mapping].values()
                for items in strikes.values() for q in items if q['symbol']==symbols[1])
            return {'AMZN':dict(symbol='AMZN',assetMainType='EQUITY',realtime=True,
                quote=dict(lastPrice=104.,quoteTime=int(now.timestamp()*1000),securityStatus='Normal')),
                q['symbol']:dict(symbol=q['symbol'],assetMainType='OPTION',realtime=True,
                    reference=dict(underlying='AMZN',contractType='C' if q['putCall']=='CALL' else 'P',strikePrice=q['strikePrice'],expirationYear=2026,
                        expirationMonth=10,expirationDay=23,multiplier=100.,deliverables='100 AMZN'),
                    quote=dict(bidPrice=q['bid'],askPrice=q['ask'],bidSize=q['bidSize'],askSize=q['askSize'],
                        quoteTime=q['quoteTimeInLong'],securityStatus='Normal'))}
        self.f.client.quotes.side_effect=direct_quote
        original_quote=self.f.quote
        def advance(**kwargs):
            original_quote(**kwargs)
            self.f.payload['underlying']['quoteTime']=int(self.f.now.timestamp()*1000)
            self.f.market.catalog_cache.clear()
        self.f.quote=advance
        self.store = QueueStore(self.f.root/'queue.db')
        self.service = TelegramManualService(self.f.service, TelegramManualStore(self.f.root/'telegram.db'),
            token=TOKEN, user_id=OWNER, base_url='https://jj.example/telegram/')
        self.ready = True
        self.runner = self.build()

    def build(self):
        return QueueRunner(self.f.service, self.store, ready=lambda:self.ready, service=self.service)

    def arm(self, quantity=2, target='35', baseline=None):
        session = (self.f.now.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat(), *self.f.state['session'])
        return self.store.arm('AMZN', quantity, target, session[0], now=self.f.now-timedelta(seconds=1),
            sessions=[session], baseline=baseline)

    def plan(self):
        return self.store.plans()[0]

    def test_empty_queue_never_touches_market_or_orders(self):
        self.runner.step()
        self.f.client.full_chain.assert_not_called()
        self.assertEqual(self.f.engine.ledger.orders(), [])
        self.assertEqual(self.store.status(self.f.now), 'READY')

    def test_arm_persists_quantity_target_and_cap_but_no_dispatch(self):
        self.arm(); p = QueueStore(self.store.path).plans()[0]
        self.assertEqual((p['quantity'],p['target'],p['state']), (2,'35','ARMED'))
        self.assertEqual(p['max_cost'],'460.00')
        self.assertEqual(self.f.engine.ledger.orders(), [])
        with self.assertRaisesRegex(ValueError,'ALREADY_ARMED'):
            self.arm()

    def test_invalid_quantity_target_symbol_range_and_session_rejected(self):
        for qty,target in [(None,'35'),(True,'35'),(0,'35'),(1,None),(1,'15')]:
            with self.subTest(qty=qty,target=target), self.assertRaises((ValueError,TypeError)):
                self.arm(qty,target)
        session = (self.f.now.date().isoformat(), *self.f.state['session'])
        with self.assertRaises(ValueError):
            self.store.arm('SPCX',1,'10',session[0],now=self.f.now,sessions=[session])
        with self.assertRaises(ValueError):
            self.store.arm('AMZN',1,'10','2099-01-01',now=self.f.now,sessions=[session])
        self.assertEqual(self.store.plans(),[])

    def test_working_then_fill_receipt_manual_close_and_no_duplicate(self):
        self.arm(target='MANUAL'); self.runner.step()
        p=self.plan();self.assertEqual(p['state'],'SUBMITTED')
        self.assertEqual(len(self.f.engine.ledger.orders()),1)
        self.assertEqual(self.f.engine.ledger.order(p['client_key'])['order']['quantity'],2)
        self.assertEqual(self.service.execute(signed(self.f.now),p['intent'])['status'],'WORKING')
        self.f.quote(seconds=1); self.f.service.observe()
        receipt=self.service.state(signed(self.f.now),p['intent'])
        self.assertTrue(receipt['position_open']);self.assertEqual(receipt['filled_quantity'],2)
        self.assertEqual(receipt['selection']['target'],'MANUAL')
        for _ in range(3):self.runner.step()
        self.assertEqual(len(self.f.engine.ledger.orders()),1)
        self.f.quote(bid=2.1,ask=2.15,seconds=2)
        review=self.service.prepare_action(signed(self.f.now),p['intent'],'close')
        self.service.confirm_action(signed(self.f.now),p['intent'],review['id'])
        self.f.quote(bid=2.1,ask=2.15,seconds=3);self.f.service.observe()
        receipt=self.service.state(signed(self.f.now),p['intent'])
        self.assertFalse(receipt['position_open']);self.assertEqual(receipt['sale_report']['status'],'CLOSED')

    def test_automatic_target_and_stop_preserved_after_queue_fill(self):
        for target,bid,ask,reason in [('35',2.70,2.75,'TARGET'),('MANUAL',1.8,1.85,'LOSS_LIMIT')]:
            h=AutomaticQueueTests();h.setUp()
            try:
                h.arm(target=target);h.runner.step();h.f.quote(seconds=1);h.f.service.observe()
                h.f.quote(bid=bid,ask=ask,seconds=3);h.f.service.observe()
                h.f.quote(bid=bid,ask=ask,seconds=4);h.f.service.observe()
                p=h.plan();r=h.service.execute(signed(h.f.now),p['intent'])
                self.assertEqual(r['sale_report']['status'],'CLOSED')
                self.assertIn(reason,r['sale_report']['reasons'])
            finally:h.doCleanups()

    def test_pause_during_provider_lookup_prevents_later_dispatch(self):
        identity=self.arm()
        original=self.f.market.get_catalog_chain
        def pause(*args):
            result=original(*args);self.store.pause(identity);return result
        with patch.object(self.f.market,'get_catalog_chain',side_effect=pause):self.runner.step()
        self.assertEqual(self.plan()['state'],'PAUSED')
        self.assertEqual(self.f.engine.ledger.orders(),[])

    def test_outside_session_and_stale_monitor_cannot_enter(self):
        self.arm();self.ready=False;self.runner.step()
        self.assertEqual(self.plan()['reason'],'MONITOR_NOT_READY')
        self.f.client.full_chain.assert_not_called()
        self.ready=True;self.f.now=datetime.fromisoformat(self.plan()['closes_at']);self.runner.step()
        self.assertEqual(self.plan()['state'],'EXPIRED')
        self.assertEqual(self.f.engine.ledger.orders(),[])

    def test_retraction_stale_feed_and_same_signal_at_arming_never_enter(self):
        for mode in ('retracted','stale','feed','baseline','before_arm'):
            h=AutomaticQueueTests();h.setUp()
            try:
                h.arm(baseline=__import__('automatic_entry_queue').signal_key(h.f.state['tick']) if mode=='baseline' else None)
                if mode=='retracted':h.f.state['tick']['signal']=None
                if mode=='stale':h.f.state['tick']['source_timestamp']=(h.f.now-timedelta(seconds=4)).isoformat()
                if mode=='feed':h.f.state['runtime']['feed']='sip'
                if mode=='before_arm':
                    with h.store.transaction() as db:db.execute('UPDATE queue_plans SET armed_at=?',(h.f.now.isoformat(),))
                h.runner.step();self.assertEqual(h.f.engine.ledger.orders(),[])
            finally:h.doCleanups()

    def test_missing_eligible_contract_keeps_waiting_without_fabricating(self):
        self.arm();self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0].update(bid=3,ask=3.01)
        self.runner.step()
        self.assertEqual(self.plan()['state'],'ARMED');self.assertEqual(self.plan()['reason'],'NO_ELIGIBLE_CONTRACTS')
        self.assertEqual(self.f.engine.ledger.orders(),[])
        # Later NEW current quote, still same live EXIT, becomes apt; no old fill.
        self.f.quote(seconds=6);self.runner.step()
        self.assertEqual(self.plan()['state'],'SUBMITTED')

    def test_direction_changes_while_fetching_never_buys_original_side(self):
        self.arm(); original=self.f.market.get_catalog_chain
        def retract(*args):
            result=original(*args);self.f.state['tick']['signal']['side']='INFERIOR';return result
        with patch.object(self.f.market,'get_catalog_chain',side_effect=retract):self.runner.step()
        self.assertEqual(self.plan()['reason'],'SIGNAL_CHANGED');self.assertEqual(self.f.engine.ledger.orders(),[])

    def test_lower_exit_selects_put_not_call(self):
        q=deepcopy(self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0])
        q.update(symbol='AMZN  261023P00105000',putCall='PUT',strikePrice=105.)
        self.f.payload['putExpDateMap']={'2026-10-23:7':{'105.0':[q]}}
        self.f.state['tick']['signal']['side']='INFERIOR'
        self.arm();self.runner.step()
        p=self.plan();self.assertEqual(p['state'],'SUBMITTED')
        order=self.f.engine.ledger.order(p['client_key'])['order']
        self.assertEqual(order['contract'],q['symbol'])

    def test_selects_nearest_eligible_itm_regardless_provider_order(self):
        q=deepcopy(self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0])
        q.update(symbol='AMZN  261023C00103000',strikePrice=103.)
        self.f.payload['callExpDateMap']['2026-10-23:7']['103.0']=[q]
        self.arm();self.runner.step()
        self.assertEqual(self.f.engine.ledger.order(self.plan()['client_key'])['order']['contract'],q['symbol'])

    def test_current_ask_can_change_within_armed_range_but_never_outside(self):
        for ask, expected in [(2.1,'SUBMITTED'),(2.4,'ARMED')]:
            h=AutomaticQueueTests();h.setUp()
            try:
                # Catalog spot is too old for sub-second reuse: require GET.
                h.f.payload['underlying']['quoteTime']=int((h.f.now-timedelta(seconds=2)).timestamp()*1000)
                direct=h.f.client.quotes.side_effect
                def quote(symbols, now):
                    raw=direct(symbols,now)
                    raw[symbols[1]]['quote'].update(bidPrice=ask-.05,askPrice=ask)
                    return raw
                h.f.client.quotes.side_effect=quote
                h.arm();h.runner.step();self.assertEqual(h.plan()['state'],expected)
                if expected=='SUBMITTED':
                    order=h.f.engine.ledger.order(h.plan()['client_key'])['order']
                    self.assertEqual(float(order['limit']),2.3)  # Saved ceiling, fill still at Ask.
                    self.assertEqual(float(order['reviewed_entry_cost']),460.0)
                else:self.assertEqual(h.f.engine.ledger.orders(),[])
            finally:h.doCleanups()

    def test_provider_error_respects_retry_and_hides_private_error(self):
        self.arm()
        with patch.object(self.f.market,'get_catalog_chain',side_effect=ManualDataError('PRIVATE_SECRET')) as market:
            self.runner.step();self.runner.step()
            self.assertEqual(market.call_count,1)
        self.assertEqual(self.plan()['reason'],'CHECK_REQUIRED')
        self.assertNotIn('PRIVATE_SECRET',str(self.store.plans()))

    def test_restart_does_not_replay_current_signal_or_uncertain_attempt(self):
        self.arm();self.runner=self.build();self.runner.step()
        self.assertEqual(self.f.engine.ledger.orders(),[])
        # Next candle, truly new current EXIT, can enter.
        self.f.quote(seconds=901);self.runner.step()
        self.assertEqual(self.plan()['state'],'SUBMITTED')
        self.runner=self.build();self.runner.step()
        self.assertEqual(len(self.f.engine.ledger.orders()),1)

    def test_unknown_dispatch_is_durable_and_never_retried(self):
        self.arm()
        original=self.f.engine.enter
        def lost(*args,**kwargs):
            original(*args,**kwargs);raise RuntimeError('PRIVATE_ACK_LOST')
        with patch.object(self.f.engine,'enter',side_effect=lost) as enter:
            self.runner.step();self.runner.step();self.build().step()
            self.assertEqual(enter.call_count,1)
        self.assertEqual(self.plan()['state'],'UNCERTAIN');self.assertEqual(len(self.f.engine.ledger.orders()),1)
        with self.assertRaisesRegex(ValueError,'UNCERTAIN'):self.arm()

    def test_lock_or_reconciliation_delay_cannot_buy_using_earlier_clock(self):
        self.arm()
        original=self.f.service._reconcile
        def delayed(now):
            original(now);self.f.now+=timedelta(seconds=4)
        with patch.object(self.f.service,'_reconcile',side_effect=delayed):self.runner.step()
        self.assertEqual(self.f.engine.ledger.orders(),[])
        self.assertEqual(self.plan()['state'],'UNCERTAIN')

    def test_parallel_workers_claim_only_once(self):
        self.arm()
        # Independent worker objects after construction; no startup baseline for
        # the test's synthetic just-arrived signal. Queue/engine claims are durable.
        other=object.__new__(QueueRunner);other.__dict__=dict(self.runner.__dict__)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda r:r.step(),[self.runner,other]))
        self.assertEqual(len(self.f.engine.ledger.orders()),1)
        self.assertEqual(len(self.store.read('SELECT * FROM queue_attempts')),1)

    def test_notify_new_receipt_once_and_skip_history_on_restart(self):
        api=Mock(return_value={'message_id':123})
        notifier=QueueNotifier(self.store,self.service,api)
        self.arm();self.runner.step();notifier.pump();api.assert_not_called()
        self.f.quote(seconds=1);self.f.service.observe();notifier.pump();notifier.pump()
        self.assertEqual(api.call_count,1)
        self.assertEqual(api.call_args.kwargs['reply_markup']['inline_keyboard'], [[
            {'text':'Ver operación en el dashboard','url':'https://jj.example/?automaticas=1'}]])
        self.assertIn('Se está ejecutando: AMZN · CALL',api.call_args.kwargs['text'])
        self.assertIn('Comprados: 2 / 2 · Entrada media $2.0000',api.call_args.kwargs['text'])
        self.assertIn('SIMULACIÓN LOCAL',api.call_args.kwargs['text'])
        with self.store.transaction() as db:db.execute("UPDATE queue_attempts SET notice_state='WAITING'")
        self.f.now+=timedelta(seconds=1);QueueNotifier(self.store,self.service,api).pump()
        self.assertEqual(api.call_count,1)
        self.assertEqual(self.store.read('SELECT notice_state FROM queue_attempts')[0]['notice_state'],'HISTORICAL_SKIPPED')

    def test_uncertain_telegram_is_not_retried_and_never_blocks_entry(self):
        api=Mock(side_effect=TimeoutError('PRIVATE'))
        notifier=QueueNotifier(self.store,self.service,api);self.arm();self.runner.step()
        self.f.quote(seconds=1);self.f.service.observe()
        notifier.pump();notifier.pump();self.assertEqual(api.call_count,1)
        self.assertEqual(self.plan()['state'],'SUBMITTED')
        self.assertEqual(self.store.read('SELECT notice_state FROM queue_attempts')[0]['notice_state'],'DELIVERY_UNCONFIRMED')

    def test_partial_entry_notifies_actual_quantity_once(self):
        api=Mock(return_value={'message_id':123});notifier=QueueNotifier(self.store,self.service,api)
        self.arm();self.runner.step()
        self.f.quote(size=1,seconds=1);self.f.service.observe();notifier.pump()
        self.assertIn('Comprados: 1 / 2',api.call_args.kwargs['text'])
        self.f.quote(size=1,seconds=2);self.f.service.observe();notifier.pump()
        self.assertEqual(api.call_count,1)

    def test_completed_before_notification_does_not_claim_still_running(self):
        api=Mock(return_value={'message_id':123});notifier=QueueNotifier(self.store,self.service,api)
        self.arm();self.runner.step();self.f.quote(seconds=1);self.f.service.observe()
        self.f.quote(bid=2.7,ask=2.75,seconds=2);self.f.service.observe()
        self.f.quote(bid=2.7,ask=2.75,seconds=3);self.f.service.observe();notifier.pump()
        self.assertIn('Se ejecutó y ya finalizó:',api.call_args.kwargs['text'])
        self.assertNotIn('Se está ejecutando:',api.call_args.kwargs['text'])

    def test_automation_policy_or_foreign_database_cannot_be_adopted(self):
        self.f.engine.policy=__import__('tests.test_schwab_simulation',fromlist=['synthetic_policy']).synthetic_policy()
        with self.assertRaisesRegex(ExecutionBlocked,'LOCAL_PRACTICE_ONLY'):self.build()
        with self.assertRaises(ValueError):QueueStore(self.f.engine.ledger.path)

    def test_official_calendar_readonly_and_holidays_not_invented(self):
        path=self.f.root/'calendar.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE market_sessions(session_date TEXT PRIMARY KEY,opens_at TEXT,closes_at TEXT)')
            db.execute('INSERT INTO market_sessions VALUES(?,?,?)',(self.f.now.date().isoformat(),*self.f.state['session']))
        before=path.read_bytes();self.assertEqual(len(official_sessions(path,self.f.now)),1)
        self.assertEqual(official_sessions(path,self.f.now+timedelta(days=1)),[])
        self.assertEqual(path.read_bytes(),before)


class QueueDashboardTests(unittest.TestCase):
    def test_actual_streamlit_controls_arm_pause_and_show_private_queue(self):
        from streamlit.testing.v1 import AppTest
        h=AutomaticQueueTests();h.setUp();self.addCleanup(h.doCleanups)
        now=datetime.now(timezone.utc);day=(now+timedelta(days=1)).date().isoformat()
        from zoneinfo import ZoneInfo
        start=datetime.fromisoformat(day+'T09:30:00').replace(tzinfo=ZoneInfo('America/New_York'))
        end=start.replace(hour=16,minute=0)
        sessions=[(day,start.isoformat(),end.isoformat())]
        with patch('automatic_entry_panel.queue_store',return_value=h.store),\
             patch('automatic_entry_panel.official_sessions',return_value=sessions),\
             patch('automatic_entry_panel.read_manual_state',return_value={'tick':{}}):
            app=AppTest.from_string('from automatic_entry_panel import render_automatic_entry_panel\nrender_automatic_entry_panel()').run(timeout=15)
            self.assertEqual(len(app.exception),0)
            self.assertEqual(h.store.plans(),[])
            app.selectbox(key='auto_queue_symbol').select('AMZN').run(timeout=15)
            self.assertEqual(app.number_input(key='auto_queue_quantity').value,0)
            app.selectbox(key='auto_queue_target').select('35').run(timeout=15)
            app.checkbox(key='auto_queue_consent').check().run(timeout=15)
            app.button(key='auto_queue_arm').click().run(timeout=15)
            self.assertEqual(h.store.plans(),[])
            self.assertEqual(h.f.engine.ledger.orders(),[])
            self.assertTrue(app.warning)
            app.number_input(key='auto_queue_quantity').set_value(2)
            app.selectbox(key='auto_queue_target').select('35')
            app.run(timeout=15)
            app.checkbox(key='auto_queue_consent').check().run(timeout=15)
            self.assertTrue(any('$460.00' in m.value for m in app.markdown))
            app.button(key='auto_queue_arm').click().run(timeout=15)
            self.assertEqual(len(app.exception),0)
            self.assertEqual(h.plan()['state'],'ARMED')
            self.assertEqual(h.f.engine.ledger.orders(),[])
            app.button(key='auto_queue_pause_all').click().run(timeout=15)
            self.assertEqual(len(app.exception),0)
            self.assertEqual(h.plan()['state'],'PAUSED')
            identity=h.plan()['id']
            app.button(key='auto_queue_delete_'+identity).click().run(timeout=15)
            self.assertEqual(len(app.exception),0)
            self.assertEqual(h.store.plans(),[])
            self.assertEqual(len(h.store.read('SELECT * FROM queue_plans')),1)
            self.assertEqual(h.f.engine.ledger.orders(),[])
            app.selectbox(key='auto_queue_symbol').select('AAPL').run(timeout=15)
            self.assertEqual(app.number_input(key='auto_queue_quantity').value,0)
            self.assertIsNone(app.selectbox(key='auto_queue_target').value)
            self.assertFalse(app.checkbox(key='auto_queue_consent').value)


class QueueArchiveTests(unittest.TestCase):
    def setUp(self):
        self.h=AutomaticQueueTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def remove(self, identity):
        return self.h.store.archive(identity,now=self.h.f.now,ledger_path=self.h.f.engine.ledger.path)

    def test_armed_or_paused_can_be_hidden_without_deleting_history(self):
        identity=self.h.arm();self.remove(identity)
        self.assertEqual(self.h.store.plans(),[])
        self.assertEqual(self.h.store.active(),[])
        self.assertEqual(self.h.store.read('SELECT state FROM queue_plans')[0]['state'],'PAUSED')
        self.remove(identity)  # idempotent
        self.assertEqual(len(self.h.store.read('SELECT * FROM queue_archives')),1)
        self.h.runner.step();self.assertEqual(self.h.f.engine.ledger.orders(),[])
        identity=self.h.arm();self.h.store.pause(identity);self.remove(identity)
        self.assertEqual(len(self.h.store.read('SELECT * FROM queue_plans')),2)

    def test_remove_during_provider_lookup_fences_dispatch(self):
        identity=self.h.arm();original=self.h.f.market.get_catalog_chain
        def remove(*args):
            result=original(*args);self.remove(identity);return result
        with patch.object(self.h.f.market,'get_catalog_chain',side_effect=remove):self.h.runner.step()
        self.assertEqual(self.h.store.plans(),[])
        self.assertEqual(self.h.f.engine.ledger.orders(),[])

    def test_pending_filled_open_and_pending_close_cannot_be_hidden(self):
        identity=self.h.arm(target='MANUAL');self.h.runner.step()
        with self.assertRaises(ExecutionBlocked):self.remove(identity)
        self.h.f.quote(seconds=1);self.h.f.service.observe()
        with self.assertRaises(ExecutionBlocked):self.remove(identity)
        review=self.h.f.service.prepare_close('owner',self.h.f.code)
        self.h.f.service.confirm('owner',review['id'])
        with self.assertRaises(ExecutionBlocked):self.remove(identity)
        self.assertEqual(len(self.h.store.plans()),1)

    def test_after_sale_remove_preserves_attempts_orders_fills_and_receipts(self):
        identity=self.h.arm(target='MANUAL');self.h.runner.step()
        self.h.f.quote(seconds=1);self.h.f.service.observe()
        review=self.h.f.service.prepare_close('owner',self.h.f.code)
        self.h.f.service.confirm('owner',review['id'])
        self.h.f.quote(seconds=2);self.h.f.service.observe()
        plan=self.h.plan();orders=deepcopy(self.h.f.engine.ledger.orders())
        with closing(sqlite3.connect(self.h.f.engine.ledger.path)) as db:
            fills=db.execute('SELECT * FROM simulated_fills').fetchall()
        self.remove(identity)
        self.assertEqual(self.h.store.plans(),[])
        self.assertEqual(self.h.f.engine.ledger.orders(),orders)
        with closing(sqlite3.connect(self.h.f.engine.ledger.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM simulated_fills').fetchall(),fills)
        self.assertEqual(len(self.h.store.read('SELECT * FROM queue_attempts')),1)
        self.assertEqual(self.h.service.execute(signed(self.h.f.now),plan['intent'])['sale_report']['status'],'CLOSED')

    def test_cancelled_unfilled_can_be_hidden_but_uncertain_cannot(self):
        identity=self.h.arm();self.h.runner.step()
        key=self.h.plan()['client_key'];review=self.h.f.service.prepare_cancel('owner',key)
        self.h.f.service.confirm('owner',review['id']);self.remove(identity)
        self.assertEqual(self.h.store.plans(),[])
        with self.h.store.transaction() as db:
            db.execute("DELETE FROM queue_archives WHERE plan_id=?",(identity,))
            db.execute("UPDATE queue_plans SET state='UNCERTAIN' WHERE id=?",(identity,))
        with self.assertRaises(ExecutionBlocked):self.remove(identity)
        self.assertEqual(len(self.h.store.plans()),1)

    def test_missing_or_foreign_ledger_fails_closed(self):
        identity=self.h.arm();self.h.runner.step()
        for path in (self.h.f.root/'missing.db',self.h.store.path):
            with self.assertRaises(ExecutionBlocked):
                self.h.store.archive(identity,now=self.h.f.now,ledger_path=path)
        self.assertFalse((self.h.f.root/'missing.db').exists())
        self.assertEqual(len(self.h.store.plans()),1)
