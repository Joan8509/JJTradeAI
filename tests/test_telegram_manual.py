"""Authenticated one-click flow, synthetic quotes and temporary databases only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import hashlib
import hmac
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from urllib.parse import urlencode,urlsplit,parse_qs

from tests import test_manual_execution as fixture
from telegram_manual import TelegramManualService,TelegramManualStore,TelegramManualError,validate_init_data
from telegram_manual_bot import TelegramManualBot,TelegramCallbackPoller
from telegram_manual_controls import preparation_button,preparation_callback,poller_lock,companion_ready,entry_monitor_ready
from telegram_manual_http import LoopbackServer,handler_for

TOKEN='123456:synthetic_only'
OWNER=123


def signed(now,**overrides):
    fields=dict(auth_date=str(int(now.timestamp())),query_id='synthetic_launch',
                user=json.dumps({'id':OWNER,'first_name':'Synthetic'}))
    fields.update(overrides)
    secret=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    check='\n'.join(k+'='+v for k,v in sorted(fields.items()))
    return urlencode(dict(fields,hash=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()))


class TelegramAuthTests(unittest.TestCase):
    def test_valid_signed_data_and_reject_tampering_owner_age_bot_group_and_duplicates(self):
        now=fixture.f.NOW;raw=signed(now)
        self.assertEqual(validate_init_data(raw,TOKEN,OWNER,now).user_id,OWNER)
        bad=[raw.replace('Synthetic','Tampered'),raw+'&auth_date=1',signed(now,user='{"id":124}'),
             signed(now,user='{"id":true}'),signed(now,user='{"id":123,"is_bot":true}'),
             signed(now,chat_type='group'),signed(now,query_id=''),signed(now,auth_date=str(int(now.timestamp())+1)),
             signed(now,auth_date=str(int(now.timestamp())-121)),'x'*16385]
        for value in bad:
            with self.subTest(value=value[:15]),self.assertRaisesRegex(TelegramManualError,'TELEGRAM_AUTH_REQUIRED'):
                validate_init_data(value,TOKEN,OWNER,now)


class TelegramServiceTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ManualExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.store=TelegramManualStore(self.f.root/'telegram.db')
        self.service=self.build()

    def build(self):
        return TelegramManualService(self.f.service,self.store,token=TOKEN,user_id=OWNER,base_url='https://jj.example/telegram/')

    def raw(self,query='synthetic_launch'):
        return signed(self.f.now,query_id=query)

    def complete(self,target='35'):
        draft=self.service.begin('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        self.service.card(draft)
        for action in ('c0','q3','t'+target):
            draft=self.service.change(draft['id'],draft['version'],action)
            card=self.service.card(draft)
        self.draft=draft
        button=card['reply_markup']['inline_keyboard'][-1][0]
        self.assertIn('SIMULADA',button['text'])
        return parse_qs(urlsplit(button['web_app']['url']).fragment)['intent'][0]

    def test_explicit_selection_no_defaults_and_no_order_until_signed_post(self):
        draft=self.service.begin('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        card=self.service.card(draft)
        self.assertIsNone(draft['quantity']);self.assertIsNone(draft['target']);self.assertIsNone(draft['contract'])
        self.assertFalse(any('web_app' in b for row in card['reply_markup']['inline_keyboard'] for b in row))
        intent=self.complete();self.assertEqual(self.f.engine.broker.snapshot(),[])
        with self.assertRaises(TelegramManualError):self.service.execute('untrusted',intent)
        result=self.service.execute(self.raw(),intent)
        self.assertEqual(result['status'],'WORKING');self.assertFalse(result['real_orders_enabled'])
        self.assertEqual(result['selection']['quantity'],3);self.assertEqual(result['selection']['stop'],'10')

    def test_rejected_quotes_and_empty_eligible_set_never_offer_quantity_or_purchase(self):
        for changes,code in [({'delta':-999},'OPTION_QUOTES_UNAVAILABLE'),
                             ({'bid':20.,'ask':20.05},'NO_ELIGIBLE_CONTRACTS')]:
            with self.subTest(changes=changes):
                row=self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
                previous=dict(row)
                try:
                    row.update(changes)
                    self.f.service.market_data.cache.clear()
                    with self.assertRaisesRegex(TelegramManualError,code):
                        self.service.begin('AMZN','CALL',self.f.state['tick']['signal']['candle'])
                finally:row.clear();row.update(previous)
        self.assertEqual(self.store.read('SELECT id FROM telegram_drafts'),[])
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_signal_watch_opens_retracted_signal_readonly_without_market_catalog_or_intent(self):
        candle=self.f.state['tick']['signal']['candle'];self.f.state['tick']['signal']=None
        files=[self.store.path,self.f.engine.ledger.path,self.f.engine.broker.path,self.f.service.reviews.path]
        before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
        with patch.object(self.f.service.market_data,'get_chain') as market:
            result=self.service.watch(self.raw(),'AMZN','CALL',candle)
        self.assertEqual(result['status'],'SIGNAL_BLOCKED');self.assertEqual(result['reason'],'NO_CURRENT_SIGNAL')
        self.assertTrue(result['view_only']);self.assertIsNone(result['signal_price']);market.assert_not_called()
        self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in files])
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_signal_watch_updates_current_evidence_but_never_authorizes_another_candle_or_side(self):
        candle=self.f.state['tick']['signal']['candle']
        current=self.service.watch(self.raw(),'AMZN','CALL',candle)
        self.assertEqual(current['status'],'CURRENT_SIGNAL');self.assertEqual(current['signal_price'],104.)
        wrong=self.service.watch(self.raw(),'AMZN','PUT',candle)
        self.assertEqual(wrong['reason'],'SIGNAL_DIRECTION_CHANGED');self.assertIsNone(wrong['signal_price'])
        old=(self.f.now-timedelta(minutes=15)).isoformat()
        self.assertEqual(self.service.watch(self.raw(),'AMZN','CALL',old)['reason'],'SIGNAL_CHANGED')
        self.f.state['runtime']['heartbeat']=(self.f.now-timedelta(seconds=4)).isoformat()
        self.assertEqual(self.service.watch(self.raw(),'AMZN','CALL',candle)['reason'],'COLLECTOR_NOT_CURRENT')
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_signal_watch_rejects_forged_identity_before_reading_and_untrusted_reference(self):
        candle=self.f.state['tick']['signal']['candle']
        with patch.object(self.f.service,'read_state') as state:
            with self.assertRaisesRegex(TelegramManualError,'TELEGRAM_AUTH_REQUIRED'):
                self.service.watch('forged','AMZN','CALL',candle)
            state.assert_not_called()
        for symbol,side,stamp in [('BAD/../../','CALL',candle),('AMZN','BUY',candle),('AMZN','CALL','2026-10-19')]:
            with self.assertRaisesRegex(TelegramManualError,'SIGNAL_REFERENCE_INVALID'):
                self.service.watch(self.raw(),symbol,side,stamp)
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_runtime_monitor_failure_blocks_new_buys_but_keeps_receipts_readable(self):
        intent=self.complete();raw=self.raw();self.service.operational_check=lambda:False
        with self.assertRaisesRegex(TelegramManualError,'MONITOR_NOT_READY'):self.service.execute(raw,intent)
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.service.operational_check=lambda:True;self.service.execute(raw,intent)
        self.service.operational_check=lambda:False
        self.assertEqual(self.service.state(raw,intent)['status'],'WORKING')

    def test_independent_monitor_evaluates_stop_without_open_view_and_cannot_duplicate_exit(self):
        intent=self.complete('MANUAL');self.service.execute(self.raw(),intent)
        self.f.quote(seconds=1);self.f.service.observe()
        self.f.quote(bid=1.6,ask=1.65,seconds=2)
        events=self.f.service.observe()
        self.assertEqual(events[0]['reason'],'LOSS_LIMIT')
        # The same observation is never a second sell, including another worker instance.
        self.f.build().observe()
        self.assertEqual(len(self.f.engine.broker.snapshot()),2)

    def test_double_click_restart_and_concurrency_submit_exactly_once(self):
        intent=self.complete();raw=self.raw()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.build().execute(raw,intent),range(2)))
        self.assertTrue(all(r['status'] in ('WORKING','UNCERTAIN') for r in results))
        self.assertEqual(self.build().execute(raw,intent)['status'],'WORKING')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_old_review_changed_ask_retracted_signal_block_without_retry(self):
        for mode in ('old','ask','signal'):
            with self.subTest(mode=mode):
                test=TelegramServiceTests();test.setUp()
                try:
                    intent=test.complete();raw=test.raw()
                    if mode=='old':test.f.quote(seconds=31)
                    elif mode=='ask':test.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0].update(bid=1.9,ask=1.95)
                    else:test.f.state['tick']['signal']=None
                    self.assertEqual(test.service.execute(raw,intent)['status'],'ENTRY_BLOCKED')
                    test.service.execute(raw,intent)
                    self.assertEqual(test.f.engine.broker.snapshot(),[])
                finally:test.doCleanups()

    def test_changed_card_and_cross_intent_launch_are_blocked(self):
        first=self.complete();draft=self.draft
        self.service.change(draft['id'],draft['version'],'q5')
        with self.assertRaisesRegex(TelegramManualError,'CARD_CHANGED'):self.service.execute(self.raw(),first)
        second=self.complete()
        with self.assertRaisesRegex(TelegramManualError,'LAUNCH_ALREADY_BOUND'):self.service.execute(self.raw(),second)
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_contract_switch_resets_quantity_and_target_and_old_callback_cannot_increment(self):
        self.complete();d=self.draft
        changed=self.service.change(d['id'],d['version'],'c0')
        self.assertIsNone(changed['quantity']);self.assertIsNone(changed['target'])
        with self.assertRaisesRegex(TelegramManualError,'CARD_CHANGED'):self.service.change(d['id'],d['version'],'plus')

    def test_displayed_catalog_is_used_and_removed_contract_cannot_select_another(self):
        self.complete();d=self.draft
        with self.store.transaction() as db:
            payload=json.loads(db.execute('SELECT payload FROM telegram_drafts WHERE id=?',(d['id'],)).fetchone()[0])
            payload['catalog']=['NOT_THE_DISPLAYED_CONTRACT']
            db.execute('UPDATE telegram_drafts SET payload=? WHERE id=?',(json.dumps(payload),d['id']))
        with self.assertRaisesRegex(TelegramManualError,'CONTRACT_CHANGED'):self.service.change(d['id'],d['version'],'c0')

    def test_app_and_telegram_share_signal_dedup(self):
        intent=self.complete();review=self.f.prepare(owner='app');self.f.service.confirm('app',review['id'])
        self.assertEqual(self.service.execute(self.raw(),intent)['status'],'BLOCKED_OR_UNCERTAIN')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_view_does_not_fill_and_extended_session_requires_bound_launch(self):
        intent=self.complete();raw=self.raw();self.service.execute(raw,intent)
        self.f.quote(seconds=1)
        paths=[self.f.root/p for p in ('ledger.db','broker.db','reviews.db')]
        before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        self.assertEqual(self.service.state(raw,intent)['status'],'WORKING')
        self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
        with self.assertRaisesRegex(TelegramManualError,'EXECUTION_NOT_STARTED'):self.service.state(self.raw('other'),intent)
        self.f.quote(seconds=121)
        self.service.state(raw,intent)
        with self.assertRaisesRegex(TelegramManualError,'TELEGRAM_AUTH_REQUIRED'):self.service.execute(raw,intent)

    def test_monitor_fills_and_manual_profit_retains_stop_and_manual_close(self):
        intent=self.complete('MANUAL');raw=self.raw();self.service.execute(raw,intent)
        self.f.quote(seconds=1);self.f.service.observe()
        result=self.service.state(raw,intent)
        self.assertEqual(result['status'],'FILLED');self.assertTrue(result['position_open'])
        self.assertEqual(result['mark']['status'],'LIVE');self.assertIsNone(result['mark']['target'])
        self.assertEqual(result['mark']['stop'],Decimal('1.80'))
        close=self.service.prepare_action(raw,intent,'close')
        self.assertNotIn('account_alias',close)
        self.assertEqual(self.service.confirm_action(raw,intent,close['id'])['reason'],'MANUAL_CLOSE')
        self.service.confirm_action(raw,intent,close['id'])
        self.assertEqual(len(self.f.engine.broker.snapshot()),2)
        self.f.quote(seconds=2);self.f.service.observe()
        final=self.service.state(raw,intent)
        self.assertFalse(final['position_open'])
        self.assertEqual(final['sale_report']['status'],'CLOSED')
        self.assertEqual(final['sale_report']['reasons'],['MANUAL_CLOSE'])
        self.assertEqual(final['sale_report']['sold_quantity'],3)

    def test_cancel_pending_entry_and_reject_foreign_action(self):
        intent=self.complete();raw=self.raw();result=self.service.execute(raw,intent)
        with self.assertRaisesRegex(TelegramManualError,'ORDER_NOT_FOUND'):self.service.prepare_action(raw,intent,'cancel','foreign')
        review=self.service.prepare_action(raw,intent,'cancel',result['pending'][0]['key'])
        self.assertEqual(self.service.confirm_action(raw,intent,review['id'])['status'],'CANCELED')
        with self.assertRaisesRegex(TelegramManualError,'ACTION_REVIEW_NOT_FOUND'):self.service.confirm_action(raw,intent,'foreign')

    def test_accepted_but_timeout_is_not_resent(self):
        intent=self.complete();raw=self.raw();original=self.f.engine.broker.accept
        def uncertain(*a,**kw):original(*a,**kw);raise TimeoutError('PRIVATE_DETAIL')
        with patch.object(self.f.engine.broker,'accept',side_effect=uncertain):
            self.service.execute(raw,intent)
        for _ in range(3):self.build().execute(raw,intent)
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)
        self.assertNotIn('PRIVATE_DETAIL',str(self.service.state(raw,intent)))


class TelegramBotTests(TelegramServiceTests):
    # Keep fixture helpers, without rerunning inherited tests in this class.
    def update(self,data,number=1,message=7,owner=OWNER):
        return {'update_id':number,'callback_query':{'id':'q'+str(number),'data':data,'from':{'id':owner},
            'message':{'message_id':message,'chat':{'id':OWNER,'type':'private'}}}}

    def test_callbacks_no_orders_owner_message_binding_and_update_dedup(self):
        api=Mock(return_value={'message_id':8});bot=TelegramManualBot(self.service,api)
        data=preparation_callback('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        self.assertFalse(bot.handle(self.update(data,owner=999)));api.assert_not_called()
        update=self.update(data);self.assertTrue(bot.handle(update));self.assertFalse(bot.handle(update))
        draft=json.loads(self.store.read('SELECT payload FROM telegram_drafts')[0]['payload'])
        self.assertEqual(draft['message_id'],8)
        identity=self.store.read('SELECT id FROM telegram_drafts')[0]['id']
        select='jj:d:'+identity+':0:q3'
        self.assertFalse(bot.handle(self.update(select,2,message=999)))
        self.assertTrue(bot.handle(self.update(select,3,message=8)))
        self.assertFalse(bot.handle(self.update(select,4,message=8)))
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_retracted_signal_has_one_visible_blocking_reply_not_a_second_ack_or_old_signal(self):
        api=Mock(return_value={'message_id':8});bot=TelegramManualBot(self.service,api)
        data=preparation_callback('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        self.f.state['tick']['signal']=None
        update=self.update(data)
        self.assertFalse(bot.handle(update));self.assertFalse(bot.handle(update))
        self.assertEqual([c.args[0] for c in api.call_args_list],['answerCallbackQuery','sendMessage'])
        text=api.call_args.kwargs['text']
        self.assertIn('ya no está vigente',text)
        button=api.call_args.kwargs['reply_markup']['inline_keyboard'][0][0]
        self.assertIn('sin comprar',button['text'])
        reference=parse_qs(urlsplit(button['web_app']['url']).fragment)
        self.assertEqual(reference['watch'],['AMZN']);self.assertNotIn('intent',reference)
        status=json.loads(self.store.read("SELECT value FROM telegram_settings WHERE key='last_callback_result'")[0]['value'])
        self.assertEqual(status['status'],'NO_CURRENT_SIGNAL')
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.assertEqual(self.store.read('SELECT id FROM telegram_drafts'),[])

    def test_unknown_failure_does_not_leak_exception_in_chat_or_diagnostics(self):
        api=Mock(return_value={'message_id':8});bot=TelegramManualBot(self.service,api)
        data=preparation_callback('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        with patch.object(self.service,'begin',side_effect=RuntimeError('SYNTHETIC_PRIVATE_DETAIL')):
            self.assertFalse(bot.handle(self.update(data)))
        self.assertNotIn('SYNTHETIC_PRIVATE_DETAIL',str(api.call_args_list))
        status=self.store.read("SELECT value FROM telegram_settings WHERE key='last_callback_result'")[0]['value']
        self.assertNotIn('SYNTHETIC_PRIVATE_DETAIL',status)
        self.assertEqual(json.loads(status)['status'],'PREPARATION_FAILED')
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_uncertain_card_delivery_does_not_send_a_second_message(self):
        api=Mock(side_effect=[{},TimeoutError('PRIVATE_NETWORK_DETAIL')])
        bot=TelegramManualBot(self.service,api)
        data=preparation_callback('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        update=self.update(data)
        with self.assertRaises(TimeoutError):bot.handle(update)
        self.assertFalse(bot.handle(update))
        self.assertEqual([c.args[0] for c in api.call_args_list],['answerCallbackQuery','sendMessage'])
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_valid_preparation_records_delivery_and_explains_how_to_open_miniapp(self):
        api=Mock(return_value={'message_id':8});bot=TelegramManualBot(self.service,api)
        data=preparation_callback('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        self.assertTrue(bot.handle(self.update(data)))
        self.assertIn('abre la MiniApp',api.call_args.kwargs['text'])
        status=json.loads(self.store.read("SELECT value FROM telegram_settings WHERE key='last_callback_result'")[0]['value'])
        self.assertEqual(status['status'],'CARD_SENT')
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_poller_discards_boot_queue_checkpoints_before_handling_and_never_deletes_webhook(self):
        api=Mock(side_effect=[{},[{'update_id':20}],[self.update('invalid',21)]])
        bot=TelegramManualBot(self.service,api);poller=TelegramCallbackPoller(bot)
        poller.bootstrap();self.assertEqual(poller.offset,21)
        with patch.object(bot,'handle',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):poller.once()
        self.assertEqual(self.store.read("SELECT value FROM telegram_settings WHERE key='offset'")[0]['value'],'22')
        self.assertEqual([c.args[0] for c in api.call_args_list],['getWebhookInfo','getUpdates','getUpdates'])
        api=Mock(return_value={'url':'https://existing.example/'})
        with self.assertRaisesRegex(TelegramManualError,'BOT_WEBHOOK_PRESENT'):
            TelegramCallbackPoller(TelegramManualBot(self.service,api)).bootstrap()
        self.assertEqual(api.call_count,1)

    def test_rate_limit_does_not_send_another_callback_response(self):
        from telegram_alerts import TelegramError
        api=Mock(side_effect=[{},TelegramError('Wait',retry_after_seconds=75)])
        data=preparation_callback('AMZN','CALL',self.f.state['tick']['signal']['candle'])
        with self.assertRaises(TelegramError):TelegramManualBot(self.service,api).handle(self.update(data))
        self.assertEqual(api.call_count,2)


class TelegramHttpTests(TelegramServiceTests):
    def setUp(self):
        super().setUp();self.server=LoopbackServer(('127.0.0.1',0),handler_for(self.service))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,method,path,body=None,**headers):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            connection.request(method,path,body=body,headers=headers)
            response=connection.getresponse();return response.status,dict(response.getheaders()),response.read()
        finally:connection.close()

    def test_get_head_and_invalid_post_never_buy_and_headers_protect_page(self):
        for method in ('GET','HEAD'):
            status,headers,_=self.request(method,'/telegram/')
            self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertIn("frame-ancestors",headers['Content-Security-Policy'])
            self.assertEqual(self.request(method,'/api/execute')[0],404)
            self.assertEqual(self.request(method,'/?intent=anything')[0],403)
        self.assertEqual(self.request('GET','/',Host='evil.example')[0],403)
        intent=self.complete();body=json.dumps(dict(init_data=self.raw(),intent=intent))
        self.assertEqual(self.request('POST','/api/execute',body,**{'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.request('POST','/api/execute',body,Origin='https://evil.example',**{'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_valid_post_executes_once_and_state_never_dispatches(self):
        intent=self.complete();body=json.dumps(dict(init_data=self.raw(),intent=intent))
        headers={'Origin':self.service.origin,'Content-Type':'application/json'}
        for path in ('/telegram/api/execute','/api/execute','/api/state'):
            status,_,raw=self.request('POST',path,body,**headers)
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['status'],'WORKING')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)
        duplicate=body[:-1]+',"intent":"other"}'
        self.assertEqual(self.request('POST','/api/execute',duplicate,**headers)[0],400)
        self.assertEqual(self.request('POST','/api/execute','{"init_data":"PRIVATE","intent":"x"}',**headers)[0],403)

    def test_watch_endpoint_requires_signed_owner_and_never_creates_a_purchase(self):
        candle=self.f.state['tick']['signal']['candle'];self.f.state['tick']['signal']=None
        body={'init_data':self.raw(),'symbol':'AMZN','side':'CALL','candle':candle}
        headers={'Origin':self.service.origin,'Content-Type':'application/json'}
        status,_,raw=self.request('POST','/api/watch',json.dumps(body),**headers)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['reason'],'NO_CURRENT_SIGNAL')
        self.assertEqual(self.request('POST','/api/watch',json.dumps(dict(body,init_data='forged')),**headers)[0],403)
        self.assertEqual(self.request('POST','/api/watch',json.dumps(dict(body,intent='untrusted')),**headers)[0],403)
        self.assertEqual(self.request('GET','/api/watch')[0],404)
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.assertEqual(self.store.read('SELECT id FROM telegram_intents'),[])

    def test_direct_entry_http_is_signed_one_click_and_repeated_post_only_reads_receipt(self):
        headers={'Origin':self.service.origin,'Content-Type':'application/json'}
        reference={'symbol':'AMZN','side':'CALL','candle':self.f.state['tick']['signal']['candle']}
        catalog={'init_data':self.raw(),**reference}
        self.assertEqual(self.request('POST','/api/entry-catalog',json.dumps(catalog),**headers)[0],200)
        self.assertEqual(self.f.engine.broker.snapshot(),[])
        body={**catalog,'contract':self.f.code,'quantity':3,'target':'35','ask':'2.00','total':'601.95',
              'stop':'10','request_id':'11111111111111111111111111111111'}
        self.assertEqual(self.request('POST','/api/entry-buy',json.dumps(dict(body,init_data='forged')),**headers)[0],403)
        self.assertEqual(self.store.read('SELECT query_hash FROM telegram_entry_requests'),[])
        for _ in range(2):
            status,_,raw=self.request('POST','/api/entry-buy',json.dumps(body),**headers)
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['status'],'WORKING')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)
        self.assertEqual(self.request('GET','/api/entry-buy')[0],404)
        self.assertEqual(self.request('POST','/api/entry-buy',json.dumps(dict(body,mode='REAL')),**headers)[0],403)


# Fixture inheritance is solely for helpers; collect each behavioral test once.
for _class in (TelegramBotTests,TelegramHttpTests):
    for _name in vars(TelegramServiceTests):
        if _name.startswith('test_'):setattr(_class,_name,None)
del _class,_name


class TelegramControlsTests(unittest.TestCase):
    def test_strategy_notice_has_four_lines_without_trade_buttons_or_replay(self):
        from tests import test_bollinger_phone_worker as notice_fixture
        original=notice_fixture.tick
        button={'text':'Preparar compra · prueba','callback_data':'synthetic'}
        def checked(*args,**kwargs):
            result=original(*args,**kwargs)
            if result['sent']==1:
                sender=kwargs['sender']
                self.assertNotIn('reply_markup',sender.call_args.kwargs)
                self.assertEqual(len(sender.call_args.args[0].splitlines()),4)
            return result
        with patch('telegram_manual_controls.preparation_button',return_value=button) as prepare,\
             patch.object(notice_fixture,'tick',side_effect=checked):
            notice_fixture.BollingerPhoneTests('test_only_one_notice_per_candle_and_restart').test_only_one_notice_per_candle_and_restart()
        prepare.assert_not_called()
        with patch('telegram_manual_controls.preparation_button',side_effect=RuntimeError('optional failure')):
            notice_fixture.BollingerPhoneTests('test_only_one_notice_per_candle_and_restart').test_only_one_notice_per_candle_and_restart()

    def test_navigation_stays_visible_during_temporary_blocks_but_buy_readiness_does_not(self):
        now=fixture.f.NOW
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'status.json'
            self.assertIsNone(preparation_button('AMZN','CALL',now.isoformat(),path=path,now=now))
            for state,age,real,visible,ready in [('READY',0,False,True,True),('READY',11,False,True,False),
                ('READY',-1,False,True,False),('READY',0,True,False,False),
                ('BOT_NOT_READY',0,False,True,False),('MONITOR_BLOCKED',0,False,True,False),
                ('STOPPED',0,False,False,False),('DISABLED_OR_INCOMPLETE',0,False,False,False)]:
                path.write_text(json.dumps(dict(state=state,heartbeat=(now-timedelta(seconds=age)).isoformat(),
                    real_orders_enabled=real,monitor_ready=state!='MONITOR_BLOCKED')))
                button=preparation_button('AMZN','CALL',now.isoformat(),path=path,now=now,base_url='https://jj.example/')
                self.assertEqual(button is not None,visible)
                self.assertEqual(companion_ready(path=path,now=now),ready)
                if visible:
                    self.assertEqual(set(button),{'text','web_app'})
                    reference=parse_qs(urlsplit(button['web_app']['url']).fragment)
                    field='entry' if entry_monitor_ready(path=path,now=now) else 'watch'
                    self.assertEqual(reference[field],['AMZN']);self.assertNotIn('intent',reference)

    def test_visible_button_cannot_create_draft_or_order_while_runtime_blocked(self):
        fixture=TelegramServiceTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.service.operational_check=lambda:False
        api=Mock(return_value={'message_id':8});bot=TelegramManualBot(fixture.service,api)
        now=fixture.f.now;candle=fixture.f.state['tick']['signal']['candle']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'status.json'
            path.write_text(json.dumps(dict(state='MONITOR_BLOCKED',heartbeat=now.isoformat(),real_orders_enabled=False)))
            button=preparation_button('AMZN','CALL',candle,path=path,now=now,base_url='https://jj.example/')
            self.assertIn('web_app',button);self.assertNotIn('callback_data',button)
            # A previously displayed preparation callback is still blocked too.
            update={'update_id':1,'callback_query':{'id':'synthetic','data':preparation_callback('AMZN','CALL',candle),
                'from':{'id':OWNER},'message':{'message_id':7,'chat':{'id':OWNER,'type':'private'}}}}
            self.assertFalse(bot.handle(update))
        self.assertIn('monitor de salidas no está listo',api.call_args.kwargs['text'])
        self.assertEqual(fixture.store.read('SELECT id FROM telegram_drafts'),[])
        self.assertEqual(fixture.store.read('SELECT id FROM telegram_intents'),[])
        self.assertEqual(fixture.f.engine.broker.snapshot(),[])

    def test_disabled_missing_malformed_or_invalid_signal_never_offers_preparation(self):
        now=fixture.f.NOW
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'status.json'
            for content in ('null','[]','invalid','{}','{"state":"READY","real_orders_enabled":true}'):
                path.write_text(content)
                self.assertIsNone(preparation_button('AMZN','CALL',now.isoformat(),path=path,now=now))
            path.write_text(json.dumps(dict(state='READY',real_orders_enabled=False,heartbeat=now.isoformat())))
            self.assertIsNone(preparation_button('BAD/','CALL',now.isoformat(),path=path,now=now))
            self.assertIsNone(preparation_button('AMZN','BUY',now.isoformat(),path=path,now=now))

    def test_transient_windows_receipt_access_retries_but_never_accepts_stale_or_future_state(self):
        from telegram_manual_controls import _read_status
        now=fixture.f.NOW
        for age,expected in ((0,True),(11,False),(-1,False)):
            payload=json.dumps(dict(state='READY',heartbeat=(now-timedelta(seconds=age)).isoformat(),real_orders_enabled=False))
            with patch.object(Path,'read_text',side_effect=[PermissionError('SYNTHETIC'),payload]) as read,\
                 patch('telegram_manual_controls.time.sleep') as pause:
                self.assertEqual(companion_ready(path='synthetic_status',now=now),expected)
                self.assertEqual(read.call_count,2);pause.assert_called_once_with(.01)
        payload=json.dumps(dict(state='READY',heartbeat=now.isoformat(),real_orders_enabled=False,monitor_ready=True))
        with patch.object(Path,'read_text',side_effect=[PermissionError('SYNTHETIC'),payload,payload]),\
             patch('telegram_manual_controls.time.sleep'):
            button=preparation_button('AMZN','CALL',now.isoformat(),path='synthetic_status',now=now,base_url='https://jj.example/')
            self.assertIn('entry=',button['web_app']['url'])
        with patch.object(Path,'read_text',side_effect=PermissionError('SYNTHETIC')) as read,\
             patch('telegram_manual_controls.time.sleep') as pause:
            self.assertFalse(companion_ready(path='synthetic_status',now=now))
            self.assertEqual(read.call_count,3);self.assertEqual(pause.call_count,2)

    def test_exclusive_poller_and_discovery_cannot_steal_updates(self):
        from telegram_alerts import discover,TelegramError
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'lock'
            with poller_lock(path):
                with self.assertRaisesRegex(RuntimeError,'BOT_READER_ALREADY_RUNNING'):
                    with poller_lock(path):pass
                with patch('telegram_manual_controls.poller_lock',side_effect=lambda:poller_lock(path)),patch('telegram_alerts.call') as api:
                    with self.assertRaisesRegex(TelegramError,'otro lector'):discover(TOKEN)
                    api.assert_not_called()
