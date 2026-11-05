"""Synthetic option request bodies; no real broker calls or credentials."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone,date
from decimal import Decimal
from unittest import TestCase

from option_market_data import OptionSnapshot
from schwab_contracts import SchwabContract
from schwab_connection import SchwabError
from schwab_option_order_request import prepare_option_limit

NOW=datetime(2026,11,2,14,30,1,tzinfo=timezone.utc)


def contract(side='CALL',**changes):
    q=OptionSnapshot(symbol='AAPL  261102'+('C' if side=='CALL' else 'P')+'00350000',
        underlying_symbol='AAPL',option_type=side,strike=350.,expiration=date(2026,11,2),
        bid=.95,ask=1.,bid_size=10,ask_size=10,quote_timestamp=NOW,latest_trade=None,
        implied_volatility=None,delta=None,gamma=None,theta=None,vega=None,feed='SCHWAB')
    return SchwabContract(replace(q,**changes),100,True,Decimal('.01'))


class OptionLimitRequestTests(TestCase):
    def prepare(self,**changes):
        args=dict(instruction='BUY_TO_OPEN',quantity=2,now=NOW,valid_until=NOW+timedelta(seconds=10))
        args.update(changes);return prepare_option_limit(contract(),**args)

    def test_call_and_put_buy_request_use_exact_documented_values_and_ask(self):
        for side in ('CALL','PUT'):
            c=contract(side);draft=prepare_option_limit(c,instruction='BUY_TO_OPEN',quantity=2,
                now=NOW,valid_until=NOW+timedelta(seconds=5))
            body=draft.payload(NOW)
            self.assertEqual(body,dict(session='NORMAL',duration='DAY',orderType='LIMIT',
                orderStrategyType='SINGLE',price='1.0',orderLegCollection=[dict(instruction='BUY_TO_OPEN',
                    quantity=2,instrument=dict(symbol=c.snapshot.symbol,assetType='OPTION'))]))
            self.assertNotIn('accountNumber',body);self.assertNotIn('orderId',body)
            self.assertNotIn('filledQuantity',body);self.assertNotIn('stopPrice',body)

    def test_close_bid_and_explicit_target_limit_use_sell_to_close(self):
        bid=self.prepare(instruction='SELL_TO_CLOSE').payload(NOW)
        target=self.prepare(instruction='SELL_TO_CLOSE',close_limit='1.20').payload(NOW)
        self.assertEqual(bid['price'],'0.95');self.assertEqual(target['price'],'1.20')
        self.assertEqual(target['orderLegCollection'][0]['instruction'],'SELL_TO_CLOSE')

    def test_short_opening_and_market_instructions_are_not_supported(self):
        for instruction in ('SELL_TO_OPEN','BUY_TO_CLOSE','BUY','SELL','MARKET','UNKNOWN'):
            with self.subTest(instruction=instruction),self.assertRaises(SchwabError):self.prepare(instruction=instruction)
        with self.assertRaisesRegex(SchwabError,'BUY_LIMIT_MUST_BE_ASK'):self.prepare(close_limit='1.10')

    def test_whole_positive_contracts_only(self):
        for quantity in (True,0,-1,1.5,'1'):
            with self.subTest(quantity=quantity),self.assertRaises(ValueError):self.prepare(quantity=quantity)

    def test_unknown_or_off_tick_increment_is_not_inferred_or_rounded(self):
        for c in (replace(contract(),price_increment=None),replace(contract(),price_increment=Decimal('.03'))):
            with self.assertRaises((ValueError,SchwabError)):prepare_option_limit(c,instruction='BUY_TO_OPEN',quantity=1,
                now=NOW,valid_until=NOW+timedelta(seconds=5))
        with self.assertRaisesRegex(SchwabError,'VERIFIED_INCREMENT'):
            self.prepare(instruction='SELL_TO_CLOSE',close_limit='1.005')

    def test_future_stale_or_expired_quote_is_not_a_sendable_draft(self):
        for stamp in (NOW+timedelta(seconds=1),NOW-timedelta(seconds=30)):
            with self.subTest(stamp=stamp),self.assertRaises(SchwabError):
                prepare_option_limit(contract(quote_timestamp=stamp),instruction='BUY_TO_OPEN',quantity=1,
                    now=NOW,valid_until=NOW+timedelta(seconds=5))
        with self.assertRaises(SchwabError):self.prepare(now=NOW+timedelta(days=1))
        later=NOW+timedelta(days=1)
        with self.assertRaisesRegex(SchwabError,'CONTRACT_EXPIRED'):
            prepare_option_limit(contract(quote_timestamp=later),instruction='BUY_TO_OPEN',quantity=1,
                now=later,valid_until=later+timedelta(seconds=5))

    def test_signal_deadline_is_preserved_and_serialization_rechecks_it(self):
        draft=self.prepare(valid_until=NOW+timedelta(seconds=2))
        self.assertEqual(draft.expires_at,NOW+timedelta(seconds=2))
        with self.assertRaisesRegex(SchwabError,'NOT_CURRENT'):draft.payload(NOW+timedelta(seconds=2))
        with self.assertRaisesRegex(SchwabError,'NOT_CURRENT'):draft.payload(NOW-timedelta(microseconds=1))
        self.assertEqual(self.prepare(valid_until=NOW+timedelta(minutes=5)).expires_at,NOW+timedelta(seconds=30))

    def test_adjusted_contract_or_identity_mismatch_is_rejected(self):
        for c in (replace(contract(),multiplier=10),replace(contract(),standard_deliverable=False),contract(strike=351.)):
            with self.assertRaises(ValueError):prepare_option_limit(c,instruction='BUY_TO_OPEN',quantity=1,
                now=NOW,valid_until=NOW+timedelta(seconds=5))
