from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import unittest

from schwab_contracts import normalize_chain,canonical_itm_contracts,price_on_tick

NOW=datetime(2026,10,16,14,tzinfo=timezone.utc)
SYMBOL='AAPL  261023C00100000'


def chain_payload():
    return {'symbol':'AAPL','isDelayed':False,'underlying':{'last':104.,'quoteTime':int(NOW.timestamp()*1000)},
        'callExpDateMap':{'2026-10-23:7':{'100.0':[{'symbol':SYMBOL,'putCall':'CALL','strikePrice':100.,
            'expirationDate':'2026-10-23T20:00:00+00:00','bid':1.95,'ask':2.,'bidSize':10,'askSize':10,
            'quoteTimeInLong':int(NOW.timestamp()*1000),'nonStandard':False,'multiplier':100,'delta':.6}]}}}


class SchwabContractsTests(unittest.TestCase):
    def test_live_shape_explicit_100_stock_delivery_preserves_identity_and_stale_guards(self):
        payload=chain_payload()
        item=payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        item.update(multiplier=100.0,optionDeliverablesList=[
            {'symbol':'AAPL','assetType':'STOCK','deliverableUnits':100.0,'currencyType':None}])
        chain=normalize_chain(payload,'AAPL')
        self.assertEqual(len(chain.contracts),1)
        self.assertTrue(chain.contracts[0].standard_deliverable)
        self.assertEqual(canonical_itm_contracts(chain,'CALL',NOW+timedelta(seconds=31)),())
        with self.assertRaisesRegex(ValueError,'increment'):
            chain.contracts[0].validated()

    def test_cash_baskets_unknown_or_contradictory_deliverables_cannot_be_certified_standard(self):
        standard={'symbol':'AAPL','assetType':'STOCK','deliverableUnits':100.0,'currencyType':None}
        invalid=[{},'unknown',[standard,standard],
            [dict(standard,symbol='OTHER')],[dict(standard,assetType='CASH')],
            [dict(standard,deliverableUnits=99)],[dict(standard,deliverableUnits='100')],
            [dict(standard,deliverableUnits=True)],[dict(standard,deliverableUnits=float('nan'))],
            [dict(standard,currencyType='USD')],[dict(standard,cashAmount=10)],
            [{k:v for k,v in standard.items() if k!='currencyType'}]]
        for delivery in invalid:
            payload=chain_payload()
            payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['optionDeliverablesList']=deepcopy(delivery)
            with self.subTest(delivery=delivery):
                result=normalize_chain(payload,'AAPL')
                self.assertEqual(result.contracts,())
                self.assertEqual(result.rejected_contracts,1)

    def test_observed_provider_nonstandard_field_is_accepted_but_not_execution_ready(self):
        payload=chain_payload()
        item=payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        self.assertNotIn('isNonStandard',item)
        chain=normalize_chain(payload,'AAPL')
        self.assertEqual(len(chain.contracts),1)
        self.assertEqual(chain.rejected_contracts,0)
        with self.assertRaisesRegex(ValueError,'increment'):
            chain.contracts[0].validated()
        self.assertEqual(canonical_itm_contracts(chain,'CALL',NOW+timedelta(seconds=31)),())

    def test_missing_or_nonboolean_standard_metadata_is_not_inferred(self):
        for value in (None,0,'false',True):
            payload=chain_payload()
            payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['nonStandard']=value
            with self.subTest(value=value):
                self.assertEqual(normalize_chain(payload,'AAPL').contracts,())
        payload=chain_payload()
        del payload['callExpDateMap']['2026-10-23:7']['100.0'][0]['nonStandard']
        self.assertEqual(normalize_chain(payload,'AAPL').contracts,())

    def test_legacy_explicit_alias_stays_supported_but_conflicts_fail_closed(self):
        payload=chain_payload()
        item=payload['callExpDateMap']['2026-10-23:7']['100.0'][0]
        item['isNonStandard']=item.pop('nonStandard')
        self.assertEqual(len(normalize_chain(payload,'AAPL').contracts),1)
        for provider,legacy in [(True,False),(False,True),(None,False),(False,0)]:
            item.update(nonStandard=provider,isNonStandard=legacy)
            with self.subTest(provider=provider,legacy=legacy):
                self.assertEqual(normalize_chain(payload,'AAPL').contracts,())
        item.update(nonStandard=False,isNonStandard=False)
        self.assertEqual(len(normalize_chain(payload,'AAPL').contracts),1)

    def test_existing_itm_selector_accepts_only_explicit_real_time_identity(self):
        chain=normalize_chain(chain_payload(),'AAPL',verified_increments={SYMBOL:'.05'})
        selected=canonical_itm_contracts(chain,'CALL',NOW)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0].validated().snapshot.symbol,SYMBOL)
        self.assertEqual(canonical_itm_contracts(chain,'PUT',NOW),())

    def test_delayed_or_unknown_real_time_is_blocked(self):
        for value in (None,True,'false'):
            payload=chain_payload();payload['isDelayed']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_chain(payload,'AAPL')

    def test_nonstandard_multiplier_and_occ_mismatch_are_not_silently_accepted(self):
        for change in ({'multiplier':10},{'isNonStandard':True},{'strikePrice':101.},{'putCall':'PUT'},
                       {'isDelayed':True},{'optionDeliverablesList':[{'assetType':'CASH'}]}):
            payload=chain_payload();payload['callExpDateMap']['2026-10-23:7']['100.0'][0].update(change)
            result=normalize_chain(payload,'AAPL')
            self.assertEqual(result.contracts,())
            self.assertEqual(result.rejected_contracts,1)

    def test_unverified_price_increment_cannot_prepare_execution(self):
        contract=normalize_chain(chain_payload(),'AAPL').contracts[0]
        with self.assertRaisesRegex(ValueError,'increment'):
            contract.validated()

    def test_30_second_quote_guard_and_future_rejection_are_unchanged(self):
        chain=normalize_chain(chain_payload(),'AAPL')
        self.assertEqual(len(canonical_itm_contracts(chain,'CALL',NOW+timedelta(seconds=30))),1)
        self.assertEqual(canonical_itm_contracts(chain,'CALL',NOW+timedelta(seconds=30,microseconds=1)),())
        self.assertEqual(canonical_itm_contracts(chain,'CALL',NOW-timedelta(microseconds=1)),())

    def test_target_and_entry_round_up_and_exit_limit_rounds_down_to_verified_step(self):
        self.assertEqual(price_on_tick('2.4333333','.05',up=True),Decimal('2.45'))
        self.assertEqual(price_on_tick('1.981','.05',up=False),Decimal('1.95'))
        for value,step in [('NaN','.01'),('1','0'),('1','NaN')]:
            with self.assertRaises(ValueError):
                price_on_tick(value,step,up=True)


if __name__=='__main__':
    unittest.main()
