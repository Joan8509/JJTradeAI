"""Shared, durable manual actions for app/chat. Local simulation only.

No HTTP order client, notification sender or market-database writer belongs here.
Opening a link or preparing a review never places an order.
"""
from datetime import datetime, timezone
import json
import secrets
import time
from threading import RLock, Event

from manual_trade_service import ManualDataError, current_manual_signal, manual_candidates
from option_exit_plan import (ExitPlan, ExitPlanConfirmation, ManualCloseConfirmation,
    load_global_exit_policy, require_current_review)
from option_position_sizing import ManualQuantityConfirmation, manual_entry_cost, _price,require_manual_confirmation
from option_market_data import _parse_occ_symbol
from schwab_contracts import decimal, positive_int, price_on_tick
from schwab_simulation import (_IsolatedDatabase, ACTIVE, DataControls, ExecutionBlocked,
    LocalPaperBroker, SimulationEngine, SimulationLedger, digest, encoded, fresh,
    policy_from_dict, validated_signal, ManualPracticePolicy, practice_policy,
    validate_contract, execution_price, OBSERVED_MANUAL)


class EntryNotDispatched(ExecutionBlocked):
    """Validation stopped before entering the broker/ledger dispatch boundary."""


class ManualReviews(_IsolatedDatabase):
    def __init__(self, path):
        super().__init__(path, 'JJTRADE_MANUAL_REVIEWS_V1')
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS manual_reviews('
                'id TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL,'
                'state TEXT NOT NULL,result TEXT)')

    def save(self, owner, payload):
        identity=secrets.token_hex(12)
        with self.transaction() as db:
            db.execute('INSERT INTO manual_reviews VALUES(?,?,?, ?,NULL)',
                       (identity,owner,encoded(payload),'REVIEW'))
        return dict(payload,id=identity,state='REVIEW')

    def claim(self, identity, owner):
        with self.transaction() as db:
            row=db.execute('SELECT * FROM manual_reviews WHERE id=? AND owner=?',
                           (identity,owner)).fetchone()
            if row is None:
                raise ExecutionBlocked('REVIEW_NOT_FOUND')
            if row['state']!='REVIEW':
                raise ExecutionBlocked('REVIEW_ALREADY_USED')
            db.execute("UPDATE manual_reviews SET state='CLAIMED' WHERE id=?",(identity,))
            return json.loads(row['payload'])

    def finish(self, identity, state, result):
        with self.transaction() as db:
            db.execute('UPDATE manual_reviews SET state=?,result=? WHERE id=?',
                       (state,encoded(result),identity))


