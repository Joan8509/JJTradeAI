"""Synthetic balances, quotes and previews only; no broker or vault writes."""
from tests.test_real_preparation_panel import select_real_tab
from copy import deepcopy
from datetime import timedelta,datetime,timezone
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,call
import json

from real_affordability import current_budget,range_candidates,verify_contract_budget
from schwab_preview_client import wire_payload
from schwab_connection import SchwabError
from tests.test_schwab_option_order_request import NOW,contract


def status(binding='a'*64,now=NOW,available='52.04',reserved='0'):
    return dict(binding=binding,checked_at=now.isoformat(),budget=dict(binding=binding,
        checked_at=now.isoformat(),available=available,reserved=reserved,
        capacity=str(Decimal(available)+Decimal(reserved))))


class BudgetTests(TestCase):
    def test_cash_requires_account_binding_fresh_host_and_fresh_balance(self):
        value=status()
        self.assertEqual(current_budget(value,'a'*64,NOW)['available'],Decimal('52.04'))
        for change in ('binding','host_stale','cash_stale','future','invalid','inconsistent'):
            bad=deepcopy(value)
            if change=='binding':bad['budget']['binding']='b'*64
            if change=='host_stale':bad['checked_at']=(NOW-timedelta(seconds=5)).isoformat()
            if change=='cash_stale':bad['budget']['checked_at']=(NOW-timedelta(seconds=30)).isoformat()
            if change=='future':bad['budget']['checked_at']=(NOW+timedelta(seconds=1)).isoformat()
            if change=='invalid':bad['budget']['available']='NaN'
            if change=='inconsistent':bad['budget']['available']='900'
            with self.subTest(change=change),self.assertRaises(ValueError):current_budget(bad,'a'*64,NOW)

    def test_ranges_use_contract_multiplier_and_do_not_claim_live_quotes_or_free_costs(self):
        rows=range_candidates(['SMALL','LARGE','MISSING','EXACT'],Decimal('52.04'),
            dict(SMALL=(Decimal('.45'),Decimal('.95')),LARGE=(Decimal('1'),Decimal('2')),
                EXACT=(Decimal('.5204'),Decimal('1'))))
        values={r['symbol']:r for r in rows}
        self.assertEqual(values['SMALL']['minimum'],45)
        self.assertEqual(values['SMALL']['ask_ceiling'],Decimal('.5204'))
        self.assertEqual(values['SMALL']['state'],'CANDIDATE_COSTS_PENDING')
        self.assertFalse(values['LARGE']['candidate']);self.assertFalse(values['EXACT']['candidate'])
        self.assertEqual(values['MISSING']['state'],'RANGE_MISSING')

    def test_budget_reserves_open_buys_recent_fills_and_costs_without_a_permit(self):
        from tests.test_real_live_adapters import LiveAdapterTests
        fixture=LiveAdapterTests();fixture.setUp()
        guard=fixture.guard;guard.refresh()
        stamp=fixture.now.isoformat()
        fixture.ledger.requests.return_value=[dict(instruction='BUY_TO_OPEN',state='ACKNOWLEDGED',
            limit='1',quantity=2,created_at=stamp,estimated_cost='201.30',
            fills={'one':dict(quantity=1,price='.99',time=stamp)})]
        result=guard.budget_snapshot()
        self.assertEqual(Decimal(result['reserved']),Decimal('200.30'))
        self.assertEqual(Decimal(result['available']),Decimal('199.70'))
        self.assertIsNone(guard.permit);fixture.preview.preview.assert_not_called()
        fixture.ledger.requests.return_value[0]['state']='UNCERTAIN'
        with self.assertRaisesRegex(ValueError,'RECONCILIATION'):guard.budget_snapshot()
        fixture.ledger.requests.return_value=[];fixture.now+=timedelta(seconds=30)
        with self.assertRaises(ValueError):guard.budget_snapshot()


