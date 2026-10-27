"""Delivered-alert entry policy: synthetic quotes, isolated SQLite, no network."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from manual_alert_entry import (AlertReference,read_alert_reference,validate_reference,
    validated_alert_entry,ManualAlertEntry)
from manual_execution import EntryNotDispatched
from fast_manual_entry import FastManualEntry
from schwab_simulation import ManualPracticePolicy,ExecutionBlocked
from tests import test_telegram_manual as fixture

class AlertEntryTests(unittest.TestCase):
    def setUp(self):
        self.h=fixture.TelegramServiceTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.f=self.h.f;self.f.engine.policy=ManualPracticePolicy();self.f.market.fee_per_contract=None
        self.f.market.increments={};self.f.client.chain.side_effect=lambda *args:json.loads(json.dumps(self.f.payload))
        self.candle=self.f.state['tick']['signal']['candle']
        self.reference=AlertReference('AMZN','CALL',self.candle,self.f.now.isoformat(),self.f.now.isoformat(),
            self.f.state['tick']['version'],'ALPACA','iex',100.,104.,'ENVIADO')
        self.f.service.alert_reader=lambda symbol,side,candle:self.reference
        self.entry=FastManualEntry(self.h.service)

    def buy(self,**changes):
        fields=dict(symbol='AMZN',side='CALL',candle=self.candle,contract=self.f.code,quantity=3,
            target='35',ask='2.00',total='600',stop='10',request_id='1'*32)
        fields.update(changes)
        return self.entry.buy(self.h.raw(),**fields)

    def test_pullback_and_no_current_iex_trade_do_not_veto_delivered_alert(self):
        self.f.state['tick']['signal']=None;self.f.state['tick']['reason']='READY_NO_EXIT'
        for field in ('source_timestamp','received_at','checked_at'):
            self.f.state['tick'][field]=(self.f.now-timedelta(seconds=15)).isoformat()
        catalog=self.entry.catalog(self.h.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(catalog['buy_ready']);self.assertTrue(catalog['entry_authorized'])
        self.assertFalse(catalog['signal_ready']);self.assertEqual(self.f.engine.broker.snapshot(),[])
        result=self.buy();self.assertEqual(result['status'],'WORKING')
        self.assertEqual(self.f.engine.ledger.orders()[0]['order']['entry_basis'],'DELIVERED_ALERT_MANUAL_V1')
        self.assertEqual(self.f.client.full_chain.call_count,1);self.assertEqual(self.f.client.chain.call_count,1)
        self.assertEqual(self.f.client.chain.call_args.args[2],self.f.client.chain.call_args.args[3])

    def test_later_candle_same_session_keeps_manual_entry_with_fresh_quotes(self):
        self.f.quote(seconds=1000)
        self.f.payload['underlying']['quoteTime']=int(self.f.now.timestamp()*1000)
        self.f.state['tick']['signal']=None;self.f.state['tick']['reason']='READY_NO_EXIT'
        catalog=self.entry.catalog(self.h.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(catalog['buy_ready']);self.assertTrue(catalog['original_candle_ended'])
        self.assertEqual(catalog['entry_window'],'SAME_SESSION_MANUAL')
        self.assertEqual(catalog['recommended_contract'],self.f.code)
        result=self.buy();self.assertEqual(result['status'],'WORKING')
        self.assertEqual(len(self.f.engine.broker.snapshot()),1)

    def test_reference_cannot_cross_session_close_or_date(self):
        controls=self.f.service._controls(self.f.state)
        for now in (controls.session_closes,controls.session_closes+timedelta(days=1)):
            with self.assertRaises(ExecutionBlocked):validate_reference(self.reference,controls,now)
        next_controls=replace(controls,session_opens=controls.session_opens+timedelta(days=1),
            session_closes=controls.session_closes+timedelta(days=1))
        with self.assertRaisesRegex(ExecutionBlocked,'ALERT_WINDOW_ENDED'):
            validate_reference(self.reference,next_controls,self.f.now+timedelta(days=1))

    def test_catalog_ranks_valid_contracts_nearest_spot_not_provider_order(self):
        from tests.test_schwab_simulation import synthetic_contract
        market=self.f.market.get_chain('AMZN','CALL',self.f.now)
        quotes=tuple(synthetic_contract(now=self.f.now,strike=k) for k in (99.,103.,102.))
        market=replace(market,chain=replace(market.chain,contracts=quotes))
        with patch.object(self.f.market,'get_catalog_chain',return_value=market):
            result=self.entry.catalog(self.h.raw(),'AMZN','CALL',self.candle)
        self.assertEqual([c['strike'] for c in result['contracts']],[103.,102.,99.])
        self.assertEqual(result['recommended_contract'],quotes[1].snapshot.symbol)
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_opposite_current_detector_direction_does_not_change_call_from_notice(self):
        self.f.state['tick']['signal']['side']='INFERIOR'
        self.assertEqual(self.buy()['status'],'WORKING')
        self.assertIn('C',self.f.engine.ledger.orders()[0]['order']['contract'])

    def test_expired_old_two_minute_access_does_not_stop_explicit_alert_entry(self):
        raw=self.h.raw();self.f.quote(seconds=180);self.f.state['tick']['signal']=None
        self.f.payload['underlying']['quoteTime']=int(self.f.now.timestamp()*1000)
        data=self.entry.catalog(raw,'AMZN','CALL',self.candle)
        self.assertTrue(data['access_ready']);self.assertTrue(data['buy_ready'])
        with patch.object(self.h,'raw',return_value=raw):self.assertEqual(self.buy()['status'],'WORKING')

    def test_missing_undelivered_future_or_other_candle_alert_cannot_buy(self):
        for index,reference in enumerate((replace(self.reference,delivery_state='ENVIO_NO_CONFIRMADO'),
            replace(self.reference,candle=(self.f.now-timedelta(minutes=15)).replace(second=0).isoformat()),
            replace(self.reference,attempted_at=(self.f.now+timedelta(seconds=1)).isoformat()),
            replace(self.reference,version='old'))):
            self.f.service.alert_reader=lambda *args,r=reference:r
            self.assertEqual(self.buy(request_id=str(index).ljust(32,'x'))['status'],'ENTRY_BLOCKED')
            self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_stale_quotes_changed_ask_and_corrections_still_reject_without_dispatch(self):
        self.f.state['tick']['reason']='CORRECTION_QUARANTINE'
        self.assertEqual(self.buy()['status'],'ENTRY_BLOCKED');self.assertEqual(self.f.engine.broker.snapshot(),[])
        self.f.state['tick']['reason']='READY_NO_EXIT';self.f.state['tick']['signal']=None
        self.assertEqual(self.buy(request_id='2'*32,ask='2.01')['status'],'ENTRY_BLOCKED')
        q=self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q['quoteTimeInLong']-=31000;self.f.market.cache.clear()
        self.assertEqual(self.buy(request_id='3'*32)['status'],'ENTRY_BLOCKED')

    def test_duplicate_unknown_and_stop_exit_remain_protected(self):
        result=self.buy();self.assertEqual(result['status'],'WORKING')
        self.assertEqual(self.buy(request_id='2'*32)['intent'],result['intent'])
        self.f.quote(seconds=1);self.f.state['tick']['signal']=None;self.f.service.observe()
        self.assertEqual(self.f.engine.ledger.orders()[0]['status'],'FILLED')
        self.f.quote(bid=1.75,ask=1.80,seconds=2);self.f.state['tick']['signal']=None
        self.f.service.observe();self.assertEqual(len(self.f.engine.broker.snapshot()),2)

    def test_generic_automation_cannot_use_alert_confirmation(self):
        from tests.test_schwab_simulation import synthetic_policy,synthetic_contract
        self.f.engine.policy=synthetic_policy()
        entry=ManualAlertEntry(self.reference,104.,self.f.now,self.f.now)
        with self.assertRaisesRegex(ExecutionBlocked,'MANUAL_ALERT_PRACTICE_ONLY'):
            self.f.engine.enter(self.f.state['tick'],self.f.state['runtime'],self.f.service._controls(self.f.state),
                synthetic_contract(),self.f.now,self.f.now,manual_alert=entry)
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_reference_reader_uses_owner_and_alias_keys_readonly(self):
        from bollinger_phone_worker import candle_keys
        dbpath=self.f.root/'evidence.db';r=self.reference
        n=candle_keys('v1|123|ALPACA|iex|AMZN',r.candle,'SUPERIOR')[-1]
        e=candle_keys(r.version+'|ALPACA|iex|AMZN',r.candle,'SUPERIOR')[-1]
        payload=dict(symbol='AMZN',side='SUPERIOR',candle=r.candle,version=r.version,provider='ALPACA',feed='iex',
            opening=r.opening,price=r.detection_price,source_timestamp=r.source_timestamp)
        with closing(sqlite3.connect(dbpath)) as db,db:
            db.executescript('CREATE TABLE bollinger_phone_notifications(event_key TEXT PRIMARY KEY,state TEXT,attempted_at TEXT);'
                'CREATE TABLE bollinger_live_events(event_key TEXT PRIMARY KEY,payload_json TEXT);')
            db.execute('INSERT INTO bollinger_phone_notifications VALUES(?,?,?)',(n,'ENVIADO',r.attempted_at))
            db.execute('INSERT INTO bollinger_live_events VALUES(?,?)',(e,json.dumps(payload)))
        before=dbpath.read_bytes()
        self.assertEqual(read_alert_reference(dbpath,'AMZN','CALL',r.candle,'123'),r)
        with self.assertRaisesRegex(RuntimeError,'DELIVERED_ALERT_REQUIRED'):
            read_alert_reference(dbpath,'AMZN','CALL',r.candle,'other')
        self.assertEqual(before,dbpath.read_bytes())

    def test_legacy_delivered_reference_remains_explicit_manual_only(self):
        from bollinger_phone_worker import EVENT_KEY_VERSION
        old=replace(self.reference,version=EVENT_KEY_VERSION)
        validate_reference(old,self.f.service._controls(self.f.state),self.f.now)

    def test_legacy_chat_and_readonly_watch_do_not_reintroduce_pullback_veto(self):
        self.f.state['tick']['signal']=None;self.f.state['tick']['reason']='READY_NO_EXIT'
        watch=self.h.service.watch(self.h.raw(),'AMZN','CALL',self.candle)
        self.assertTrue(watch['entry_authorized']);self.assertIsNone(watch['signal_price'])
        draft=self.h.service.begin('AMZN','CALL',self.candle)
        self.assertIn('AMZN',self.h.service.card(draft)['text'])
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_inferior_alert_buys_put_despite_current_superior_detector(self):
        self.reference=replace(self.reference,side='PUT')
        code='AMZN  261023P00110000'
        q=self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        q.update(symbol=code,putCall='PUT',strikePrice=110,delta=-.6)
        self.f.payload['callExpDateMap']={};self.f.payload['putExpDateMap']={'2026-10-23:7':{'110.0':[q]}}
        self.assertEqual(self.buy(side='PUT',contract=code)['status'],'WORKING')
        self.assertEqual(self.f.engine.ledger.orders()[0]['order']['contract'],code)

    def test_unknown_accepted_order_by_alert_is_not_resubmitted(self):
        accept=self.f.engine.broker.accept
        def lost(*args,**kwargs):
            accept(*args,**kwargs);raise TimeoutError('SYNTHETIC_PRIVATE_DETAIL')
        with patch.object(self.f.engine.broker,'accept',side_effect=lost) as call:
            first=self.buy();second=self.buy(request_id='2'*32)
        self.assertEqual(first['status'],'UNKNOWN');self.assertEqual(second['intent'],first['intent'])
        self.assertEqual(call.call_count,1);self.assertEqual(len(self.f.engine.broker.snapshot()),1)
        self.assertNotIn('SYNTHETIC_PRIVATE_DETAIL',str(second))

    def test_selected_expiry_lookup_preserves_full_calendar_and_falls_back_if_old(self):
        full=self.f.market.get_chain('AMZN','CALL',self.f.now)
        partial=self.f.market.get_entry_chain('AMZN','CALL',self.f.code,self.f.now)
        self.assertEqual(partial.expirations,full.expirations)
        self.assertIs(self.f.market.cache[('AMZN','CALL')],full)
        self.assertEqual(self.f.client.chain.call_count,1)
        self.f.market.get_entry_chain('AMZN','CALL',self.f.code,self.f.now+timedelta(seconds=31))
        self.assertEqual(self.f.client.full_chain.call_count,2)

    def test_catalog_refreshes_only_selected_expiry_and_never_poisons_complete_calendar(self):
        first=self.f.market.get_catalog_chain('AMZN','CALL',self.f.now)
        now=self.f.now+timedelta(seconds=6)
        partial=self.f.market.get_catalog_chain('AMZN','CALL',now)
        self.assertEqual(self.f.client.full_chain.call_count,1)
        self.assertEqual(self.f.client.chain.call_count,1)
        self.assertIs(self.f.market.cache[('AMZN','CALL')],first)
        self.assertEqual(partial.expirations,first.expirations)
        self.assertIs(self.f.market.get_catalog_chain('AMZN','CALL',now+timedelta(seconds=1)),partial)
        self.assertEqual(self.f.client.chain.call_count,1)
        self.f.market.get_catalog_chain('AMZN','CALL',self.f.now+timedelta(seconds=31))
        self.assertEqual(self.f.client.full_chain.call_count,2)

    def test_blocked_buy_reason_survives_catalog_refresh_without_resubmission(self):
        payload=json.loads(json.dumps(self.f.payload))
        payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['bid']=1.50
        self.f.client.chain.side_effect=lambda *a:payload
        result=self.buy()
        self.assertEqual(result['status'],'ENTRY_BLOCKED')
        self.assertEqual(result['reason'],'CONTRACT_NO_LONGER_ELIGIBLE')
        catalog=self.entry.catalog(self.h.raw(),'AMZN','CALL',self.candle)
        self.assertEqual(catalog['last_entry_result']['reason'],'CONTRACT_NO_LONGER_ELIGIBLE')
        self.assertTrue(catalog['buy_ready'])
        self.assertEqual(self.f.engine.broker.snapshot(),[])

    def test_newly_valid_catalog_quote_can_be_refreshed_without_old_full_quote(self):
        quote=self.f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        quote['bid']=0
        first=self.f.market.get_catalog_chain('AMZN','CALL',self.f.now)
        self.assertEqual(first.chain.contracts,())
        quote['bid']=1.95
        now=self.f.now+timedelta(seconds=6)
        current=self.f.market.get_catalog_chain('AMZN','CALL',now)
        self.assertEqual(len(current.chain.contracts),1)
        refreshed=self.f.market.get_entry_chain('AMZN','CALL',self.f.code,now)
        self.assertEqual(len(refreshed.chain.contracts),1)
        self.assertIs(self.f.market.cache[('AMZN','CALL')],first)
        self.assertEqual(self.f.client.full_chain.call_count,1)
        self.assertEqual(self.f.client.chain.call_count,2)