class ManualWorkflow:
    """One owner/account and ledger shared across UI sessions and chat callbacks."""
    def __init__(self, engine, reviews, *, read_state, market_data,
                 clock=lambda:datetime.now(timezone.utc)):
        if type(engine) is not SimulationEngine or type(reviews) is not ManualReviews:
            raise TypeError('LOCAL_SIMULATION_REQUIRED')
        if len({engine.ledger.path,engine.broker.path,reviews.path})!=3:
            raise ValueError('ISOLATED_COMPONENTS_REQUIRED')
        self.engine=engine;self.reviews=reviews;self.read_state=read_state
        self.market_data=market_data;self.clock=clock;self.lock=RLock()
        self.observation_lock=RLock()
        self.observation_journal=None
        self.observation_requested=Event()

    def _policy(self):
        policy=self.engine.policy.require_complete()
        if decimal(policy.stop_loss_pct)!=load_global_exit_policy().stop_loss_pct:
            raise ExecutionBlocked('GLOBAL_STOP_POLICY_MISMATCH')
        if not practice_policy(policy) and (self.market_data.fee_per_contract is None or decimal(
                self.market_data.fee_per_contract)!=decimal(policy.fee_per_contract)):
            raise ExecutionBlocked('VERIFIED_FEES_REQUIRED')
        return policy

    @staticmethod
    def _controls(state):
        session=state.get('session')
        return DataControls(True,True,True,
            datetime.fromisoformat(session[0]) if session else None,
            datetime.fromisoformat(session[1]) if session else None)

    def _entry(self, symbol, side, contract_symbol, *, force=False,alert_candle=None):
        if getattr(self,'entry_ready',None) is not None and not self.entry_ready():
            raise ExecutionBlocked('MONITOR_NOT_READY')
        state=self.read_state(symbol)
        reader=getattr(self,'alert_reader',None)
        if alert_candle is not None:
            if not practice_policy(self.engine.policy) or not callable(reader):
                raise ExecutionBlocked('MANUAL_ALERT_PRACTICE_ONLY')
            from manual_alert_entry import validate_reference,alert_candidates
            reference=reader(symbol,side,alert_candle)
            validate_reference(reference,self._controls(state),self.clock())
        else:current_manual_signal(state,symbol,self.clock())
        if force and alert_candle is not None:
            market=self.market_data.get_entry_chain(symbol,side,contract_symbol,self.clock())
        elif alert_candle is not None:
            market=self.market_data.get_catalog_chain(symbol,side,self.clock())
        else:market=self.market_data.get_chain(symbol,side,self.clock(),force=force)
        state=self.read_state(symbol);now=self.clock()
        if alert_candle is not None:
            reference=reader(symbol,side,alert_candle)
            signal,_,contracts=alert_candidates(reference,state,market,now,self._controls(state))
            tick=state.get('tick') or {}
        else:tick,_,contracts=manual_candidates(state,market,symbol,side,now)
        contract=next((c for c in contracts if c.snapshot.symbol==contract_symbol),None)
        if contract is None:
            error=ExecutionBlocked('CONTRACT_NO_LONGER_ELIGIBLE')
            error.contract_reasons=['CONTRACT_UNAVAILABLE']
            try:
                from entry_contract_diagnostics import contract_diagnostics
                from option_contract_selection import select_entry_expiration
                from price_ranges import optimal_option_premium
                selected=next((c for c in market.chain.contracts if c.snapshot.symbol==contract_symbol),None)
                expiry=select_entry_expiration(market.expirations,now)
                if selected and selected.snapshot.expiration!=expiry:
                    error.contract_reasons=['EXPIRATION_NOT_SELECTED']
                elif selected:
                    diagnostics=contract_diagnostics(market,symbol=symbol,side=side,expiration=expiry,as_of=now,
                        underlying_price=market.chain.underlying_price,underlying_stamp=market.chain.underlying_timestamp,
                        optimal_range=optimal_option_premium(symbol),eligible=contracts)
                    detail=next((r for r in diagnostics['contracts'] if r['symbol']==contract_symbol),None)
                    if detail:error.contract_reasons=detail['reasons']
            except Exception:pass  # Optional explanation never changes the rejection.
            raise error
        observed=practice_policy(self.engine.policy)
        validate_contract(contract,observed=observed)
        if execution_price(contract,'BUY',observed=observed)!=decimal(contract.snapshot.ask):
            raise ExecutionBlocked('ASK_NOT_ON_VERIFIED_TICK')
        controls=self._controls(state)
        if alert_candle is None:signal=validated_signal(tick,state['runtime'],controls,now)
        if getattr(self,'entry_ready',None) is not None and not self.entry_ready():
            raise ExecutionBlocked('MONITOR_NOT_READY')
        return tick,state['runtime'],controls,market,contract,signal,now

    def prepare_buy(self, owner, symbol, side, contract_symbol, quantity, target,*,alert_candle=None):
        """Explicit quantity/target; no fallback values or order dispatch."""
        policy=self._policy();positive_int(quantity)
        tick,runtime,controls,market,contract,signal,now=self._entry(symbol,side,contract_symbol,alert_candle=alert_candle)
        plan=ExitPlan('MANUAL' if target=='MANUAL' else 'TARGET_PERCENT',
            None if target=='MANUAL' else _price(target),decimal(policy.stop_loss_pct),
            policy.max_holding_minutes, OBSERVED_MANUAL if practice_policy(policy) else 'VERIFIED_TICK').validated()
        cost=manual_entry_cost(contract.snapshot.ask,quantity,policy.fee_per_contract)
        return self.reviews.save(owner,dict(action='BUY',account_alias=policy.account_alias,alert_candle=alert_candle,
            symbol=symbol,side=side,contract=contract_symbol,signal_key=signal['key'],
            quantity=quantity,ask=str(decimal(contract.snapshot.ask)),entry_cost=str(cost),
            target=str(plan.target_return_pct) if plan.target_return_pct is not None else 'MANUAL',
            stop=str(plan.stop_loss_pct),holding_minutes=plan.max_holding_minutes,
            reviewed_at=now.isoformat(),mode='LOCAL_SIMULATION',
            fees_known=not practice_policy(policy),cost_basis='PREMIUM_ONLY' if practice_policy(policy) else 'WITH_FEES'))

    def _owned(self, contract_symbol):
        position=self.engine.ledger.portfolio().get(contract_symbol)
        if not position:
            raise ExecutionBlocked('NO_FILLED_POSITION')
        source=self.engine.ledger.order(position['entry_client_key'])['order']
        if source['account_alias']!=self.engine.policy.account_alias:
            raise ExecutionBlocked('POSITION_ACCOUNT_CHANGED')
        return position,source

    def positions(self):
        result=[]
        for code,position in self.engine.ledger.portfolio().items():
            source=self.engine.ledger.order(position['entry_client_key'])['order']
            if source['account_alias']==self.engine.policy.account_alias:
                result.append(dict(contract=code,symbol=source['underlying'],quantity=position['quantity'],
                    side=_parse_occ_symbol(code.replace(' ',''))[0],
                    average_fill=str(position['premium']/(position['quantity']*100)),
                    entry_fees=str(position['entry_fees']) if source.get('fees_known') is not False else None,
                    exit_fee_per_contract=source['fee_per_contract'] if source.get('fees_known') is not False else None,
                    plan=position['plan'],entry_client_key=position['entry_client_key']))
        return result

    def position_market(self, contract_symbol):
        """Display-only quote; permits viewing a last quote with market closed.

        No trade signal, verified tick or order dispatch is needed to VIEW a mark.
        Trading continues to use its existing independent stricter checks.
        """
        position,source=self._owned(contract_symbol)
        side=_parse_occ_symbol(contract_symbol.replace(' ',''))[0]
        state=self.read_state(source['underlying'])
        market=(self.market_data.get_entry_chain(source['underlying'],side,contract_symbol,self.clock(),force=False)
            if getattr(self.market_data,'direct_quotes',False) else
            self.market_data.get_chain(source['underlying'],side,self.clock()))
        now=self.clock()
        contract=next((c for c in market.chain.contracts if c.snapshot.symbol==contract_symbol),None)
        if contract is None:
            raise ExecutionBlocked('POSITION_QUOTE_UNAVAILABLE')
        try:
            self._controls(state).require_session(now);session_open=True
        except ExecutionBlocked:
            session_open=False
        return dict(snapshot=contract.snapshot,underlying_price=market.chain.underlying_price,
            underlying_timestamp=market.chain.underlying_timestamp,session_open=session_open)

    def _exit(self, contract_symbol, *, force=False, market=None):
        position,source=self._owned(contract_symbol)
        # A position can be closed after the entry signal retracts or changes side.
        side=_parse_occ_symbol(contract_symbol.replace(' ',''))[0]
        state=self.read_state(source['underlying']);controls=self._controls(state)
        controls.require_session(self.clock())
        if market is None:
            market=self._observation_market(source['underlying'],contract_symbol,force=force)
        now=self.clock();controls.require_session(now)
        contract=next((c for c in market.chain.contracts if c.snapshot.symbol==contract_symbol),None)
        if contract is None:
            raise ExecutionBlocked('EXIT_QUOTE_UNUSABLE')
        validate_contract(contract,observed=practice_policy(self.engine.policy));q=contract.snapshot
        if q.feed!='opra' or q.quote_timestamp is None or not fresh(q.quote_timestamp,now,30):
            raise ExecutionBlocked('EXIT_QUOTE_UNUSABLE')
        return position,source,contract,controls,now

    def prepare_close(self, owner, contract_symbol):
        position,source,contract,controls,now=self._exit(contract_symbol,force=True)
        return self.reviews.save(owner,dict(action='CLOSE',account_alias=source['account_alias'],
            symbol=source['underlying'],contract=contract_symbol,quantity=position['quantity'],
            entry_client_key=position['entry_client_key'],
            minimum_price=str(execution_price(contract,'SELL',observed=practice_policy(self.engine.policy))),
            reviewed_at=now.isoformat(),mode='LOCAL_SIMULATION'))

    def pending_orders(self):
        return [row for row in self.engine.ledger.orders() if row['status'] in ACTIVE and
                row['order']['account_alias']==self.engine.policy.account_alias]

    def prepare_cancel(self, owner, client_key):
        row=self.engine.ledger.order(client_key)
        if (not row or row['status'] not in ('WORKING','PARTIALLY_FILLED') or
                row['order']['account_alias']!=self.engine.policy.account_alias):
            raise ExecutionBlocked('ORDER_NOT_CANCELABLE')
        return self.reviews.save(owner,dict(action='CANCEL',account_alias=self.engine.policy.account_alias,
            client_key=client_key,contract=row['order']['contract'],quantity=row['order']['quantity']-row['filled_quantity'],
            reviewed_at=self.clock().isoformat(),mode='LOCAL_SIMULATION'))

    def confirm(self, owner, identity):
        """Persist claim BEFORE dispatch; replay/uncertain responses never resubmit."""
        with self.lock:
            review=self.reviews.claim(identity,owner)
            entry_dispatch_started=False
            try:
                require_current_review(datetime.fromisoformat(review['reviewed_at']),self.clock())
                if review['account_alias']!=self.engine.policy.account_alias:
                    raise ExecutionBlocked('REVIEW_ACCOUNT_CHANGED')
                if review['action']=='CANCEL':
                    row=self.engine.ledger.order(review['client_key'])
                    if (not row or row['status'] not in ('WORKING','PARTIALLY_FILLED') or
                            row['order']['account_alias']!=review['account_alias']):
                        raise ExecutionBlocked('ORDER_NOT_CANCELABLE')
                    self.engine.broker.acknowledge_cancel(row['broker_id'])
                    self._reconcile(self.clock())
                    result={'status':self.engine.ledger.order(review['client_key'])['status'],
                            'client_key':review['client_key']}
                elif review['action']=='BUY':
                    policy=self._policy()
                    tick,runtime,controls,market,contract,signal,now=self._entry(
                        review['symbol'],review['side'],review['contract'],force=True,alert_candle=review.get('alert_candle'))
                    if signal['key']!=review['signal_key']:
                        raise ExecutionBlocked('REVIEW_SIGNAL_CHANGED')
                    if (decimal(review['stop'])!=decimal(policy.stop_loss_pct) or
                            review['holding_minutes']!=policy.max_holding_minutes):
                        raise ExecutionBlocked('REVIEW_POLICY_CHANGED')
                    entry=ManualQuantityConfirmation(review['account_alias'],review['symbol'],
                        review['contract'],review['signal_key'],review['quantity'],decimal(review['ask']),
                        decimal(review['entry_cost']),datetime.fromisoformat(review['reviewed_at']))
                    try:
                        require_manual_confirmation(entry,account_alias=policy.account_alias,
                            underlying_symbol=signal['symbol'],contract_symbol=contract.snapshot.symbol,
                            signal_key=signal['key'],ask=contract.snapshot.ask,
                            fee_per_contract=policy.fee_per_contract,as_of=now)
                    except ValueError as error:raise ExecutionBlocked(str(error)) from None
                    plan=ExitPlan('MANUAL' if review['target']=='MANUAL' else 'TARGET_PERCENT',
                        None if review['target']=='MANUAL' else decimal(review['target']),
                        decimal(review['stop']),review['holding_minutes'],
                        OBSERVED_MANUAL if practice_policy(policy) else 'VERIFIED_TICK')
                    self._reconcile(now)
                    entry_dispatch_started=True
                    key=self.engine.enter(tick,runtime,controls,contract,
                        signal.get('underlying_timestamp') or datetime.fromisoformat(tick['source_timestamp']),now,
                        listed_expirations=market.expirations,strike_inventory=market.strike_inventory,manual_confirmation=entry,
                        exit_confirmation=ExitPlanConfirmation(entry,plan,entry.confirmed_at),
                        manual_alert=signal.get('manual_alert'))
                    result={'status':self.engine.ledger.order(key)['status'],'client_key':key}
                else:
                    position,source,contract,controls,now=self._exit(review['contract'],force=True)
                    self._reconcile(now)
                    result=self.engine.close_position(contract,controls,now,
                        confirmation=ManualCloseConfirmation(review['account_alias'],review['entry_client_key'],
                            review['contract'],review['quantity'],decimal(review['minimum_price']),
                            datetime.fromisoformat(review['reviewed_at'])))
            except Exception as error:
                if (review['action']=='BUY' and not entry_dispatch_started and
                        (isinstance(error,(ExecutionBlocked,ManualDataError)) or
                         isinstance(error,ValueError) and str(error)=='EXIT_REVIEW_NOT_CURRENT')):
                    # No broker entry call happened. A NEW explicit review may
                    # try again after recovery; never reuse this claimed review.
                    self.reviews.finish(identity,'BLOCKED_BEFORE_DISPATCH',
                        {'status':'ENTRY_BLOCKED','reason':str(error)})
                    blocked=EntryNotDispatched(str(error))
                    blocked.contract_reasons=getattr(error,'contract_reasons',[])
                    raise blocked from None
                # No automatic retry, even if local dispatch or receipt persistence failed.
                self.reviews.finish(identity,'USED_OR_UNCERTAIN',{'status':'REVIEW_REQUIRES_NEW_CHECK'})
                raise
            self.reviews.finish(identity,'USED',result)
            return dict(result,mode='LOCAL_SIMULATION',real_orders_enabled=False)

    def _reconcile(self, now):
        if self.engine.reconcile(now)['status']!='RECONCILED':
            raise ExecutionBlocked('POSITION_RECONCILIATION_REQUIRED')

    def _observation_market(self, symbol, contract, *, force=False):
        """Provider I/O must precede taking the workflow mutation lock."""
        side=_parse_occ_symbol(contract.replace(' ',''))[0]
        self._controls(self.read_state(symbol)).require_session(self.clock())
        return (self.market_data.get_entry_chain(symbol,side,contract,self.clock(),force=force)
            if getattr(self.market_data,'direct_quotes',False) else
            self.market_data.get_chain(symbol,side,self.clock(),force=force))

    def observe(self):
        """One local simulation step; never a fill claim from the real broker.

        Explicit fresh quote matches and durable quote-liquidity dedup. Invocation
        needs a UI/worker; this method does not start a background monitor.
        """
        # Serialize observers independently, never blocking an entry while REST
        # is in flight. Every mutation re-reads ledger/session/quote under lock.
        with self.observation_lock:
            return self._observe()

    def _observe(self):
        results=[];quote_errors=[]
        with self.lock:
            self._reconcile(self.clock())
            exiting={r['order']['contract'] for r in self.pending_orders() if r['order']['instruction']=='SELL_TO_CLOSE'}
            positions=[p for p in self.positions() if p['contract'] not in exiting] if practice_policy(self.engine.policy) else []
        for p in positions:
            try:
                market=self._observation_market(p['symbol'],p['contract'])
            except Exception as error:
                quote_errors.append(error);continue
            with self.lock:
                if not any(r['contract']==p['contract'] for r in self.positions()):continue
                # Protect filled exposure BEFORE matching another entry tranche.
                # Cancel acknowledgement and reconciliation must precede selling.
                try:position,source,c,controls,now=self._exit(p['contract'],market=market)
                except (ValueError,ExecutionBlocked) as error:
                    quote_errors.append(error);continue
                stored=source['plan']
                plan=ExitPlan(stored['profit_mode'],
                    decimal(stored['target_pct']) if stored['target_pct'] is not None else None,
                    decimal(stored['stop_pct']),stored['max_holding_minutes'],stored['pricing_model'])
                average=position['premium']/(position['quantity']*100)
                target,stop=plan.levels(average,None)
                if decimal(c.snapshot.bid)<=stop or (target is not None and decimal(c.snapshot.bid)>=target):
                    for row in self.pending_orders():
                        if row['order']['contract']==p['contract'] and row['order']['instruction']=='BUY_TO_OPEN':
                            if not row['broker_id']:
                                raise ExecutionBlocked('ENTRY_CANCELLATION_AND_RECONCILIATION_REQUIRED')
                            self.engine.broker.acknowledge_cancel(row['broker_id'])
                    self._reconcile(now)
                    result=self.engine.manage_exit(c,controls,now);results.append(result)
                    if result.get('status') in ('EXIT_WORKING','EXIT_UNCERTAIN'):self._exit_diagnostic('EXIT_ORDER_REGISTERED',self.engine.ledger.order(result['client_key']),c)
        with self.lock:pending=sorted(self.pending_orders(),key=lambda r:r['order']['instruction']!='SELL_TO_CLOSE')
        for snapshot in pending:
            from automatic_entry_execution import queued_entry_expired,require_queued_match
            with self.lock:
                row=self.engine.ledger.order(snapshot['client_key'])
                if row['status'] not in ACTIVE or not row['broker_id']:continue
                order=row['order']
                if quote_errors and order['instruction']=='BUY_TO_OPEN':
                    continue  # Keep managing exits; do not add unmonitored exposure.
                if queued_entry_expired(order,self.clock()):
                    # Only acknowledge a local cancellation; never retry/rearm.
                    self.engine.broker.acknowledge_cancel(row['broker_id'])
                    self._reconcile(self.clock())
                    continue
            selling=order['instruction']=='SELL_TO_CLOSE'
            lookup_started=time.monotonic()
            if selling:self._exit_diagnostic('LOOKUP_STARTED',row)
            try:
                market=self._observation_market(order['underlying'],order['contract'],
                    force=selling or order.get('entry_basis')=='ARMED_LOCAL_QUEUE_V2' and order['instruction']=='BUY_TO_OPEN')
            except Exception as error:
                if selling:self._exit_diagnostic('LOOKUP_FAILED',row,lookup_ms=(time.monotonic()-lookup_started)*1000)
                quote_errors.append(error);continue
            with self.lock:
                row=self.engine.ledger.order(snapshot['client_key'])
                if row['status'] not in ACTIVE or not row['broker_id']:continue
                order=row['order']
                self._controls(self.read_state(order['underlying'])).require_session(self.clock())
                contract=next((c for c in market.chain.contracts if c.snapshot.symbol==order['contract']),None)
                if contract is None:
                    continue
                if selling:self._exit_diagnostic('LOOKUP_FINISHED',row,contract,lookup_ms=(time.monotonic()-lookup_started)*1000)
                now=self.clock()
                if queued_entry_expired(order,now):
                    self.engine.broker.acknowledge_cancel(row['broker_id'])
                    self._reconcile(now)
                    continue
                try:require_queued_match(order,contract,market,now)
                except ValueError:continue
                if contract.snapshot.quote_timestamp is not None and contract.snapshot.quote_timestamp<=datetime.fromisoformat(order['created_at']):
                    if selling:self._exit_diagnostic('POST_ORDER_QUOTE_REQUIRED',row,contract)
                    continue  # Provider has not published post-order liquidity yet.
                identity=digest(['LOCAL_QUOTE',row['client_key'],contract.snapshot.quote_timestamp])
                filled=self.engine.broker.match_quote(row['broker_id'],contract,now=now,execution_id=identity)
                if selling:
                    stage='MATCH_APPLIED' if filled else 'BID_BELOW_LIMIT' if decimal(contract.snapshot.bid)<decimal(order['limit']) else 'NO_AVAILABLE_LIQUIDITY'
                    self._exit_diagnostic(stage,row,contract,filled=filled)
        with self.lock:
            self._reconcile(self.clock())
            exiting={r['order']['contract'] for r in self.pending_orders() if r['order']['instruction']=='SELL_TO_CLOSE'}
            positions=[p for p in self.positions() if p['contract'] not in exiting]
        for position in positions:
            try:
                market=self._observation_market(position['symbol'],position['contract'])
            except Exception as error:
                quote_errors.append(error);continue
            with self.lock:
                if not any(r['contract']==position['contract'] for r in self.positions()):continue
                try:_,_,contract,controls,now=self._exit(position['contract'],market=market)
                except (ValueError,ExecutionBlocked) as error:
                    quote_errors.append(error);continue
                result=self.engine.manage_exit(contract,controls,now);results.append(result)
                if result.get('status') in ('EXIT_WORKING','EXIT_UNCERTAIN'):self._exit_diagnostic('EXIT_ORDER_REGISTERED',self.engine.ledger.order(result['client_key']),contract)
        # Healthy exposure was still managed. Unmanaged exposure continues to
        # fail the monitor readiness gate; this never authorizes another buy.
        if quote_errors:raise quote_errors[0]
        return results

    def _exit_diagnostic(self,event,row,contract=None,**metrics):
        if self.observation_journal is None:return
        try:
            now=self.clock();order=row['order']
            fields=dict(at=now,client_key=row['client_key'],contract=order['contract'],
                reason=order.get('exit_reason'),limit=order['limit'],
                order_age_ms=(now-datetime.fromisoformat(order['created_at'])).total_seconds()*1000,**metrics)
            if contract is not None:
                q=contract.snapshot
                fields.update(bid=q.bid,ask=q.ask,quote_at=q.quote_timestamp,
                    quote_age_ms=(now-q.quote_timestamp).total_seconds()*1000 if q.quote_timestamp else None)
            self.observation_journal.record(event,**fields)
        except Exception:pass  # Optional diagnostics never change trading.


