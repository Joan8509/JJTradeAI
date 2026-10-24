"""Direct signed manual entry; reuses existing reviews, claims and paper engine."""
import hashlib
import json
import re
from datetime import datetime,timedelta,timezone
from urllib.parse import parse_qsl

from bollinger_phone_worker import canonical_candle
from manual_trade_service import ManualDataError,current_manual_signal,manual_candidates
from price_ranges import optimal_option_premium
from schwab_contracts import decimal,positive_int
from schwab_simulation import ExecutionBlocked,digest,encoded,practice_policy
from telegram_manual import TelegramManualError
from entry_preparation import public_entry_error as error_code,preparation_candidates,safe_entry_code
from entry_contract_diagnostics import contract_diagnostics
from option_contract_selection import otm_strike_positions


class FastManualEntry:
    def __init__(self,service):
        self.service=service;self.workflow=service.workflow;self.store=service.store
        self.alert_mode=practice_policy(self.workflow.engine.policy) and callable(getattr(self.workflow,'alert_reader',None))

    def _identity(self,raw,*,view=False):
        identity=self.service._identity(raw,view=view)
        key=hashlib.sha256((str(identity.user_id)+':'+identity.query_id).encode()).hexdigest()
        return key

    def _reference(self,symbol,side,candle):
        self.service.watch_link(symbol,side,candle)
        return canonical_candle(candle)

    def _existing(self,key):
        rows=self.store.read('SELECT * FROM telegram_entry_requests WHERE query_hash=?',(key,))
        if not rows:return None
        row=rows[0]
        if row['state']=='BLOCKED_BEFORE_DISPATCH':return json.loads(row['result'])
        if row['intent_id']:
            # Receipts do not execute. A concurrent/uncertain request is never retried.
            result=self.service._receipt(row['intent_id'])
            return dict(result,intent=row['intent_id'])
        return {'status':'ENTRY_IN_PROGRESS','mode':'LOCAL_SIMULATION','real_orders_enabled':False}

    def _record(self,result,stage):
        # No initData, owner/account, request/intent IDs, tokens or raw errors.
        try:
            with self.store.transaction() as db:
                db.execute('INSERT INTO telegram_entry_checks(checked_utc,symbol,side,candle,stage,status,reason,signal_reason,contracts) VALUES(?,?,?,?,?,?,?,?,?)',
                    (self.workflow.clock().isoformat(),result['symbol'],result['side'],result['candle'],stage,
                     result['status'],safe_entry_code(result['reason']) if result.get('reason') else None,
                     safe_entry_code(result['signal_reason']) if result.get('signal_reason') else None,
                     len(result.get('contracts',[]))))
        except Exception:pass  # Diagnostic failure must never place or repeat an order.

    def _signal(self,state,symbol,side,candle,now):
        tick=current_manual_signal(state,symbol,now)
        if canonical_candle(tick['signal']['candle'])!=candle:raise TelegramManualError('SIGNAL_CHANGED')
        if tick['signal']['side']!=('SUPERIOR' if side=='CALL' else 'INFERIOR'):
            raise TelegramManualError('SIGNAL_DIRECTION_CHANGED')
        return tick

    def result(self,raw):
        key=self._identity(raw,view=True)
        return self._existing(key) or {'status':'NO_ENTRY_REQUEST','real_orders_enabled':False}

    def catalog(self,raw,symbol,side,candle,selected_contract=None):
        key=self._identity(raw,view=True);candle=self._reference(symbol,side,candle)
        existing=self._existing(key)
        if existing and existing.get('intent'):return dict(existing,active_entry=True)
        result=dict(symbol=symbol,side=side,candle=candle,status='ENTRY_CATALOG',buy_ready=False,
            preparation_ready=False,signal_ready=False,signal_reason=None,contract_reason=None,
            contracts=[],reason=None,real_orders_enabled=False,mode='LOCAL_SIMULATION')
        if existing and existing.get('status')=='ENTRY_BLOCKED':
            from entry_preparation import safe_contract_reasons
            result['last_entry_result']={'status':'ENTRY_BLOCKED','reason':safe_entry_code(existing.get('reason')),
                'contract_reasons':safe_contract_reasons(existing.get('contract_reasons',[]))}
        auth_date=int(dict(parse_qsl(raw))['auth_date'])  # Already HMAC/owner validated.
        result['access_expires_utc']=datetime.fromtimestamp(auth_date+(28800 if self.alert_mode else 120),timezone.utc).isoformat()
        result.update(premium_low=None,premium_high=None,stop=str(self.workflow.engine.policy.stop_loss_pct))
        try:
            try:low,high=optimal_option_premium(symbol)
            except ValueError as error:
                if str(error)=='OPTIMAL_PREMIUM_RANGE_MISSING':raise ManualDataError('OPTIMAL_PREMIUM_RANGE_MISSING') from None
                raise
            result.update(premium_low=str(low),premium_high=str(high))
            self.workflow._policy()
            state=self.workflow.read_state(symbol);now=self.workflow.clock()
            self.workflow._controls(state).require_session(now)
            if self.alert_mode:
                from manual_alert_entry import validate_reference,alert_candidates
                reference=self.workflow.alert_reader(symbol,side,candle)
                validate_reference(reference,self.workflow._controls(state),now)
            try:self._signal(state,symbol,side,candle,now)
            except (ManualDataError,TelegramManualError) as error:
                result['signal_reason']=error_code(error)
            if not self.alert_mode and not datetime.fromisoformat(candle)<=now<datetime.fromisoformat(candle)+timedelta(minutes=15):
                # An old message is never silently moved to another candle.
                try:
                    tick=current_manual_signal(state,symbol,now)
                    if tick['signal']['side']==('SUPERIOR' if side=='CALL' else 'INFERIOR'):
                        result['current_candle']=canonical_candle(tick['signal']['candle'])
                except ManualDataError:pass
                raise TelegramManualError('SIGNAL_CHANGED')
            if selected_contract is not None:
                if not isinstance(selected_contract,str) or not 1<=len(selected_contract)<=40:
                    raise TelegramManualError('ENTRY_SELECTION_INVALID')
                market=self.workflow.market_data.get_entry_chain(symbol,side,selected_contract,now)
            else:
                market=(self.workflow.market_data.get_catalog_chain(symbol,side,now) if self.alert_mode else
                    self.workflow.market_data.get_chain(symbol,side,now))
            state=self.workflow.read_state(symbol);now=self.workflow.clock()
            if self.alert_mode:
                reference=self.workflow.alert_reader(symbol,side,candle)
                authorization,expiry,contracts=alert_candidates(reference,state,market,now,self.workflow._controls(state))
                result.update(entry_authorized=True,entry_basis='DELIVERED_ALERT_MANUAL_V1',
                    alert_expires_utc=self.workflow._controls(state).session_closes.isoformat(),
                    entry_window='SAME_SESSION_MANUAL',original_candle_ended=now>=datetime.fromisoformat(candle)+timedelta(minutes=15))
            tick=None
            try:
                tick=self._signal(state,symbol,side,candle,now)
            except (ManualDataError,TelegramManualError) as error:
                result['signal_reason']=error_code(error)
            if tick is not None and not self.alert_mode:
                result['signal_ready']=True;result['signal_reason']=None
                _,expiry,contracts=manual_candidates(state,market,symbol,side,now)
            elif not self.alert_mode:
                expiry,contracts=preparation_candidates(market,symbol,side,now)
            elif tick is not None:
                result['signal_ready']=True;result['signal_reason']=None
            if not market.chain.contracts:raise TelegramManualError('OPTION_QUOTES_UNAVAILABLE')
            if not contracts:result['contract_reason']='NO_ELIGIBLE_CONTRACTS'
            monitor_reason=None
            try:
                self.service._operational(direct=True)
                if getattr(self.workflow,'entry_ready',None) is not None and not self.workflow.entry_ready():
                    raise TelegramManualError('MONITOR_NOT_READY')
            except TelegramManualError as error:monitor_reason=error_code(error)
            positions=otm_strike_positions(market.chain.underlying_price,side,
                [strike for day,strike in market.strike_inventory if day==expiry])
            result.update(buy_ready=bool((result.get('entry_authorized') or result['signal_ready']) and contracts and monitor_reason is None),
                preparation_ready=bool(contracts),reason=(None if self.alert_mode else result['signal_reason']) or result['contract_reason'] or monitor_reason,
                source_timestamp=(state.get('tick') or {}).get('source_timestamp'),
                underlying_price=tick['signal']['price'] if result['signal_ready'] and not self.alert_mode else market.chain.underlying_price,
                underlying_source='SCHWAB_CURRENT' if self.alert_mode else 'IEX' if result['signal_ready'] else 'SCHWAB_PREPARATION_ONLY',
                expiration=expiry.isoformat(),fees_known=not practice_policy(self.workflow.engine.policy),
                fee_per_contract=str(self.workflow.engine.policy.fee_per_contract),
                contracts=[dict(symbol=c.snapshot.symbol,strike=c.snapshot.strike,ask=str(decimal(c.snapshot.ask)),
                    itm=(c.snapshot.strike<market.chain.underlying_price if side=='CALL' else c.snapshot.strike>market.chain.underlying_price),
                    otm_position=positions.get(decimal(c.snapshot.strike)),
                    bid=str(decimal(c.snapshot.bid)),ask_size=c.snapshot.ask_size,bid_size=c.snapshot.bid_size,
                    quote_timestamp=c.snapshot.quote_timestamp.isoformat()) for c in sorted(contracts,
                        key=lambda c:(abs(decimal(c.snapshot.strike)-decimal(market.chain.underlying_price)),c.snapshot.symbol))])
            result['recommended_contract']=result['contracts'][0]['symbol'] if result['contracts'] else None
            # Presentation only: canonical contracts/buy_ready above are unchanged.
            # A diagnostic error must not veto a valid entry or expose raw errors.
            try:
                use_tick=result['signal_ready'] and not self.alert_mode
                result['contract_diagnostics']=contract_diagnostics(market,symbol=symbol,side=side,
                    expiration=expiry,as_of=now,underlying_price=result['underlying_price'],
                    underlying_stamp=datetime.fromisoformat(tick['source_timestamp']) if use_tick else market.chain.underlying_timestamp,
                    optimal_range=(low,high),eligible=contracts)
            except Exception:pass
        except Exception as error:
            result['reason']=error_code(error)
            if result['signal_ready']:result['contract_reason']=result['reason']
        result['checked_utc']=self.workflow.clock().isoformat()
        result['access_ready']=self.workflow.clock()<=datetime.fromisoformat(result['access_expires_utc'])
        if not result['access_ready']:
            result['buy_ready']=False;result['reason']='TELEGRAM_AUTH_REQUIRED'
        self._record(result,'CATALOG')
        return result

    def buy(self,raw,*,symbol,side,candle,contract,quantity,target,ask,total,stop,request_id):
        key=self._identity(raw,view=self.alert_mode);candle=self._reference(symbol,side,candle)
        positive_int(quantity)
        if target not in ('10','20','35','100','MANUAL') or not isinstance(contract,str) or not 1<=len(contract)<=40:
            raise TelegramManualError('ENTRY_SELECTION_INVALID')
        if not isinstance(request_id,str) or not re.fullmatch('[A-Za-z0-9-]{16,64}',request_id):
            raise TelegramManualError('ENTRY_SELECTION_INVALID')
        expected_ask,expected_total,expected_stop=decimal(ask),decimal(total),decimal(stop)
        if min(expected_ask,expected_total,expected_stop)<=0:raise TelegramManualError('ENTRY_SELECTION_INVALID')
        duplicate=False
        with self.store.transaction() as db:
            row=db.execute('SELECT * FROM telegram_entry_requests WHERE query_hash=?',(key,)).fetchone()
            if row and not (row['state']=='BLOCKED_BEFORE_DISPATCH' and row['request_id']!=request_id):
                duplicate=True
            elif row:
                db.execute("UPDATE telegram_entry_requests SET request_id=?,state='PREPARING',intent_id=NULL,result=NULL WHERE query_hash=?",
                    (request_id,key))
            else:db.execute("INSERT INTO telegram_entry_requests VALUES(?,?,'PREPARING',NULL,NULL)",(key,request_id))
        if duplicate:return self._existing(key)
        intent=None
        try:
            self.service._operational(direct=True)
            kwargs={'alert_candle':candle} if self.alert_mode else {}
            review=self.workflow.prepare_buy(self.service.owner,symbol,side,contract,quantity,target,**kwargs)
            expected_key=digest(['ALPACA','iex',symbol,candle,'SUPERIOR' if side=='CALL' else 'INFERIOR'])
            if review['signal_key']!=expected_key:raise TelegramManualError('SIGNAL_CHANGED')
            if (decimal(review['ask'])!=expected_ask or decimal(review['entry_cost'])!=expected_total
                    or decimal(review['stop'])!=expected_stop):raise TelegramManualError('PRICE_CHANGED')
            draft=self.store.new_draft(self.service.user_id,dict(symbol=symbol,side=side,candle=candle,
                contract=contract,quantity=quantity,target=target,page=0,message_id=None))
            intent=self.store.new_intent(draft,self.service.user_id,review['id'])
            with self.store.transaction() as db:
                db.execute("UPDATE telegram_entry_requests SET state='DISPATCHING',intent_id=? WHERE query_hash=?",(intent,key))
            result=dict(self.service.execute(raw,intent,direct=True),intent=intent)
            if result['status']=='ENTRY_BLOCKED':
                # Proven rejection before the broker entry boundary; keep the
                # old intent for audit but don't switch the UI to a position.
                result.pop('intent');state='BLOCKED_BEFORE_DISPATCH'
            else:state='COMPLETE'
        except Exception as error:
            result={'status':'ENTRY_BLOCKED' if intent is None else 'ENTRY_UNCERTAIN','reason':error_code(error),
                'mode':'LOCAL_SIMULATION','real_orders_enabled':False}
            from entry_preparation import safe_contract_reasons
            result['contract_reasons']=safe_contract_reasons(getattr(error,'contract_reasons',[]))
            if intent is not None:result['intent']=intent
            state='BLOCKED_BEFORE_DISPATCH' if intent is None else 'UNCERTAIN'
        with self.store.transaction() as db:
            db.execute('UPDATE telegram_entry_requests SET state=?,result=? WHERE query_hash=?',(state,encoded(result),key))
        self._record(dict(result,symbol=symbol,side=side,candle=candle),'BUY')
        return result
