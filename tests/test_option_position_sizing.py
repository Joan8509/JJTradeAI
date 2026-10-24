"""Synthetic standard100 budgets only; no broker calls or user policy amounts."""
from decimal import Decimal
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import unittest

from option_position_sizing import (contracts_for_budget, manual_entry_cost,
    ManualQuantityConfirmation, require_manual_confirmation)


class ManualQuantityReviewTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,17,15,tzinfo=timezone.utc)
        self.review=ManualQuantityConfirmation('SYNTHETIC','AMZN','SYNTHETIC_OCC',
            'SYNTHETIC_SIGNAL',2,Decimal('.47'),Decimal('95.30'),self.now)
        self.context=dict(account_alias='SYNTHETIC',underlying_symbol='AMZN',
            contract_symbol='SYNTHETIC_OCC',signal_key='SYNTHETIC_SIGNAL',ask='.47',
            fee_per_contract='.65',as_of=self.now)

    def test_reviewed_quantity_and_cost_are_preserved(self):
        self.assertEqual(require_manual_confirmation(self.review,**self.context),(2,Decimal('95.30')))
        for quantity in (0,-1,True,1.5,None):
            with self.subTest(quantity=quantity),self.assertRaisesRegex(ValueError,'QUANTITY_INVALID'):
                manual_entry_cost('.47',quantity,'.65')
        with self.assertRaises(ValueError):manual_entry_cost('.47',2,None)

    def test_confirmation_is_bound_to_identity_price_and_cost(self):
        for field,value in (('account_alias','OTHER'),('underlying_symbol','OTHER'),
                ('contract_symbol','OTHER'),('signal_key','OTHER'),('ask',Decimal('.46')),
                ('entry_cost',Decimal('94'))):
            with self.subTest(field=field),self.assertRaises(ValueError):
                require_manual_confirmation(replace(self.review,**{field:value}),**self.context)
        with self.assertRaisesRegex(ValueError,'CONFIRMATION_REQUIRED'):
            require_manual_confirmation(None,**self.context)

    def test_current_confirmation_boundary_future_and_dst_fold(self):
        require_manual_confirmation(self.review,**(self.context|{'as_of':self.now+timedelta(seconds=30)}))
        for stamp in (self.now-timedelta(microseconds=1),self.now+timedelta(seconds=30,microseconds=1)):
            with self.assertRaisesRegex(ValueError,'NOT_CURRENT'):
                require_manual_confirmation(self.review,**(self.context|{'as_of':stamp}))
        zone=ZoneInfo('America/New_York')
        first=datetime(2026,11,1,1,0,tzinfo=zone,fold=0)
        second=datetime(2026,11,1,1,0,tzinfo=zone,fold=1)
        with self.assertRaisesRegex(ValueError,'NOT_CURRENT'):
            require_manual_confirmation(replace(self.review,confirmed_at=first),
                **(self.context|{'as_of':second}))


class OptionPositionSizingTests(unittest.TestCase):
    def test_entry_costs_are_included_and_unspent_money_stays_unspent(self):
        self.assertEqual(contracts_for_budget('500', '.47', '.65'), 10)
        self.assertEqual(Decimal('10')*(Decimal('.47')*100+Decimal('.65')),Decimal('476.50'))

    def test_exact_budget_includes_entry_costs_and_rounds_down(self):
        self.assertEqual(contracts_for_budget('601.95', '2.00', '.65'), 3)
        self.assertEqual(contracts_for_budget('600', '2.00', '.65'), 2)
        self.assertEqual(contracts_for_budget('601.95', '2.05', '.65'), 2)
        self.assertEqual(contracts_for_budget('200.65', '2.00', '.65'), 1)
        self.assertEqual(contracts_for_budget('200.64', '2.00', '.65'), 0)

    def test_no_binary_or_decimal_rounding_can_turn_shortfall_into_extra_contract(self):
        self.assertEqual(contracts_for_budget('601.94999999999999999999999999999999999','2','.65'),2)
        self.assertEqual(contracts_for_budget('15','.15','0'),1)
        self.assertEqual(contracts_for_budget('0.01','2','.65'),0)

    def test_unknown_or_invalid_budget_price_and_fees_block(self):
        for args in ((None,2,.65),(0,2,.65),(-1,2,.65),(True,2,.65),
                ('NaN',2,.65),('Infinity',2,.65),('10%',2,.65),
                (500,None,.65),(500,0,.65),(500,-2,.65),(500,'NaN',.65),
                (500,2,None),(500,2,-1),(500,2,True),(500,2,'Infinity')):
            with self.subTest(args=args),self.assertRaisesRegex(ValueError,'INPUT_INVALID'):
                contracts_for_budget(*args)


if __name__=='__main__':unittest.main()