def configured_workflow(profile, root, *, read_state, market_data):
    """Private opt-in profile; incomplete policy blocks before creating databases."""
    if not isinstance(profile,dict) or profile.get('real_orders_enabled') is not False:
        raise ExecutionBlocked('REAL_ORDERS_DISABLED')
    payload=profile.get('manual_simulation_policy')
    observed=profile.get('manual_practice_enabled') is True
    if observed:
        if payload is not None or profile.get('api_product')!='MARKET_DATA_ONLY':
            raise ExecutionBlocked('MANUAL_PRACTICE_PROFILE_CONFLICT')
        policy=ManualPracticePolicy().require_complete()
    else:
        if not isinstance(payload,dict):
            raise ExecutionBlocked('MANUAL_SIMULATION_NOT_CONFIGURED')
        policy=policy_from_dict(payload).require_complete()
        if market_data.fee_per_contract is None or decimal(market_data.fee_per_contract)!=decimal(policy.fee_per_contract):
            raise ExecutionBlocked('VERIFIED_FEES_REQUIRED')
    from pathlib import Path
    root=Path(root)
    if observed:
        root=root/'observed_manual_v1'
    engine=SimulationEngine(SimulationLedger(root/'ledger.db'),LocalPaperBroker(root/'broker.db'),policy)
    workflow=ManualWorkflow(engine,ManualReviews(root/'reviews.db'),read_state=read_state,market_data=market_data)
    if observed:
        from observation_journal import ObservationJournal
        workflow.observation_journal=ObservationJournal(root/'exit_observations.jsonl')
        from telegram_manual_controls import entry_monitor_ready
        workflow.entry_ready=entry_monitor_ready
    return workflow
