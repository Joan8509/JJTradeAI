from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from hashlib import sha256
from decimal import Decimal
import json

from real_live_capital import settled_capacity,preview_cost,RealCapitalGuard
from real_live_opportunities import RealOpportunities
from schwab_option_order_request import prepare_observed_limit
from schwab_order_preview import preview_request_payload
from tests import test_schwab_option_order_request as options
from tests import test_real_trade_preparation as preparation
from tests import test_real_execution_service as cycle


class LiveAdapterTests(TestCase):
    def setUp(self):
        self.now=options.NOW
        self.context=SimpleNamespace(binding='a'*64,account_number='12345678',account_hash='HASH')
        self.reader=Mock();self.preview=Mock();self.ledger=Mock();self.ledger.requests.return_value=[]
        self.preview.wire_format='PREVIEW_ORDER_STRATEGY_V1'
        self.account=dict(accountNumber='12345678',type='CASH',isClosingOnlyRestricted=False,
            currentBalances=dict(cashAvailableForTrading=500,cashBalance=500,cashAvailableForWithdrawal=400),positions=[])
        self.reader.positions.return_value=dict(securitiesAccount=self.account);self.reader.orders.return_value=[]
        self.guard=RealCapitalGuard(self.context,self.reader,self.preview,self.ledger,clock=lambda:self.now)
        self.draft=prepare_observed_limit(replace(options.contract(),price_increment=None),instruction='BUY_TO_OPEN',
            quantity=2,now=self.now,valid_until=self.now+timedelta(seconds=10))

    def report(self):
        wire=preview_request_payload(self.draft,account_number='12345678',as_of=self.now)
        return dict(source='SCHWAB_PREVIEW_ENDPOINT',state='PREVIEW_ACCEPT_REPORTED',
            request_fingerprint=sha256(json.dumps(wire,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            reported_projection=dict(projectedAvailableFund='298.70',projectedBuyingPower='298.70',projectedCommission='1.30'),
            reported_costs=dict(commission=[dict(value='1.30')],trueCommission=[dict(value='1.30')],fee=[]))

    def test_settled_capacity_never_uses_unsettled_or_invents_missing_cash(self):
        self.assertEqual(settled_capacity(self.account),400)
        account=deepcopy(self.account);account['currentBalances'].pop('cashAvailableForWithdrawal')
        with self.assertRaisesRegex(ValueError,'SETTLED_CASH_UNPROVEN'):settled_capacity(account)
        account['currentBalances']['unsettledCash']=450
        self.assertEqual(settled_capacity(account),50)
        account['type']='MARGIN'
        with self.assertRaises(ValueError):settled_capacity(account)

    def test_preview_commission_alternatives_not_double_counted_and_missing_fees_block(self):
        self.assertEqual(preview_cost(self.report(),self.draft),Decimal('201.30'))
        r=self.report();r['reported_costs'].pop('fee')
        with self.assertRaisesRegex(ValueError,'COSTS_INCOMPLETE'):preview_cost(r,self.draft)
        r=self.report();r['state']='PREVIEW_REQUIRES_REVIEW'
        with self.assertRaises(ValueError):preview_cost(r,self.draft)

    def test_exact_preview_and_current_cash_required_and_no_constructor_io(self):
        self.reader.positions.assert_not_called();self.preview.preview.assert_not_called()
        self.guard.refresh();self.preview.preview.return_value=self.report()
        self.guard.authorize(self.draft,'AAPL')
        self.assertTrue(self.guard.permits(self.draft))
        self.assertFalse(self.guard.permits(replace(self.draft,quantity=1)))
        self.now+=timedelta(seconds=10);self.assertFalse(self.guard.permits(self.draft))

    def test_negative_cash_external_order_wrong_account_and_unknown_positions(self):
        self.reader.orders.return_value=[dict(orderId=9,status='WORKING')]
        self.guard.refresh();self.assertFalse(self.guard.account_ready())
        self.reader.orders.return_value=[];self.account['accountNumber']='999'
        self.guard.refresh();self.assertFalse(self.guard.account_ready())
        self.account['accountNumber']='12345678';self.account.pop('positions')
        self.guard.refresh();self.assertTrue(self.guard.account_ready())
        self.assertNotIn('positions',self.guard.account)  # No inference of zero positions.

    def test_uncertain_order_blocks_new_entry_readiness_but_not_exit_monitor(self):
        self.ledger.requests.return_value=[dict(state='UNCERTAIN',broker_id=None)]
        self.guard.refresh()
        self.assertFalse(self.guard.account_ready())
        self.assertEqual(self.guard.blocker,'LIVE_ORDER_REQUIRES_RECONCILIATION')

    def test_insufficient_cash_and_stale_refresh_block_authorization(self):
        self.account['currentBalances']['cashAvailableForWithdrawal']=100
        self.guard.refresh();self.preview.preview.return_value=self.report()
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):self.guard.authorize(self.draft,'AAPL')
        self.now+=timedelta(seconds=30);self.assertFalse(self.guard.account_ready())

    def test_pending_buy_cash_reserved_and_existing_company_blocked(self):
        self.guard.refresh();self.preview.preview.return_value=self.report()
        self.ledger.requests.return_value=[dict(instruction='BUY_TO_OPEN',state='UNCERTAIN',limit='3',quantity=1,fills={})]
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):self.guard.authorize(self.draft,'AAPL')
        self.ledger.requests.return_value=[]
        self.account['positions']=[dict(instrument=dict(assetType='OPTION',underlyingSymbol='AAPL'),longQuantity=1)]
        with self.assertRaisesRegex(ValueError,'ALREADY_HELD'):self.guard.authorize(self.draft,'AAPL')

    def test_recent_filled_buy_is_not_treated_as_reusable_settled_cash(self):
        self.guard.refresh();self.preview.preview.return_value=self.report()
        self.ledger.requests.return_value=[dict(instruction='BUY_TO_OPEN',state='FILLED',limit='1',quantity=2,
            created_at=self.now.isoformat(),estimated_cost='201.30',
            fills={'x':dict(quantity=2,price='1',time=self.now.isoformat())})]
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):self.guard.authorize(self.draft,'AAPL')

    def test_observed_price_is_exact_bbo_and_not_an_increment_certification(self):
        self.assertEqual(self.draft.price_validation,'OBSERVED_SCHWAB_QUOTE')
        self.assertEqual(self.draft.limit,1)
        with self.assertRaises(Exception):prepare_observed_limit(options.contract(quote_timestamp=self.now-timedelta(seconds=30)),
            instruction='BUY_TO_OPEN',quantity=1,now=self.now,valid_until=self.now+timedelta(seconds=10))
        with self.assertRaises(Exception):prepare_observed_limit(options.contract(feed='UNKNOWN'),
            instruction='BUY_TO_OPEN',quantity=1,now=self.now,valid_until=self.now+timedelta(seconds=10))

    def test_shared_strategy_and_contract_selection_connected_without_simulation_writes(self):
        f=preparation.RealPreparationTests();f.setUp();self.addCleanup(f.doCleanups)
        market=f.h.f.market
        capital=Mock();capital.entry_ready.return_value=True;capital.funding_capacity.return_value=Decimal('100000')
        provider=RealOpportunities(market,capital,clock=lambda:f.h.f.now,signal_reader=f.service)
        result=provider(f.rows[0])
        self.assertIsNotNone(result);self.assertTrue(provider.signal_current(result['signal_key']))
        self.assertEqual(result['draft'].quantity,2);self.assertEqual(result['target'],'20')
        self.assertEqual(f.h.f.engine.ledger.orders(),[]);self.assertEqual(f.h.store.plans(),[])
        capital.authorize.assert_called_once()

    def test_impossible_range_budget_skips_network_without_changing_signal_clock(self):
        f=preparation.RealPreparationTests();f.setUp();self.addCleanup(f.doCleanups)
        market=Mock();capital=Mock();capital.funding_capacity.return_value=Decimal('1')
        provider=RealOpportunities(market,capital,clock=lambda:f.h.f.now,signal_reader=f.service)
        with self.assertRaisesRegex(ValueError,'LIVE_SETTLED_CASH_INSUFFICIENT'):provider(f.rows[0])
        market.get_catalog_chain.assert_not_called();capital.authorize.assert_not_called()
        self.assertEqual(f.service._signal('AMZN')[0]['detector_first_at'],f.h.f.now.isoformat())

    def test_prearming_and_consumed_signals_skip_all_broker_preparation(self):
        from real_live_opportunities import signal_identity
        f=preparation.RealPreparationTests();f.setUp();self.addCleanup(f.doCleanups)
        market=Mock();capital=Mock()
        provider=RealOpportunities(market,capital,clock=lambda:f.h.f.now,signal_reader=f.service)
        state,tick,_=f.service._signal('AMZN')
        key=signal_identity(tick,f.h.f.now)
        for changes in (dict(_signal_after=f.h.f.now.isoformat()),
                dict(_signal_after=(f.h.f.now+timedelta(seconds=1)).isoformat()),
                dict(used_signals=[key])):
            self.assertIsNone(provider(dict(f.rows[0],**changes)))
        market.get_catalog_chain.assert_not_called()
        capital.funding_capacity.assert_not_called();capital.authorize.assert_not_called()
        self.assertEqual(f.service._signal('AMZN')[0]['detector_first_at'],state['detector_first_at'])

    def test_signal_after_activation_keeps_existing_purchase_preparation(self):
        f=preparation.RealPreparationTests();f.setUp();self.addCleanup(f.doCleanups)
        capital=Mock();capital.entry_ready.return_value=True;capital.funding_capacity.return_value=Decimal('100000')
        provider=RealOpportunities(f.h.f.market,capital,clock=lambda:f.h.f.now,signal_reader=f.service)
        row=dict(f.rows[0],_signal_after=(f.h.f.now-timedelta(microseconds=1)).isoformat())
        self.assertIsNotNone(provider(row));capital.authorize.assert_called_once()

    def test_phase_timing_separates_preview_and_preserves_private_errors(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        ticks=iter(range(100));provider._monotonic=lambda:next(ticks)
        provider(f.rows[0])
        result=provider.timing_status()['AMZN']
        self.assertEqual(result['outcome'],'PREPARED_NOT_SENT')
        self.assertEqual(result['seconds'],dict(detector=1,funding=1,contract_search=1,
            selection_and_revalidation=1,broker_preview=1,final_revalidation=1,total=6))
        result['seconds']['total']=999
        self.assertEqual(provider.timing_status()['AMZN']['seconds']['total'],6)
        capital.authorize.side_effect=RuntimeError('PRIVATE_RESPONSE')
        with self.assertRaises(RuntimeError):provider(f.rows[0])
        status=provider.timing_status()
        self.assertEqual(status['AMZN']['outcome'],'UNAVAILABLE')
        self.assertNotIn('PRIVATE_RESPONSE',str(status))
        self.assertEqual(status['AMZN']['seconds']['broker_preview'],1)

    def test_observed_quote_entry_and_exit_work_without_fabricated_tick(self):
        f=cycle.RealExecutionCycleTests();f.setUp()
        quote=f.quote
        f.service.quote_contract=lambda symbol:replace(quote(symbol),price_increment=None)
        draft=prepare_observed_limit(f.service.quote_contract(options.contract().snapshot.symbol),instruction='BUY_TO_OPEN',
            quantity=2,now=f.now,valid_until=f.now+timedelta(seconds=10))
        buy=f.service.enter(signal_key='NEW',draft=draft,first_signal_at=f.now,source_at=f.now,
            session_close=f.end,target='20')
        f.broker(buy,2,'FILLED');f.service.poll();f.bid='1.23';f.ask='1.25'
        close=f.service.poll()[-1]
        self.assertEqual(close['limit'],'1.23')
        self.assertEqual(close['price_validation'],'OBSERVED_SCHWAB_QUOTE')

    def test_empty_contract_set_reports_contract_failure_instead_of_waiting_for_signal(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        from unittest.mock import patch
        with patch('option_contract_selection.entry_candidates',return_value=[]):
            with self.assertRaisesRegex(ValueError,'NO_ELIGIBLE_EXPIRATION_OR_RANGE'):provider(f.rows[0])
        capital.authorize.assert_not_called()
        attempt=next(iter(provider.attempt_status().values()))
        self.assertEqual(attempt['first_failure']['code'],'NO_ELIGIBLE_EXPIRATION_OR_RANGE')
        self.assertEqual(attempt['phase'],'selection_and_revalidation')
        self.assertEqual(attempt['first_signal_at'],f.h.f.now.isoformat())

    def test_first_meaningful_failure_survives_later_success_and_expired_signal(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        capital.authorize.side_effect=ValueError('LIVE_PREVIEW_NOT_ACCEPTED')
        with self.assertRaises(ValueError):provider(f.rows[0])
        capital.authorize.side_effect=None;provider(f.rows[0])
        attempt=next(iter(provider.attempt_status().values()))
        self.assertEqual(attempt['first_failure']['code'],'LIVE_PREVIEW_NOT_ACCEPTED')
        self.assertEqual(attempt['outcome'],'PREPARED_NOT_SENT')
        provider.reader._signal=Mock(side_effect=ValueError('SIGNAL_ENTRY_WINDOW_EXPIRED'))
        with self.assertRaises(ValueError):provider(f.rows[0])
        self.assertEqual(next(iter(provider.attempt_status().values()))['first_failure'],attempt['first_failure'])
        attempt['first_failure']['code']='CHANGED'
        self.assertEqual(next(iter(provider.attempt_status().values()))['first_failure']['code'],'LIVE_PREVIEW_NOT_ACCEPTED')

    def test_attempt_diagnostics_never_publish_private_error_text(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        capital.authorize.side_effect=RuntimeError('PRIVATE RESPONSE WITH CREDENTIAL')
        with self.assertRaises(RuntimeError):provider(f.rows[0])
        self.assertNotIn('PRIVATE RESPONSE',str(provider.attempt_status()))

    def two_choices(self,capacity):
        from manual_trade_service import manual_candidates
        from price_ranges import optimal_option_premium
        f=preparation.RealPreparationTests();f.setUp();self.addCleanup(f.doCleanups)
        market=f.h.f.market.get_catalog_chain('AMZN','CALL',f.h.f.now)
        _,_,eligible=manual_candidates(f.state,market,'AMZN','CALL',f.h.f.now)
        original=eligible[0];low,high=optimal_option_premium('AMZN')
        low=Decimal(str(low));high=Decimal(str(high));price=low+(high-low)/2
        first=replace(original,snapshot=replace(original.snapshot,bid=float(price-Decimal('.03')),ask=float(price)))
        strike=original.snapshot.strike-1
        symbol=original.snapshot.symbol[:-8]+f'{int(strike*1000):08d}'
        second=replace(original,snapshot=replace(original.snapshot,symbol=symbol,strike=strike,
            bid=float(low-Decimal('.03')),ask=float(low)))
        inventory=tuple(sorted(set(market.strike_inventory+((second.snapshot.expiration,strike),))))
        market=replace(market,chain=replace(market.chain,contracts=(first,second)),strike_inventory=inventory)
        client=Mock();client.get_catalog_chain.return_value=market
        capital=Mock();capital.entry_ready.return_value=True
        capital.funding_capacity.return_value=capacity if capacity is not None else low*200+Decimal('.01')
        return RealOpportunities(client,capital,clock=lambda:f.h.f.now,signal_reader=f.service),f,first,second,capital

    def test_selects_nearest_affordable_qualified_contract_without_reducing_quantity(self):
        provider,f,first,second,capital=self.two_choices(None)
        result=provider(f.rows[0])
        self.assertEqual(result['draft'].contract,second.snapshot.symbol)
        self.assertEqual(result['draft'].quantity,2);capital.authorize.assert_called_once()

    def test_funding_rejection_can_try_next_contract_without_restarting_signal_clock(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        def authorize(draft,symbol):
            if draft.contract==first.snapshot.symbol:raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        capital.authorize.side_effect=authorize
        result=provider(f.rows[0])
        self.assertEqual(result['draft'].contract,second.snapshot.symbol)
        self.assertEqual(result['first_signal_at'],f.h.f.now)
        self.assertEqual(capital.authorize.call_count,2)
        self.assertEqual(f.h.f.engine.ledger.orders(),[])

    def test_no_cheaper_candidate_does_not_repeat_preview(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        market=provider.market.get_catalog_chain.return_value
        provider.market.get_catalog_chain.return_value=replace(market,chain=replace(market.chain,contracts=(first,)))
        capital.authorize.side_effect=ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):provider(f.rows[0])
        self.assertEqual(capital.authorize.call_count,1)

    def test_successful_fallback_accumulates_preview_timing_and_retains_original_deadline(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        original_deadline=provider.reader._signal('AMZN')[2]
        ticks=iter(range(100));provider._monotonic=lambda:next(ticks)
        def authorize(draft,symbol):
            self.assertLessEqual(draft.expires_at,original_deadline)
            if draft.contract==first.snapshot.symbol:raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        capital.authorize.side_effect=authorize
        result=provider(f.rows[0])
        self.assertEqual(result['first_signal_at'],f.h.f.now)
        self.assertEqual(provider.timing_status()['AMZN']['seconds']['broker_preview'],2)
        self.assertEqual(capital.authorize.call_count,2)
        attempt=next(iter(provider.attempt_status().values()))
        self.assertEqual([r['result'] for r in attempt['funding_preview_attempts']],
            ['INSUFFICIENT_FUNDS','AUTHORIZED_PREVIEW'])

    def test_funding_capacity_deducts_unsettled_fills_and_reserved_fees(self):
        self.guard.refresh()
        self.ledger.requests.return_value=[dict(instruction='BUY_TO_OPEN',state='WORKING',limit='1',quantity=2,
            created_at=self.now.isoformat(),estimated_cost='201.30',fills={})]
        self.assertEqual(self.guard.funding_capacity(),Decimal('198.70'))
        self.assertIsNone(self.guard.permit)

    def test_funding_fallback_stops_after_two_previews_and_records_reasons(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        capital.authorize.side_effect=ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):provider(f.rows[0])
        self.assertEqual(capital.authorize.call_count,2)
        attempt=next(iter(provider.attempt_status().values()))
        self.assertEqual([r['ask'] for r in attempt['funding_preview_attempts']],
            [str(first.snapshot.ask),str(second.snapshot.ask)])
        self.assertTrue(all(r['result']=='INSUFFICIENT_FUNDS' for r in attempt['funding_preview_attempts']))
        self.assertEqual(f.h.f.engine.ledger.orders(),[])

    def test_warning_or_unknown_preview_failure_never_tries_another_contract(self):
        for error in (ValueError('LIVE_PREVIEW_NOT_ACCEPTED'),RuntimeError('PRIVATE_TRANSPORT_ERROR')):
            provider,f,first,second,capital=self.two_choices(Decimal('100000'))
            capital.authorize.side_effect=error
            with self.assertRaises(type(error)):provider(f.rows[0])
            self.assertEqual(capital.authorize.call_count,1)
            self.assertEqual(provider._funding_rejected,set())

    def test_funding_fallback_rechecks_retracted_or_expired_signal_before_preview(self):
        for code in ('NO_CURRENT_SIGNAL','SIGNAL_ENTRY_WINDOW_EXPIRED'):
            provider,f,first,second,capital=self.two_choices(Decimal('100000'))
            def reject(draft,symbol):
                provider.reader._signal=Mock(side_effect=ValueError(code))
                raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
            capital.authorize.side_effect=reject
            with self.assertRaisesRegex(ValueError,code):provider(f.rows[0])
            self.assertEqual(capital.authorize.call_count,1)
            self.assertEqual(f.h.f.engine.ledger.orders(),[])

    def test_funding_fallback_rechecks_available_cash_without_reducing_quantity(self):
        provider,f,first,second,capital=self.two_choices(Decimal('100000'))
        def reject(draft,symbol):
            capital.funding_capacity.return_value=Decimal('0')
            raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        capital.authorize.side_effect=reject
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):provider(f.rows[0])
        self.assertEqual(capital.authorize.call_count,1)
        self.assertEqual(capital.authorize.call_args.args[0].quantity,f.rows[0]['quantity'])

    def test_profit_exit_reprices_lower_bid_above_target_without_waiting_quote_expiry(self):
        f=cycle.RealExecutionCycleTests();f.setUp();quote=f.quote
        f.service.quote_contract=lambda symbol:replace(quote(symbol),price_increment=None)
        draft=prepare_observed_limit(f.service.quote_contract(options.contract().snapshot.symbol),instruction='BUY_TO_OPEN',
            quantity=2,now=f.now,valid_until=f.now+timedelta(seconds=10))
        buy=f.service.enter(signal_key='NEW',draft=draft,first_signal_at=f.now,source_at=f.now,session_close=f.end,target='20')
        f.broker(buy,2,'FILLED');f.service.poll();f.bid='1.23';f.ask='1.25'
        close=f.service.poll()[-1];f.broker(close,0)
        f.bid='1.22';f.ask='1.24'
        canceled=f.service.poll()[-1]
        self.assertEqual(canceled['state'],'PENDING_CANCEL');self.assertEqual(f.gateway.submit.call_count,2)
        f.broker(close,0,'CANCELED');new_close=f.service.poll()[-1]
        self.assertEqual(new_close['limit'],'1.22');self.assertEqual(new_close['quantity'],2)
        f.broker(new_close,0);f.bid='1.26';f.ask='1.28';f.service.poll()
        self.assertEqual(f.gateway.cancel.call_count,1)  # A higher bid makes the old limit marketable.
