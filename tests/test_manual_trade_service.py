"""Synthetic market-state/proposal checks, no active database or real API."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta,date,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import traceback
import unittest
from unittest.mock import Mock

from manual_trade_service import (ManualDataError,ManualMarketData,read_manual_state,
    current_manual_signal,decode_manual_chain,manual_candidates)
from schwab_connection import SchwabError
from tests.test_schwab_simulation import NOW,synthetic_signal,synthetic_contract


def state_fixture(now=NOW):
    tick=synthetic_signal()
    for field in ('source_timestamp','received_at','checked_at'):tick[field]=now.isoformat()
    tick['signal']['candle']=now.replace(minute=15*(now.minute//15),second=0,microsecond=0).isoformat()
    radar=deepcopy(tick);radar['data_reason']='EXIT'
    return {'session':(now.replace(hour=13,minute=30,second=0).isoformat(),
                       now.replace(hour=20,minute=0,second=0).isoformat()),
        'runtime':{'state':'CONECTADO','feed':'iex','heartbeat':now.isoformat(),'symbols':['AMZN']},
        'tick':tick,'radar':radar}


def payload_fixture():
    q=synthetic_contract().snapshot
    item={'symbol':q.symbol,'putCall':'CALL','strikePrice':q.strike,
          'expirationDate':q.expiration.isoformat()+'T20:00:00Z','bid':q.bid,'ask':q.ask,
          'bidSize':10,'askSize':10,'quoteTimeInLong':int(NOW.timestamp()*1000),
          'nonStandard':False,'multiplier':100,'delta':.6}
    return {'symbol':'AMZN','isDelayed':False,
        'underlying':{'last':104.,'quoteTime':int(NOW.timestamp()*1000)},
        'callExpDateMap':{'2026-10-23:7':{'100.0':[item]}},'putExpDateMap':{}}


class ManualTradeServiceTests(unittest.TestCase):
    def test_state_reader_is_readonly_bounded_and_does_not_create_missing_db(self):
        state=state_fixture()
        with tempfile.TemporaryDirectory() as temp:
            dbpath=Path(temp)/'isolated.db'
            with closing(sqlite3.connect(dbpath)) as db,db:
                db.executescript('CREATE TABLE market_sessions(session_date TEXT PRIMARY KEY,opens_at TEXT,closes_at TEXT);'
                    'CREATE TABLE bollinger_tick_runtime(id INTEGER PRIMARY KEY,state TEXT,heartbeat TEXT,feed TEXT,symbols_json TEXT);'
                    'CREATE TABLE bollinger_tick_latest(symbol TEXT PRIMARY KEY,payload_json TEXT);'
                    'CREATE TABLE bollinger_radar_state(symbol TEXT PRIMARY KEY,payload_json TEXT);')
                db.execute('INSERT INTO market_sessions VALUES(?,?,?)',(NOW.date().isoformat(),*state['session']))
                db.execute('INSERT INTO bollinger_tick_runtime VALUES(1,?,?,?,?)',('CONECTADO',NOW.isoformat(),'iex','["AMZN"]'))
                db.execute('INSERT INTO bollinger_tick_latest VALUES(?,?)',('AMZN',json.dumps(state['tick'])))
                db.execute('INSERT INTO bollinger_radar_state VALUES(?,?)',('AMZN',json.dumps(state['radar'])))
            before=hashlib.sha256(dbpath.read_bytes()).hexdigest()
            actual=read_manual_state(dbpath,'AMZN',NOW.date())
            self.assertEqual(current_manual_signal(actual,'AMZN',NOW),state['tick'])
            self.assertEqual(hashlib.sha256(dbpath.read_bytes()).hexdigest(),before)
            with closing(sqlite3.connect(dbpath,timeout=.1)) as db,db:
                db.execute("UPDATE bollinger_tick_runtime SET heartbeat=? WHERE id=1",(NOW.isoformat(),))
            missing=Path(temp)/'missing.db'
            with self.assertRaises(ManualDataError):read_manual_state(missing,'AMZN',NOW.date())
            self.assertFalse(missing.exists())

    def test_stale_future_disconnected_retracted_quarantined_and_wrong_side_block(self):
        changes=[('runtime','heartbeat',(NOW-timedelta(seconds=4)).isoformat()),
            ('runtime','heartbeat',(NOW+timedelta(microseconds=1)).isoformat()),
            ('runtime','state','DESCONECTADO'),('runtime','feed','sip'),
            ('tick','reason','CORRECTION_QUARANTINE'),('tick','signal',None),
            ('tick','source_timestamp',(NOW+timedelta(microseconds=1)).isoformat())]
        for section,key,value in changes:
            state=state_fixture();state[section][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ManualDataError):
                current_manual_signal(state,'AMZN',NOW)
        state=state_fixture();state['session']=None
        with self.assertRaisesRegex(ManualDataError,'OUTSIDE_OFFICIAL_SESSION'):
            current_manual_signal(state,'AMZN',NOW)
        state=state_fixture();state['tick']['signal']['side']='UNKNOWN'
        with self.assertRaises(ManualDataError):current_manual_signal(state,'AMZN',NOW)

    def test_async_dashboard_projection_cannot_veto_current_canonical_detector(self):
        from schwab_simulation import validated_signal,DataControls
        controls=DataControls(True,True,True,datetime.fromisoformat(state_fixture()['session'][0]),
            datetime.fromisoformat(state_fixture()['session'][1]))
        for radar in (None,{},dict(state_fixture()['radar'],signal=None),
                      dict(state_fixture()['radar'],checked_at=(NOW-timedelta(seconds=10)).isoformat())):
            state=state_fixture();state['radar']=radar
            self.assertEqual(validated_signal(state['tick'],state['runtime'],controls,NOW)['option_type'],'CALL')
            self.assertEqual(current_manual_signal(state,'AMZN',NOW),state['tick'])
        state=state_fixture();state['tick']['signal']=None
        with self.assertRaisesRegex(ManualDataError,'NO_CURRENT_SIGNAL'):
            current_manual_signal(state,'AMZN',NOW)

    def test_missing_current_price_evidence_is_not_mislabeled_as_a_retraction(self):
        state=state_fixture();state['tick']['source_timestamp']=(NOW-timedelta(seconds=4)).isoformat()
        with self.assertRaisesRegex(ManualDataError,'TRADE_NOT_CURRENT'):
            current_manual_signal(state,'AMZN',NOW)
        state['tick']['signal']=None;state['tick']['reason']='READY_NO_EXIT'
        with self.assertRaisesRegex(ManualDataError,'TRADE_NOT_CURRENT'):
            current_manual_signal(state,'AMZN',NOW)

    def test_candidates_use_current_iex_signal_not_ambiguous_chain_last(self):
        payload=payload_fixture();payload['underlying']['last']=1.0
        market=decode_manual_chain(payload,'AMZN','CALL',NOW)
        tick,expiry,contracts=manual_candidates(state_fixture(),market,'AMZN','CALL',NOW)
        self.assertEqual(expiry,date(2026,10,23));self.assertEqual(len(contracts),1)
        self.assertEqual(tick['signal']['price'],104.)
        self.assertIsNone(contracts[0].price_increment)  #Preview is not execution readiness.
        with self.assertRaisesRegex(ManualDataError,'DIRECTION_CHANGED'):
            manual_candidates(state_fixture(),market,'AMZN','PUT',NOW)

    def test_calendar_includes_nearest_dates_even_if_their_quotes_are_rejected(self):
        payload=payload_fixture();item=deepcopy(payload['callExpDateMap']['2026-10-23:7']['100.0'][0])
        item.update(symbol='AMZN  261016C00100000',expirationDate='2026-10-16T20:00:00Z',bid=0)
        payload['callExpDateMap']['2026-10-16:0']={'100.0':[item]}
        market=decode_manual_chain(payload,'AMZN','CALL',NOW)
        _,expiry,contracts=manual_candidates(state_fixture(),market,'AMZN','CALL',NOW)
        self.assertEqual(expiry,date(2026,10,16));self.assertEqual(contracts,())
        self.assertEqual(market.chain.rejected_contracts,1)

    def test_stale_quotes_do_not_become_current_due_to_recent_fetch(self):
        later=NOW+timedelta(seconds=31)
        market=decode_manual_chain(payload_fixture(),'AMZN','CALL',later)
        _,_,contracts=manual_candidates(state_fixture(later),market,'AMZN','CALL',later)
        self.assertEqual(contracts,())
        with self.assertRaisesRegex(ManualDataError,'CHAIN_NOT_CURRENT'):
            manual_candidates(state_fixture(later),replace(market,fetched_at=NOW),'AMZN','CALL',later)

    def test_shared_cache_and_provider_retry_after_do_not_loop_requests(self):
        client=Mock();client.full_chain.return_value=payload_fixture()
        service=ManualMarketData(client)
        first=service.get_chain('AMZN','CALL',NOW)
        self.assertIs(service.get_chain('AMZN','CALL',NOW+timedelta(seconds=4)),first)
        client.full_chain.assert_called_once()
        client.full_chain.side_effect=SchwabError('RATE_LIMITED',http_status=429,retry_after_seconds=60)
        with self.assertRaisesRegex(ManualDataError,'RATE_LIMITED'):
            service.get_chain('AMZN','CALL',NOW+timedelta(seconds=6))
        with self.assertRaisesRegex(ManualDataError,'COOLDOWN'):
            service.get_chain('AMZN','CALL',NOW+timedelta(seconds=30))
        self.assertEqual(client.full_chain.call_count,2)
        client.accounts.assert_not_called();client.positions.assert_not_called();client.orders.assert_not_called()

    def test_raw_private_exception_is_not_exposed(self):
        client=Mock();client.full_chain.side_effect=RuntimeError('SYNTHETIC_SECRET')
        try:ManualMarketData(client).get_chain('AMZN','CALL',NOW)
        except ManualDataError as error:
            self.assertEqual(str(error),'MARKET_DATA_UNAVAILABLE')
            self.assertNotIn('SYNTHETIC_SECRET',''.join(traceback.format_exception(error)))
        else:self.fail('Expected redacted error')


if __name__=='__main__':unittest.main()
