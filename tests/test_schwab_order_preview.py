"""Preview report fixtures; never calls POST preview or submits an order."""
from copy import deepcopy
from datetime import timedelta
from unittest import TestCase

from schwab_connection import SchwabError
from schwab_option_order_request import prepare_option_limit
from schwab_order_preview import normalize_preview_response
from tests import test_schwab_option_order_request as fixture

ACCOUNT='SYNTHETIC_ACCOUNT'


class OrderPreviewTests(TestCase):
    def setUp(self):
        self.draft=prepare_option_limit(fixture.contract(),instruction='BUY_TO_OPEN',quantity=2,
            now=fixture.NOW,valid_until=fixture.NOW+timedelta(seconds=10))
        self.raw=dict(orderId=0,orderStrategy=dict(accountNumber=ACCOUNT,orderType='LIMIT',
            session='NORMAL',duration='DAY',orderStrategyType='SINGLE',price=1.,quantity=2,
            filledQuantity=0,remainingQuantity=2,orderLegs=[dict(assetType='OPTION',instruction='BUY_TO_OPEN',
                quantity=2,finalSymbol=self.draft.contract)],orderBalance=dict(orderValue=200,
                projectedAvailableFund=799,projectedBuyingPower=799,projectedCommission=1)),
            orderValidationResult=dict(alerts=[],accepts=[dict(originalSeverity='ACCEPT',overrideSeverity='ACCEPT')],
                rejects=[],reviews=[],warns=[]),commissionAndFee=dict(
                commission=dict(commissionLegs=[dict(commissionValues=[dict(type='COMMISSION',value=1)])]),
                trueCommission=dict(commissionLegs=[dict(commissionValues=[dict(type='COMMISSION',value=1)])]),
                fee=dict(feeLegs=[dict(feeValues=[dict(type='FEE',value=.1)])])))
    def check(self):return normalize_preview_response(self.raw,self.draft,expected_account=ACCOUNT,as_of=fixture.NOW)

    def production_leg(self):
        leg=self.raw['orderStrategy']['orderLegs'][0]
        leg.pop('finalSymbol');leg.pop('quantity')
        leg['instrument']=dict(assetType='OPTION',symbol=self.draft.contract,
            uniformSymbol=self.draft.contract,underlyingSymbol='AAPL',putCall='CALL')
        self.raw['orderValidationResult']={}
        return leg

    def production_check(self):
        return normalize_preview_response(self.raw,self.draft,expected_account=ACCOUNT,
            as_of=fixture.NOW,optional_empty_categories=True)

    def test_actual_instrument_symbol_shape_is_verified_without_a_send_permission(self):
        self.production_leg();result=self.production_check()
        self.assertEqual(result['state'],'PREVIEW_NO_REJECTION_REPORTED')
        self.assertFalse(result['send_authorized']);self.assertEqual(result['orders_sent'],0)

    def test_actual_nested_identity_missing_or_contradictory_fields_fail_closed(self):
        self.production_leg();original=deepcopy(self.raw)
        for field,value in (('symbol',self.draft.contract.replace('C','P')),
            ('uniformSymbol',self.draft.contract.replace('C','P')),('assetType','EQUITY'),
            ('underlyingSymbol','SPY'),('putCall','PUT')):
            self.raw=deepcopy(original);self.raw['orderStrategy']['orderLegs'][0]['instrument'][field]=value
            with self.subTest(field=field),self.assertRaises(SchwabError):self.production_check()
        self.raw=deepcopy(original);del self.raw['orderStrategy']['orderLegs'][0]['instrument']['symbol']
        with self.assertRaises(SchwabError):self.production_check()

    def test_final_and_nested_symbol_must_agree_when_both_are_reported(self):
        leg=self.production_leg();leg['finalSymbol']=self.draft.contract.replace('C','P')
        with self.assertRaises(SchwabError):self.production_check()

    def test_report_never_authorizes_or_counts_preview_id_as_an_order(self):
        result=self.check();self.assertEqual(result['state'],'PREVIEW_ACCEPT_REPORTED')
        self.assertFalse(result['send_authorized']);self.assertFalse(result['real_orders_enabled'])
        self.assertFalse(result['settled_cash_verified']);self.assertFalse(result['options_permissions_verified'])
        self.assertEqual(result['orders_sent'],0);self.assertNotIn('order_id',result)
        self.assertNotIn(ACCOUNT,str(result))

    def test_commission_and_alternative_are_not_added_or_treated_as_final_cost(self):
        result=self.check();self.assertEqual(result['estimated_premium'],'200.0')
        self.assertEqual(result['reported_costs']['commission'][0]['value'],'1')
        self.assertEqual(result['reported_costs']['trueCommission'][0]['value'],'1')
        self.assertIsNone(result['total_cost']);self.assertFalse(result['total_cost_verified'])
        del self.raw['commissionAndFee']
        self.assertEqual(self.check()['reported_costs'],{})

    def test_identity_quantity_symbol_price_type_and_asset_must_match(self):
        original=deepcopy(self.raw)
        for key,value in (('accountNumber','OTHER'),('quantity',3),('price',1.01),('orderType','MARKET'),('duration','UNKNOWN')):
            self.raw=deepcopy(original);self.raw['orderStrategy'][key]=value
            with self.subTest(key=key),self.assertRaises(SchwabError):self.check()
        for key,value in (('assetType','EQUITY'),('instruction','SELL_TO_OPEN'),('quantity',3),('finalSymbol','SYNTHETIC')):
            self.raw=deepcopy(original);self.raw['orderStrategy']['orderLegs'][0][key]=value
            with self.subTest(key=key),self.assertRaises(SchwabError):self.check()

    def test_alert_reject_review_or_warning_blocks_even_when_accepts_exist(self):
        for category in ('alerts','rejects','reviews','warns'):
            self.raw['orderValidationResult'][category]=[dict(originalSeverity='ACCEPT')]
            result=self.check();self.assertEqual(result['state'],'PREVIEW_REQUIRES_REVIEW')
            self.assertIn(category.upper()+'_REPORTED',result['blockers'])
            self.raw['orderValidationResult'][category]=[]

    def test_missing_rules_or_generic_example_do_not_become_acceptance(self):
        del self.raw['orderValidationResult']['warns']
        with self.assertRaises(SchwabError):self.check()
        self.raw['orderValidationResult']['warns']=[];self.raw['orderValidationResult']['accepts']=[]
        self.assertIn('NO_EXPLICIT_ACCEPT_REPORTED',self.check()['blockers'])
        self.raw['orderStrategy']['quantity']=0
        with self.assertRaises(SchwabError):self.check()

    def test_unknown_validation_categories_require_review(self):
        self.raw['orderValidationResult']['futureRules']=[dict(message='UNINTERPRETED')]
        self.assertIn('UNKNOWN_VALIDATION_CATEGORY',self.check()['blockers'])

    def test_unsubmitted_preview_remaining_zero_or_omitted_never_creates_exposure(self):
        self.raw['orderStrategy']['remainingQuantity']=0
        self.assertEqual(self.check()['orders_sent'],0)
        del self.raw['orderStrategy']['remainingQuantity'];del self.raw['orderStrategy']['filledQuantity']
        self.assertFalse(self.check()['send_authorized'])
        self.raw['orderStrategy']['remainingQuantity']=999
        with self.assertRaises(SchwabError):self.check()

    def test_negative_funds_unknown_severity_or_nonfinite_costs_are_not_approved(self):
        self.raw['orderStrategy']['orderBalance']['projectedAvailableFund']=-1
        self.assertIn('NEGATIVE_PROJECTION_REPORTED',self.check()['blockers'])
        self.raw['orderValidationResult']['accepts'][0]['originalSeverity']='UNKNOWN'
        self.assertIn('UNKNOWN_ACCEPT_SEVERITY',self.check()['blockers'])
        self.raw['commissionAndFee']['commission']['commissionLegs'][0]['commissionValues'][0]['value']='NaN'
        with self.assertRaises(SchwabError):self.check()

    def test_expired_draft_filled_preview_or_changed_request_cannot_be_used(self):
        with self.assertRaises(SchwabError):normalize_preview_response(self.raw,self.draft,
            expected_account=ACCOUNT,as_of=fixture.NOW+timedelta(seconds=10))
        self.raw['orderStrategy']['filledQuantity']=1
        with self.assertRaises(SchwabError):self.check()
