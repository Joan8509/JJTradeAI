"""Valuation/quote-time regressions; no broker, account or market IO."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest

from option_exit_plan import ExitPlan
from position_monitor import position_mark,append_bid_observation
from tests import test_schwab_simulation as f


def position_fixture(**changes):
    q=f.synthetic_contract().snapshot
    return dict(contract=q.symbol,symbol='AMZN',side='CALL',quantity=3,average_fill='2',
        entry_fees='1.95',exit_fee_per_contract='.65',entry_client_key='SYNTHETIC_ENTRY',
        plan=ExitPlan('TARGET_PERCENT',Decimal('20'),Decimal('20'),30).payload('.05'),**changes)


def market_fixture(now=f.NOW,**changes):
    return dict(snapshot=f.synthetic_contract(now,bid=2.3,ask=2.35).snapshot,
        underlying_price=104,underlying_timestamp=now,session_open=True,**changes)


class PositionMonitorTests(unittest.TestCase):
    def test_bid_liquidation_gross_and_net_using_remaining_executed_position(self):
        mark=position_mark(position_fixture(),market_fixture(),now=f.NOW)
        self.assertEqual(mark['status'],'LIVE');self.assertEqual(mark['value'],Decimal('690'))
        self.assertEqual(mark['gross_pnl'],Decimal('90'));self.assertEqual(mark['gross_pct'],Decimal('15'))
        self.assertEqual(mark['net_estimate'],Decimal('86.10'))
        self.assertEqual(mark['target'],Decimal('2.40'));self.assertEqual(mark['stop'],Decimal('1.6'))
        self.assertNotEqual(mark['gross_pnl'],Decimal('105')) #Ask is not a liquidation price.

    def test_loss_uses_option_price_not_underlying_or_call_put_direction(self):
        p=position_fixture();m=market_fixture();m['snapshot']=replace(m['snapshot'],bid=1.6,ask=1.65)
        m['underlying_price']=10000
        mark=position_mark(p,m,now=f.NOW)
        self.assertEqual(mark['gross_pnl'],Decimal('-120'));self.assertEqual(mark['gross_pct'],Decimal('-20'))
        p['side']='PUT';p['contract']=f.synthetic_contract(side='PUT',strike=105).snapshot.symbol
        m['snapshot']=f.synthetic_contract(bid=1.6,ask=1.65,side='PUT',strike=105).snapshot
        self.assertEqual(position_mark(p,m,now=f.NOW)['gross_pct'],Decimal('-20'))

    def test_partial_remaining_position_costs_and_vwap(self):
        p=position_fixture();p.update(quantity=1,average_fill='1.983333333333333333333333333',entry_fees='.65')
        mark=position_mark(p,market_fixture(),now=f.NOW)
        self.assertEqual(mark['target'],Decimal('2.40'))
        self.assertAlmostEqual(mark['gross_pnl'],(Decimal('2.3')-Decimal(p['average_fill']))*100,places=20)
        self.assertEqual(mark['net_estimate'],mark['gross_pnl']-Decimal('1.30'))

    def test_stale_future_closed_unavailable_never_show_current_profit(self):
        for mode in ('STALE','FUTURE','CLOSED','UNAVAILABLE'):
            with self.subTest(mode=mode):
                m=market_fixture()
                if mode=='STALE':m['snapshot']=replace(m['snapshot'],quote_timestamp=f.NOW-timedelta(seconds=30,microseconds=1))
                if mode=='FUTURE':m['snapshot']=replace(m['snapshot'],quote_timestamp=f.NOW+timedelta(microseconds=1))
                if mode=='CLOSED':m['session_open']=False
                mark=position_mark(position_fixture(),m,now=f.NOW,unavailable=mode=='UNAVAILABLE')
                self.assertEqual(mark['status'],mode);self.assertIsNone(mark['gross_pnl']);self.assertIsNone(mark['value'])
                self.assertIsNone(mark['net_estimate']);self.assertEqual(mark['bid'],Decimal('2.3'))
                self.assertEqual(mark['stop'],Decimal('1.6'))

    def test_thirty_seconds_is_inclusive_and_unknown_costs_are_not_free(self):
        p=position_fixture();p['entry_fees']=None
        m=market_fixture(f.NOW-timedelta(seconds=30))
        mark=position_mark(p,m,now=f.NOW)
        self.assertEqual(mark['status'],'LIVE');self.assertIsNone(mark['net_estimate'])
        p['entry_fees']='1.95';p['exit_fee_per_contract']=None
        self.assertIsNone(position_mark(p,m,now=f.NOW)['net_estimate'])

    def test_missing_or_wrong_identity_feed_crossed_or_invalid_timestamp_blocks(self):
        self.assertEqual(position_mark(position_fixture(),None,now=f.NOW)['status'],'UNAVAILABLE')
        for changes in ({'feed':'iex'},{'symbol':'WRONG'},{'underlying_symbol':'SPY'},{'option_type':'PUT'},
                        {'bid':0},{'bid':3.,'ask':2.},{'bid_size':0},{'quote_timestamp':None},
                        {'quote_timestamp':f.NOW.replace(tzinfo=None)}):
            with self.subTest(changes=changes):
                m=market_fixture();m['snapshot']=replace(m['snapshot'],**changes)
                mark=position_mark(position_fixture(),m,now=f.NOW)
                self.assertEqual(mark['status'],'INVALID');self.assertIsNone(mark['gross_pnl'])

    def test_manual_profit_keeps_stop_and_underlying_has_independent_timestamp(self):
        p=position_fixture();p['plan']=ExitPlan('MANUAL',None,Decimal('20'),30).payload('.05')
        m=market_fixture();m['underlying_timestamp']=f.NOW-timedelta(seconds=4)
        mark=position_mark(p,m,now=f.NOW)
        self.assertIsNone(mark['target']);self.assertEqual(mark['stop'],Decimal('1.6'))
        self.assertFalse(mark['underlying_current']);self.assertEqual(mark['gross_pct'],Decimal('15'))

    def test_history_has_no_duplicates_reverse_times_fake_gaps_or_persistence(self):
        history=[]
        for sec in (0,0,-1,10,41):
            m=market_fixture(f.NOW+timedelta(seconds=sec))
            mark=position_mark(position_fixture(),m,now=f.NOW+timedelta(seconds=sec))
            history=append_bid_observation(history,mark)
        self.assertEqual(len(history),3);self.assertEqual([p['segment'] for p in history],[0,0,1])
        old=deepcopy(history)
        mark['status']='STALE';self.assertEqual(append_bid_observation(history,mark),old)
        mark['status']='LIVE';mark['quote_timestamp']+=timedelta(seconds=1)
        self.assertEqual(len(append_bid_observation(history,mark,limit=2)),2)
        self.assertEqual(history,old)


if __name__=='__main__':unittest.main()
