"""Real-quote schema fixture, no API/vault/active database."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock
import unittest
from manual_trade_service import ManualMarketData,decode_manual_chain,ManualDataError
from selected_option_quotes import refresh_selected
from tests.test_manual_trade_service import NOW,payload_fixture


class SelectedQuoteTests(unittest.TestCase):
    def setUp(self):
        self.market=decode_manual_chain(payload_fixture(),'AMZN','CALL',NOW)
        self.code=self.market.chain.contracts[0].snapshot.symbol
        stamp=int(NOW.timestamp()*1000)
        self.payload={'AMZN':dict(symbol='AMZN',assetMainType='EQUITY',realtime=True,
            quote=dict(lastPrice=104.,quoteTime=stamp,securityStatus='Normal')),
            self.code:dict(symbol=self.code,assetMainType='OPTION',realtime=True,
                reference=dict(underlying='AMZN',contractType='C',strikePrice=100.,
                    expirationYear=2026,expirationMonth=10,expirationDay=23,multiplier=100.,deliverables='100 AMZN'),
                quote=dict(bidPrice=1.96,askPrice=2.01,bidSize=10,askSize=10,quoteTime=stamp,securityStatus='Normal'))}

    def test_batched_quote_refresh_preserves_identity_and_actual_provider_time(self):
        result=refresh_selected(self.market,self.code,self.payload,NOW+timedelta(seconds=8))
        c=result.chain.contracts[0]
        self.assertEqual(c.snapshot.symbol,self.code);self.assertEqual(c.snapshot.ask,2.01)
        self.assertEqual(c.snapshot.quote_timestamp,NOW)
        self.assertEqual(result.chain.underlying_timestamp,NOW)
        self.assertEqual(result.expirations,self.market.expirations)
        self.assertIsNone(self.market.chain.contracts[0].price_increment)

    def test_delayed_halted_wrong_identity_or_adjusted_cannot_refresh(self):
        for changes in ('delay','numeric_realtime','halt','strike','expiry','delivery','root','side'):
            p=deepcopy(self.payload);o=p[self.code]
            if changes=='delay':o['realtime']=False
            if changes=='numeric_realtime':o['realtime']=1
            if changes=='halt':o['quote']['securityStatus']='Halted'
            if changes=='strike':o['reference']['strikePrice']=101
            if changes=='expiry':o['reference']['expirationDay']=24
            if changes=='delivery':o['reference']['deliverables']='10 AMZN'
            if changes=='root':o['reference']['underlying']='OTHER'
            if changes=='side':o['reference']['contractType']='P'
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                refresh_selected(self.market,self.code,p,NOW)

    def test_future_and_old_quotes_remain_ineligible_not_restamped(self):
        from option_contract_selection import entry_candidates
        for delta in (-31,1):
            p=deepcopy(self.payload);p[self.code]['quote']['quoteTime']=int((NOW+timedelta(seconds=delta)).timestamp()*1000)
            m=refresh_selected(self.market,self.code,p,NOW)
            self.assertEqual(entry_candidates([c.snapshot for c in m.chain.contracts],symbol='AMZN',side='CALL',
                underlying_price=m.chain.underlying_price,underlying_stamp=m.chain.underlying_timestamp,
                as_of=NOW,listed_expirations=m.expirations),[])

    def test_entry_uses_single_batch_get_and_does_not_poison_calendar(self):
        client=Mock();client.full_chain.return_value=payload_fixture();client.quotes.return_value=self.payload
        data=ManualMarketData(client,direct_quotes=True)
        full=data.get_chain('AMZN','CALL',NOW)
        result=data.get_entry_chain('AMZN','CALL',self.code,NOW+timedelta(seconds=40))
        self.assertEqual(client.full_chain.call_count,1);client.chain.assert_not_called()
        client.quotes.assert_called_once_with(['AMZN',self.code],NOW+timedelta(seconds=40))
        self.assertIs(data.cache[('AMZN','CALL')],full)
        self.assertEqual(result.chain.contracts[0].snapshot.quote_timestamp,NOW)
        data.get_entry_chain('AMZN','CALL',self.code,NOW+timedelta(seconds=301))
        self.assertEqual(client.full_chain.call_count,2)

    def test_batch_failure_is_not_silently_replaced_by_old_quote(self):
        client=Mock();client.full_chain.return_value=payload_fixture();client.quotes.side_effect=TimeoutError()
        data=ManualMarketData(client,direct_quotes=True);data.get_chain('AMZN','CALL',NOW)
        with self.assertRaisesRegex(ManualDataError,'MARKET_DATA_UNAVAILABLE'):
            data.get_entry_chain('AMZN','CALL',self.code,NOW)
        client.chain.assert_not_called()

    def test_monitor_cache_one_second_never_replaces_forced_confirmation(self):
        client=Mock();client.full_chain.return_value=payload_fixture();client.quotes.return_value=self.payload
        data=ManualMarketData(client,direct_quotes=True);data.get_chain('AMZN','CALL',NOW)
        first=data.get_entry_chain('AMZN','CALL',self.code,NOW)
        self.assertIs(data.get_entry_chain('AMZN','CALL',self.code,NOW+timedelta(milliseconds=500),force=False),first)
        self.assertEqual(client.quotes.call_count,1)
        data.get_entry_chain('AMZN','CALL',self.code,NOW+timedelta(milliseconds=500))
        self.assertEqual(client.quotes.call_count,2)

    def test_complete_buy_fill_monitor_manual_sale_with_direct_quotes(self):
        from tests.test_manual_alert_entry import AlertEntryTests
        fixture=AlertEntryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        f=fixture.f;f.market.direct_quotes=True
        def quote(*args):
            p=deepcopy(self.payload);q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
            p[f.code]['quote'].update(bidPrice=q['bid'],askPrice=q['ask'],quoteTime=q['quoteTimeInLong'])
            p['AMZN']['quote']['quoteTime']=q['quoteTimeInLong'];return p
        f.client.quotes.side_effect=quote
        result=fixture.buy(target='MANUAL');self.assertEqual(result['status'],'WORKING')
        f.quote(seconds=1);f.service.observe()
        receipt=fixture.h.service.state(fixture.h.raw(),result['intent'])
        self.assertEqual(receipt['status'],'FILLED');self.assertTrue(receipt['position_open'])
        f.quote(bid=2.10,ask=2.15,seconds=3)
        receipt=fixture.h.service.state(fixture.h.raw(),result['intent']);self.assertEqual(str(receipt['mark']['bid']),'2.1')
        review=fixture.h.service.prepare_action(fixture.h.raw(),result['intent'],'close')
        fixture.h.service.confirm_action(fixture.h.raw(),result['intent'],review['id'])
        f.quote(bid=2.10,ask=2.15,seconds=5);f.service.observe()
        final=fixture.h.service.state(fixture.h.raw(),result['intent'])
        self.assertFalse(final['position_open']);self.assertEqual(final['sale_report']['status'],'CLOSED')
        self.assertEqual(len(f.engine.ledger.orders()),2)

    def test_direct_quotes_keep_target_and_stop_exits_even_outside_entry_range(self):
        from tests.test_manual_alert_entry import AlertEntryTests
        for target,bid,ask,reason in [('35',2.70,2.75,'TARGET'),('MANUAL',1.79,1.84,'LOSS_LIMIT')]:
            h=AlertEntryTests();h.setUp()
            try:
                f=h.f;f.market.direct_quotes=True
                def quote(*args):
                    p=deepcopy(self.payload);q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
                    p[f.code]['quote'].update(bidPrice=q['bid'],askPrice=q['ask'],quoteTime=q['quoteTimeInLong'])
                    p['AMZN']['quote']['quoteTime']=q['quoteTimeInLong'];return p
                f.client.quotes.side_effect=quote
                result=h.buy(target=target);self.assertEqual(result['status'],'WORKING')
                f.quote(seconds=1);f.service.observe()
                f.quote(bid=bid,ask=ask,seconds=3);f.service.observe()
                f.quote(bid=bid,ask=ask,seconds=5);f.service.observe()
                receipt=h.h.service.state(h.h.raw(),result['intent'])
                self.assertEqual(receipt['sale_report']['status'],'CLOSED')
                self.assertIn(reason,receipt['sale_report']['reasons'])
                self.assertEqual(len(f.engine.ledger.orders()),2)
            finally:h.doCleanups()

    def test_real_http_refresh_purchase_receipt_monitor_and_close(self):
        from contextlib import contextmanager
        from threading import Thread
        import http.client,json
        from telegram_manual_http import LoopbackServer,handler_for
        from tests.test_manual_alert_entry import AlertEntryTests
        h=AlertEntryTests();h.setUp();self.addCleanup(h.doCleanups)
        f=h.f;f.market.direct_quotes=True
        def quote(*args):
            p=deepcopy(self.payload);q=f.payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
            p[f.code]['quote'].update(bidPrice=q['bid'],askPrice=q['ask'],quoteTime=q['quoteTimeInLong'])
            p['AMZN']['quote']['quoteTime']=q['quoteTimeInLong'];return p
        f.client.quotes.side_effect=quote
        server=LoopbackServer(('127.0.0.1',0),handler_for(h.h.service))
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        def post(route,body):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                connection.request('POST','/api/'+route,json.dumps(dict(init_data=h.h.raw(),**body)),
                    {'Origin':h.h.service.origin,'Content-Type':'application/json'})
                response=connection.getresponse();data=json.loads(response.read())
                self.assertEqual(response.status,200);return data
            finally:connection.close()
        try:
            reference=dict(symbol='AMZN',side='CALL',candle=h.candle)
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                connection.request('POST','/api/entry-refresh',json.dumps(dict(init_data='forged',contract=f.code,**reference)),
                    {'Origin':h.h.service.origin,'Content-Type':'application/json'})
                response=connection.getresponse();response.read();self.assertEqual(response.status,403)
            finally:connection.close()
            self.assertEqual(f.engine.ledger.orders(),[])
            self.assertTrue(post('entry-catalog',reference)['buy_ready'])
            refreshed=post('entry-refresh',dict(reference,contract=f.code))
            self.assertTrue(refreshed['buy_ready']);self.assertEqual(len(f.engine.ledger.orders()),0)
            buy=post('entry-buy',dict(reference,contract=f.code,quantity=3,target='MANUAL',ask='2.00',
                total='600',stop='10',request_id='a'*32))
            self.assertEqual(buy['status'],'WORKING');self.assertIn('selection',buy);self.assertIn('intent',buy)
            ref=dict(intent=buy['intent'])
            self.assertEqual(post('state',ref)['filled_quantity'],0)
            f.quote(seconds=1);f.service.observe();self.assertTrue(post('state',ref)['position_open'])
            f.quote(bid=2.10,ask=2.15,seconds=3);self.assertEqual(str(post('state',ref)['mark']['bid']),'2.1')
            review=post('prepare',dict(ref,action='close',order_key=None))
            post('confirm',dict(ref,review_id=review['id']))
            f.quote(bid=2.10,ask=2.15,seconds=5);f.service.observe()
            self.assertEqual(post('state',ref)['sale_report']['status'],'CLOSED')
            self.assertEqual(len(f.engine.ledger.orders()),2)
        finally:server.shutdown();server.server_close();thread.join(3)

if __name__=='__main__':unittest.main()
