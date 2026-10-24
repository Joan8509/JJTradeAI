"""User-approved entry methodology; synthetic quotes, no network or active DB."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from option_contract_selection import entry_candidates, require_entry_premium, select_entry_expiration
from price_ranges import load_optimal_option_premiums, optimal_option_premium
from tests.test_schwab_simulation import NOW, synthetic_contract


class OptionEntryRulesTests(unittest.TestCase):
    def test_user_spread_examples_and_strict_overage(self):
        for bid,ask in ((.10,.15),(.01,.05),(.42,.47),(2.30,2.35),(1.32,1.37),(.01,.06),(1.92,2.00),(.01,.09)):
            with self.subTest(bid=bid,ask=ask):
                require_entry_premium(bid,ask,(Decimal('.01'),Decimal('3')))
        for bid,ask in ((.10,.180001),(.01,.10)):
            with self.subTest(bid=bid,ask=ask),self.assertRaisesRegex(ValueError,'SPREAD'):
                require_entry_premium(bid,ask,(Decimal('.01'),Decimal('1')))

    def test_ask_determines_range_not_bid_or_midpoint(self):
        interval=optimal_option_premium('SPY')  #0.30-0.45 quoted premium.
        require_entry_premium(.28,.33,interval)  #Bid below range, ask inside.
        #Bid0.42 and midpoint0.445 are inside; ask0.47 is outside.
        with self.assertRaisesRegex(ValueError,'OUTSIDE_OPTIMAL'):
            require_entry_premium(.42,.47,interval)

    def test_generic_30_90_example_has_inclusive_quoted_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.csv'
            path.write_text('ticker;optimal_low;optimal_high;minimum;maximum\nTEST;30;90;20;100\n')
            interval=optimal_option_premium('TEST',path)
            self.assertEqual(interval,(Decimal('.30'),Decimal('.90')))
            for bid,ask in ((.25,.30),(.85,.90)):
                require_entry_premium(bid,ask,interval)
            for bid,ask in ((.2499,.2999),(.8501,.9001)):
                with self.assertRaisesRegex(ValueError,'OPTIMAL'):
                    require_entry_premium(bid,ask,interval)
            # Passing the spread does not independently pass a company's range.
            with self.assertRaisesRegex(ValueError,'OPTIMAL'):
                require_entry_premium(.01,.06,interval)

    def test_saved_company_intervals_preserved_and_missing_is_blocking(self):
        self.assertEqual(len(load_optimal_option_premiums()),53)
        self.assertEqual(optimal_option_premium('AAPL'),(Decimal('.35'),Decimal('.90')))
        self.assertEqual(optimal_option_premium('AMZN'),(Decimal('1.40'),Decimal('2.30')))
        with self.assertRaisesRegex(ValueError,'MISSING'):optimal_option_premium('NO_SUCH_SYMBOL')

    def test_bad_or_duplicate_ranges_are_not_silently_selected(self):
        header='ticker;optimal_low;optimal_high\n'
        for rows in ('AAPL;NaN;90\n','AAPL;35;Infinity\n','AAPL;0;90\n',
                     'AAPL;90;35\n','AAPL;;90\n',';35;90\n',
                     'AAPL;35;90\naapl;30;90\n',''):
            with self.subTest(rows=rows),tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'synthetic.csv';path.write_text(header+rows)
                with self.assertRaisesRegex(ValueError,'INVALID'):load_optimal_option_premiums(path)

    def test_invalid_numbers_and_limit_below_ask_fail_closed(self):
        for bid,ask,interval,limit in ((True,.50,(.30,.90),None),(.45,float('nan'),(.30,.90),None),
                (.45,.50,(.30,float('inf')),None),(.45,.50,(.30,.90),.49),
                (.51,.50,(.30,.90),None),(.45,.50,(.90,.30),None)):
            with self.subTest(bid=bid,ask=ask,limit=limit),self.assertRaisesRegex(ValueError,'INVALID'):
                require_entry_premium(bid,ask,interval,entry_limit=limit)

    def test_candidate_selection_keeps_itm_freshness_and_company_identity(self):
        quote=synthetic_contract().snapshot
        params=dict(symbol='AMZN',underlying_price=104.,underlying_stamp=NOW,side='CALL',as_of=NOW,
                    listed_expirations=(date(2026,10,23),))
        self.assertEqual(entry_candidates([quote],**params),[quote])
        for changed in (replace(quote,strike=104.),replace(quote,strike=105.),
                replace(quote,quote_timestamp=NOW-timedelta(seconds=30,microseconds=1)),
                replace(quote,quote_timestamp=NOW+timedelta(microseconds=1)),
                replace(quote,underlying_symbol='AAPL'),replace(quote,bid=1.919999),
                replace(quote,bid=2.26,ask=2.31)):
            with self.subTest(changed=changed):self.assertEqual(entry_candidates([changed],**params),[])
        put=synthetic_contract(side='PUT',strike=105.).snapshot
        self.assertEqual(entry_candidates([put],**(params|{'side':'PUT'})),[put])
        self.assertEqual(entry_candidates([quote],**(params|{'underlying_stamp':NOW-timedelta(seconds=31)})),[])

    def test_nearest_listed_date_is_selected_before_quote_filters(self):
        quote=synthetic_contract().snapshot
        params=dict(symbol='AMZN',underlying_price=104.,underlying_stamp=NOW,side='CALL',as_of=NOW)
        #No usable quote at the listed nearer date: do not jump to23Oct.
        self.assertEqual(entry_candidates([quote],**params,
            listed_expirations=(date(2026,10,16),date(2026,10,23))),[])
        with self.assertRaisesRegex(ValueError,'CALENDAR_REQUIRED'):
            entry_candidates([quote],**params)

    def test_nearest_expiration_and_two_pm_boundary_in_new_york(self):
        today=date(2026,10,15);tomorrow=date(2026,10,16)
        dates=(date(2026,10,23),tomorrow,today,today,date(2026,10,14))
        cutoff=datetime(2026,10,15,18,tzinfo=timezone.utc)  #14:00ET in October.
        for stamp in (cutoff-timedelta(microseconds=1),cutoff):
            self.assertEqual(select_entry_expiration(dates,stamp),today)
        self.assertEqual(select_entry_expiration(dates,cutoff+timedelta(microseconds=1)),tomorrow)

    def test_no_expiration_today_keeps_nearest_future_even_after_cutoff(self):
        stamp=datetime(2026,10,15,19,tzinfo=timezone.utc)
        self.assertEqual(select_entry_expiration((date(2026,10,23),date(2026,10,20)),stamp),
                         date(2026,10,20))

    def test_et_calendar_and_dst_not_host_clock_or_fixed_utc_cutoff(self):
        stamp=datetime(2026,1,15,19,tzinfo=timezone.utc)  #14:00ET in winter.
        dates=(date(2026,1,15),date(2026,1,16))
        self.assertEqual(select_entry_expiration(dates,stamp),dates[0])
        self.assertEqual(select_entry_expiration(dates,stamp+timedelta(seconds=1)),dates[1])
        #UTC has rolled into tomorrow but ET has not.
        stamp=datetime(2026,10,16,0,30,tzinfo=timezone.utc)
        self.assertEqual(select_entry_expiration((date(2026,10,15),date(2026,10,16)),stamp),
                         date(2026,10,16))

    def test_missing_tomorrow_uses_next_listed_expiry_without_inventing_dates(self):
        stamp=datetime(2026,10,16,19,tzinfo=timezone.utc)  #Friday15:00ET.
        self.assertEqual(select_entry_expiration(
            (date(2026,10,23),date(2026,10,16),date(2026,10,19)),stamp),date(2026,10,19))
        #If this company's next actual expiration is next Friday, use that date.
        self.assertEqual(select_entry_expiration((date(2026,10,16),date(2026,10,23)),stamp),
                         date(2026,10,23))
        with self.assertRaisesRegex(ValueError,'NONE_AFTER_CUTOFF'):
            select_entry_expiration((date(2026,10,16),),stamp)
        self.assertEqual(select_entry_expiration((date(2026,10,16),date(2026,10,17)),stamp),
                         date(2026,10,17))  #Only if explicitly supplied by provider.

    def test_unknown_invalid_or_expired_calendars_fail_closed(self):
        for dates,code in ((None,'REQUIRED'),([], 'NONE_AVAILABLE'),
                ((date(2026,10,15),),'NONE_AVAILABLE'),(('2026-10-23',),'INVALID'),
                ((True,),'INVALID'),((NOW,),'INVALID')):
            with self.subTest(dates=dates),self.assertRaisesRegex(ValueError,code):
                select_entry_expiration(dates,NOW)
        with self.assertRaisesRegex(ValueError,'CLOCK_MUST_BE_AWARE'):
            select_entry_expiration((date(2026,10,23),),NOW.replace(tzinfo=None))


if __name__=='__main__':unittest.main()