class ContractBudgetTests(TestCase):
    def setUp(self):
        self.now=NOW;self.context=SimpleNamespace(binding='a'*64,account_number='SYNTHETIC')
        self.market=Mock();c=contract(ask=.5,bid=.45,feed='opra')
        self.market.get_catalog_chain.return_value=SimpleNamespace(expirations=[c.snapshot.expiration],
            strike_inventory=[(c.snapshot.expiration,350)],chain=SimpleNamespace(contracts=[c],
                underlying_price=351.,underlying_timestamp=NOW))
        self.preview=Mock(wire_format='ORDER_REQUEST_V1')
        def response(draft):
            fingerprint=sha256(json.dumps(wire_payload(draft,self.context.account_number,self.now,
                self.preview.wire_format),sort_keys=True,separators=(',',':')).encode()).hexdigest()
            return dict(source='SCHWAB_PREVIEW_ENDPOINT',state='PREVIEW_ACCEPT_REPORTED',
                request_fingerprint=fingerprint,reported_projection=dict(projectedAvailableFund='1',
                    projectedBuyingPower='1',projectedCommission='.65'),reported_costs=dict(fee=[]))
        self.preview.preview.side_effect=response
        self.available='52.04'
        self.reader=lambda:status(now=self.now,available=self.available)
        self.idle=lambda:True
        self.session=lambda now:(NOW-timedelta(seconds=1),NOW+timedelta(hours=6))

    def check(self):
        return verify_contract_budget('AAPL','CALL',context=self.context,market=self.market,
            preview=self.preview,budget_reader=self.reader,idle=self.idle,
            session_provider=self.session,clock=lambda:self.now)

    def test_quote_and_personalized_cost_confirm_one_contract_without_order_permission(self):
        result=self.check()
        self.assertEqual(result['cost'],'50.65');self.assertEqual(result['side'],'CALL')
        draft=self.preview.preview.call_args.args[0]
        self.assertEqual(draft.quantity,1);self.assertEqual(draft.price_validation,'PREVIEW_ONLY')
        self.assertEqual(self.preview.mock_calls,[call.preview(draft)])

    def test_closed_session_or_active_execution_never_queries_market_or_preview(self):
        self.session=lambda now:(NOW+timedelta(hours=1),NOW+timedelta(hours=6))
        with self.assertRaisesRegex(ValueError,'OUTSIDE'):self.check()
        self.session=lambda now:(NOW-timedelta(seconds=1),NOW+timedelta(hours=6))
        self.idle=lambda:False
        with self.assertRaisesRegex(ValueError,'BUSY'):self.check()
        self.market.get_catalog_chain.assert_not_called();self.preview.preview.assert_not_called()

    def test_cost_or_balance_change_after_preview_cannot_confirm_affordability(self):
        original=self.preview.preview.side_effect
        def response(draft):
            report=original(draft)
            self.available='49'
            return report
        self.preview.preview.side_effect=response
        with self.assertRaisesRegex(ValueError,'EXCEEDS'):self.check()

    def test_missing_fees_wrong_fingerprint_and_quote_expired_after_http_fail_closed(self):
        original=self.preview.preview.side_effect
        for mode in ('fees','fingerprint','expiry'):
            self.now=NOW
            def response(draft):
                report=original(draft)
                if mode=='fees':report['reported_costs']={}
                if mode=='fingerprint':report['request_fingerprint']='wrong'
                if mode=='expiry':self.now+=timedelta(seconds=30)
                return report
            self.preview.preview.side_effect=response
            with self.subTest(mode=mode),self.assertRaises((ValueError,SchwabError)):self.check()


class BudgetPanelTests(TestCase):
    def test_budget_preparation_preserves_targets_sets_one_and_does_not_arm_or_save(self):
        from streamlit.testing.v1 import AppTest
        from tests.test_real_preparation_panel import page
        app=AppTest.from_function(page,default_timeout=20).run()
        runtime=app.session_state['real_execution_runtime'];binding=runtime.binding
        runtime.status.return_value=status(binding,datetime.now(timezone.utc))
        app.session_state['real_prep_models']={binding:dict(selected=['AAPL'],
            rows={'AAPL':dict(symbol='AAPL',quantity=3,target='20')},generation=0)}
        client=app.session_state['test_client'];calls=list(client.method_calls)
        select_real_tab(app,'Con mi saldo')
        self.assertEqual(len(app.exception),0)
        app.button(key='real_budget_prepare').click().run()
        self.assertEqual(len(app.exception),0)
        model=app.session_state['real_prep_models'][binding]
        self.assertIn('AAPL',model['selected'])
        self.assertEqual(model['rows']['AAPL'],dict(symbol='AAPL',quantity=1,target='20'))
        runtime.arm.assert_not_called()
        self.assertIsNone(app.session_state['real_preparation_service'].preparation)
        self.assertEqual(client.method_calls,calls)
