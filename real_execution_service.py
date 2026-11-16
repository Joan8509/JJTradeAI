"""Independent real execution cycle. Dependencies must be explicitly connected.

No production factory, scheduler, UI side effects or simulated broker fallback.
Confirmed option executions alone establish owned quantities. Entry readiness
does not prevent monitoring/canceling/closing an already-owned position.
"""
from datetime import datetime, timedelta, timezone
from threading import RLock

from real_order_ledger import RealOrderBlocked, TERMINAL
from schwab_connection import aware
from schwab_contracts import decimal, price_on_tick
from schwab_option_order_request import OptionLimitRequest, prepare_option_limit,prepare_observed_limit


class RealEntryNotDispatched(RealOrderBlocked):
    '''Raised only while preparing, before any order coordinator call.'''


class RealExecutionService:
    def __init__(self, *, binding, account_number, ledger, coordinator, read_order,
                 quote_contract, entry_ready, signal_current,
                 clock=lambda: datetime.now(timezone.utc),entry_admission=None,exit_session_provider=None,entry_quote_provider=None,
                 entry_cost=None):
        self.binding=binding;self._account_number=account_number
        self.ledger=ledger;self.coordinator=coordinator;self.read_order=read_order
        self.quote_contract=quote_contract;self.entry_ready=entry_ready
        self.signal_current=signal_current;self.clock=clock;self._lock=RLock()
        self._entry_lock=RLock()
        self._order_observation_lock=RLock()
        self._drafts={}
        self._entry_signals={}
        self._target_permits={}
        self._exit_retry_permits={}
        self._exit_retry_after={}
        self.entry_admission=entry_admission or (lambda draft:True)
        self.exit_session_provider=exit_session_provider
        self.entry_quote_provider=entry_quote_provider
        self.entry_cost=entry_cost or (lambda draft:None)
        self.exit_admission=lambda contract:True
        self.exit_retry_proof=lambda parent,rejected,quantity:None
        self.exit_observations={}

    def __repr__(self):return '<RealExecutionService: explicit dependencies, durable orders>'

    def draft_for(self,row):
        # A restart does not revive an uncommitted stale entry or sell price.
        draft=self._drafts.get(row['id'])
        if draft is None:raise RealOrderBlocked('LIVE_DRAFT_NOT_CURRENT')
        draft.payload(aware(self.clock()))
        return draft

    def commit_guard(self,row,action):
        """Transport calls this again after OAuth/waits; no cached UI grant."""
        owned=next((r for r in self.ledger.requests(self.binding) if r['id']==row.get('id')),None)
        if owned!=row:return False
        if action=='CANCEL':return row['state']=='CANCEL_SUBMITTING'
        if action!='SUBMIT' or row['state']!='SUBMITTING':return False
        self.draft_for(row)
        if row['instruction']=='BUY_TO_OPEN':
            if any(r.get('external_close_hold') for r in self.ledger.requests(self.binding)):return False
            key=self._entry_signals.get(row['id'])
            return (key is not None and self.entry_ready() is True and self.signal_current(key) is True
                and self.entry_admission(self.draft_for(row)) is True)
        parent=next((r for r in self.ledger.requests(self.binding) if r['id']==row.get('parent_id')),None)
        if parent and parent.get('external_close_hold'):return False
        if row.get('exit_recovery_proof') is not None:
            from real_exit_recovery import validate_retry_proof
            proof=row['exit_recovery_proof']
            if (not parent or proof!=self._exit_retry_permits.get(row['id'])
                    or parent.get('exit_recovery_request')!=row['id']):return False
            rejected=[r for r in self.ledger.requests(self.binding) if r.get('parent_id')==parent['id']
                and r['id'] in proof['rejected_ids'] and r['state']=='REJECTED']
            try:
                validate_retry_proof(proof,binding=self.binding,parent=dict(parent,exit_recovery_used=False),
                    rejected=rejected,quantity=row['quantity'],now=self.clock())
            except RealOrderBlocked:return False
        if row.get('exit_role')=='BROKER_TARGET':
            if row.get('price_proof')!=self._target_permits.get(row['id']):return False
            parent=next((r for r in self.ledger.requests(self.binding) if r['id']==row.get('parent_id')),None)
            if not parent or parent.get('exit_trigger') in ('STOP','MANUAL'):return False
        return row.get('parent_id') is not None and self.exit_admission(row['contract']) is True

    def place_broker_target(self,buy_id,draft,proof):
        """Reserve a validated profit limit; no slow HTTP holds the exit lock."""
        from schwab_target_limit import TARGET_PRICE_MODE
        with self._lock:
            draft.payload(aware(self.clock()))
            if draft.price_validation!=TARGET_PRICE_MODE or draft.instruction!='SELL_TO_CLOSE':
                raise RealOrderBlocked('BROKER_TARGET_DRAFT_REQUIRED')
            rows=self.ledger.requests(self.binding)
            buy=next(r for r in rows if r['id']==buy_id and r['instruction']=='BUY_TO_OPEN')
            children=[r for r in rows if r.get('parent_id')==buy_id]
            if (buy['state'] not in TERMINAL or not buy['fills'] or buy.get('external_close_hold') or buy.get('exit_trigger') in ('STOP','MANUAL')
                    or any(r['state'] not in TERMINAL or r['state']=='REJECTED' for r in children)):
                raise RealOrderBlocked('BROKER_TARGET_POSITION_CHANGED')
            quantity=sum(f['quantity'] for f in buy['fills'].values())
            cost=sum(decimal(f['price'])*f['quantity'] for f in buy['fills'].values())/quantity
            target=buy['exit_plan']['target']
            if target=='MANUAL' or draft.limit<cost*(1+decimal(target)/100):
                raise RealOrderBlocked('BROKER_TARGET_BELOW_GOAL')
            if self.exit_admission(buy['contract']) is not True:raise RealOrderBlocked('LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION')
            row=self.ledger.prepare(self.binding,intent=buy_id+':BROKER_TARGET:'+str(len(children)),
                contract=draft.contract,instruction=draft.instruction,quantity=draft.quantity,limit=draft.limit,
                price_increment=None,expires_at=draft.expires_at,parent_id=buy_id,
                price_validation=TARGET_PRICE_MODE,price_proof=proof,exit_role='BROKER_TARGET')
            self._drafts[row['id']]=draft
            from copy import deepcopy
            self._target_permits[row['id']]=deepcopy(proof)
        # The stop can latch during OAuth/POST; the final transport guard checks
        # it again and cancels/observes any accepted order before another sell.
        return self.coordinator.submit(self.binding,row['id'])

    def enter(self, *, signal_key, draft, first_signal_at, source_at, session_close, target):
        with self._entry_lock:
            try:
                row,current=self._prepare_entry(signal_key=signal_key,draft=draft,first_signal_at=first_signal_at,
                    source_at=source_at,session_close=session_close,target=target)
            except Exception as error:
                import re
                code=str(error) if re.fullmatch('[A-Z_]{1,100}',str(error)) else 'LIVE_ENTRY_NOT_DISPATCHED'
                raise RealEntryNotDispatched(code) from None
            self._drafts[row['id']]=current
            self._entry_signals[row['id']]=signal_key
            return self.coordinator.submit(self.binding,row['id'])

    def _prepare_entry(self, *, signal_key, draft, first_signal_at, source_at, session_close, target):
        now=aware(self.clock());first=aware(first_signal_at);source=aware(source_at)
        end=aware(session_close)
        if (type(draft) is not OptionLimitRequest or draft.instruction!='BUY_TO_OPEN'
                or draft.price_validation not in ('VERIFIED_INCREMENT','OBSERVED_SCHWAB_QUOTE')):
            raise RealOrderBlocked('LIVE_ENTRY_DRAFT_REQUIRED')
        if not first<=source<=now or now-source>timedelta(seconds=3):
            raise RealOrderBlocked('LIVE_SIGNAL_NOT_CURRENT')
        deadline=min(first+timedelta(seconds=30),end,aware(draft.expires_at),now+timedelta(seconds=10))
        if now>=deadline:raise RealOrderBlocked('LIVE_SIGNAL_EXPIRED')
        if any(r.get('external_close_hold') for r in self.ledger.requests(self.binding)):
            raise RealOrderBlocked('LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION')
        if self.entry_ready() is not True or self.signal_current(signal_key) is not True or self.entry_admission(draft) is not True:
            raise RealOrderBlocked('LIVE_ENTRY_NOT_READY')
        # Exact limit was validated by the draft provider. No tick inference.
        contract=(self.entry_quote_provider or self.quote_contract)(draft.contract);contract.validate_identity()
        if (contract.snapshot.symbol!=draft.contract or decimal(contract.snapshot.ask)!=draft.limit):
            raise RealOrderBlocked('LIVE_ENTRY_QUOTE_CHANGED')
        builder=prepare_option_limit if draft.price_validation=='VERIFIED_INCREMENT' else prepare_observed_limit
        current=builder(contract,instruction='BUY_TO_OPEN',quantity=draft.quantity,
            now=now,valid_until=deadline)
        row=self.ledger.prepare(self.binding,intent=signal_key,contract=current.contract,
            instruction=current.instruction,quantity=current.quantity,limit=current.limit,
            expires_at=deadline,price_increment=contract.price_increment,enforce_symbol_exposure=True,
            exit_plan=dict(target=target,stop='20',session_close=end.isoformat()),price_validation=current.price_validation,
            estimated_cost=self.entry_cost(current))
        return row,current

    def poll(self):
        """Poll known IDs only; no adoption or resend of uncertain submissions."""
        return self.observe_orders()+self.monitor_positions()

    def observe_orders(self):
        """Account GET/cancel observation never holds the price-monitor lock."""
        with self._order_observation_lock:
            results=[]
            try:
                self.coordinator.recover_receipts(self.binding)
            except Exception:
                results.append(dict(state='LIVE_ORDER_READ_UNAVAILABLE',code='ORDER_RECEIPT_RECOVERY_PENDING'))
            for row in self.ledger.requests(self.binding):
                if not row.get('broker_id') or row['state'] in TERMINAL:continue
                try:
                    payload=self.read_order(row['broker_id'])
                    results.append(self.ledger.reconcile_snapshot(self.binding,row['id'],payload,
                        account_number=self._account_number))
                except Exception:
                    # One unavailable read must not suspend other positions' exits.
                    results.append(dict(id=row['id'],state='LIVE_ORDER_READ_UNAVAILABLE'))
            now=aware(self.clock())
            for row in self.ledger.requests(self.binding):
                if (row['instruction']=='BUY_TO_OPEN' and row['state'] in
                    ('ACKNOWLEDGED','WORKING','PARTIALLY_FILLED') and
                    now>=aware(datetime.fromisoformat(row['expires_at']))):
                    results.append(self.coordinator.cancel(self.binding,row['id']))
            return results

    def monitor_positions(self):
        # Independent of account GET latency, browser, notices and entry pause.
        with self._lock:
            results=[]
            for row in self.ledger.requests(self.binding):
                if (row.get('exit_role')=='BROKER_TARGET' and row['state']=='PREPARED'
                        and aware(self.clock())>=aware(datetime.fromisoformat(row['expires_at']))):
                    self.ledger.abandon_prepared(self.binding,row['id'])
            for row in self.ledger.requests(self.binding):
                if row['instruction']=='BUY_TO_OPEN' and row.get('exit_plan') and row['fills']:
                    try:
                        result=self._exit(row)
                        if result is not None:results.append(result)
                    except Exception as error:
                        code=str(error)
                        import re
                        if not re.fullmatch('[A-Z_]{1,100}',code):
                            code='LIVE_STORAGE_LOCK_UNAVAILABLE' if isinstance(error,PermissionError) else 'LIVE_EXIT_CHECK_FAILED'
                        self.exit_observations[row['contract']]=dict(self.exit_observations.get(row['contract'],{}),
                            checked_at=aware(self.clock()).isoformat(),state=code,parent_id=row['id'])
                        results.append(dict(id=row['id'],state='LIVE_EXIT_REQUIRES_REVIEW',code=code))
            return results

    def _exit(self,buy):
        now=aware(self.clock());plan=buy['exit_plan']
        end=aware(datetime.fromisoformat(plan['session_close']))
        if self.exit_session_provider:
            start,end=self.exit_session_provider(now)
            if not aware(start)<=now<aware(end):return None
        elif now>=end:return None
        rows=self.ledger.requests(self.binding)
        children=[r for r in rows if r.get('parent_id')==buy['id']]
        bought=sum(f['quantity'] for f in buy['fills'].values())
        sold=sum(f['quantity'] for r in children for f in r['fills'].values())
        if sold>=bought:
            if self.exit_observations.get(buy['contract'],{}).get('parent_id')==buy['id']:
                self.exit_observations.pop(buy['contract'],None)
            return None
        if buy.get('external_close_hold'):
            self.exit_observations[buy['contract']]=dict(checked_at=now.isoformat(),state='EXTERNAL_MANUAL_CLOSE_DETECTED')
            return None
        if self.exit_admission(buy['contract']) is not True:
            raise RealOrderBlocked('LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION')
        contract=self.quote_contract(buy['contract']);contract.validate_identity()
        # The quote may have changed while the GET was in flight. Evaluate its
        # actual provider timestamp against the clock AFTER receiving it.
        now=aware(self.clock())
        if now>=aware(end):return None
        if contract.snapshot.symbol!=buy['contract']:raise RealOrderBlocked('LIVE_EXIT_QUOTE_MISMATCH')
        quote=contract.snapshot;stamp=aware(quote.quote_timestamp)
        if not timedelta(0)<=now-stamp<timedelta(seconds=30):raise RealOrderBlocked('LIVE_EXIT_QUOTE_NOT_CURRENT')
        cost=sum(decimal(f['price'])*f['quantity'] for f in buy['fills'].values())/bought
        bid=decimal(quote.bid);reason=buy.get('exit_trigger')
        self.exit_observations[buy['contract']]=dict(checked_at=now.isoformat(),state='CURRENT',
            parent_id=buy['id'],
            quote_at=stamp.isoformat(),bid=str(bid),entry_average=str(cost),
            target=plan['target'],stop=plan['stop'],stop_bid=str(cost*decimal('.8')),
            target_bid=None if plan['target']=='MANUAL' else str(cost*(1+decimal(plan['target'])/100)))
        if bid<=cost*decimal('.8'):reason='STOP'
        elif not reason and plan['target']!='MANUAL' and bid>=cost*(1+decimal(plan['target'])/100):reason='TARGET'
        from real_exit_recovery import unresolved_rejections
        rejected=unresolved_rejections(buy,children)
        if not reason:
            if rejected:raise RealOrderBlocked('LIVE_EXIT_REJECTION_REQUIRES_REVIEW')
            return None
        self.exit_observations[buy['contract']].update(state='EXIT_TRIGGERED',reason=reason)
        if reason!=buy.get('exit_trigger'):buy=self.ledger.trigger_exit(self.binding,buy['id'],reason)
        if buy['state'] in ('ACKNOWLEDGED','WORKING','PARTIALLY_FILLED'):
            return self.coordinator.cancel(self.binding,buy['id'])
        # Keep the gain floor tied to final confirmed entry cost. Late buy
        # fills during cancellation must not lower the chosen percentage.
        if reason=='TARGET' and buy['state'] not in TERMINAL:return None
        active=[r for r in children if r['state'] not in TERMINAL]
        # Cancel an outstanding gain order when a stop takes priority. Never
        # replace until a subsequent GET proves final fills and remaining size.
        if active:
            for row in active:
                lower_to_bid=(decimal(row['limit'])>bid and (reason in ('STOP','MANUAL') or
                    (reason=='TARGET' and row.get('exit_role')!='BROKER_TARGET' and bid>=cost*(1+decimal(plan['target'])/100))))
                if (row['state'] in ('ACKNOWLEDGED','WORKING','PARTIALLY_FILLED') and
                        ((row.get('exit_role')!='BROKER_TARGET' and now>=aware(datetime.fromisoformat(row['expires_at']))) or
                         lower_to_bid)):
                    return self.coordinator.cancel(self.binding,row['id'])
            return None
        quantity=min(bought-sold,self.ledger.available_to_close(self.binding,buy['contract']))
        if quantity<=0:return None
        if now<self._exit_retry_after.get(buy['id'],now):
            self.exit_observations[buy['contract']].update(state='LIVE_EXIT_NOT_DISPATCHED')
            return dict(id=buy['id'],state='LIVE_EXIT_REQUIRES_REVIEW',code='LIVE_EXIT_NOT_DISPATCHED')
        retry_proof=None
        if rejected:
            retry_proof=self.exit_retry_proof(buy,rejected,quantity)
            if retry_proof is None:raise RealOrderBlocked('LIVE_EXIT_REJECTION_REQUIRES_REVIEW')
        until=min(stamp+timedelta(seconds=30),aware(end))
        if contract.price_increment is None:
            if reason=='TARGET' and bid<cost*(1+decimal(plan['target'])/100):return None
            draft=prepare_observed_limit(contract,instruction='SELL_TO_CLOSE',quantity=quantity,now=now,valid_until=until)
        else:
            limit=bid if reason!='TARGET' else price_on_tick(cost*(1+decimal(plan['target'])/100),contract.price_increment,up=True)
            draft=prepare_option_limit(contract,instruction='SELL_TO_CLOSE',quantity=quantity,now=now,valid_until=until,close_limit=limit)
        row=self.ledger.prepare(self.binding,intent=buy['id']+':EXIT:'+str(len(children)),
            contract=draft.contract,instruction=draft.instruction,quantity=quantity,limit=draft.limit,
            price_increment=contract.price_increment,expires_at=draft.expires_at,parent_id=buy['id'],price_validation=draft.price_validation,
            exit_retry_proof=retry_proof)
        self._drafts[row['id']]=draft
        if retry_proof is not None:self._exit_retry_permits[row['id']]=dict(retry_proof)
        result=self.coordinator.submit(self.binding,row['id'])
        self.exit_observations[buy['contract']].update(state='EXIT_ORDER_'+result['state'],limit=result['limit'])
        if result['state']=='EXPIRED' and 'ORDER_HTTP_NOT_ATTEMPTED' in result.get('issues',[]):
            self.exit_observations[buy['contract']].update(state='LIVE_EXIT_NOT_DISPATCHED')
            self._exit_retry_after[buy['id']]=aware(self.clock())+timedelta(seconds=1)
        return result

    def close_manually(self,buy_id):
        with self._lock:
            row=self.ledger.trigger_exit(self.binding,buy_id,'MANUAL')
            return self._exit(row)
