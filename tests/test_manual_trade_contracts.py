import unittest
from datetime import datetime,date,timedelta,timezone
from types import SimpleNamespace
from manual_trade_panel import itm_candidates


class ManualContractTests(unittest.TestCase):
    def test_itm_direction_and_fresh_real_quotes_are_required(self):
        now=datetime(2026,10,12,14,tzinfo=timezone.utc)
        def quote(strike,side='CALL',**changes):
            return SimpleNamespace(**(dict(option_type=side,expiration=date(2026,10,16),feed='opra',
                quote_timestamp=now,bid=2.,ask=2.1,bid_size=10,ask_size=10,strike=strike)|changes))
        chain=[quote(99),quote(100),quote(101),quote(98,feed='indicative'),
               quote(97,quote_timestamp=now-timedelta(minutes=2)),quote(96,bid=3),quote(95,ask_size=0)]
        selected=itm_candidates(chain,underlying_price=100,underlying_stamp=now,side='CALL',as_of=now)
        self.assertEqual([q.strike for q in selected],[99])
        puts=itm_candidates([quote(99,'PUT'),quote(101,'PUT')],underlying_price=100,
                            underlying_stamp=now,side='PUT',as_of=now)
        self.assertEqual([q.strike for q in puts],[101])
        self.assertFalse(itm_candidates(chain,underlying_price=100,underlying_stamp=now-timedelta(minutes=1),side='CALL',as_of=now))
