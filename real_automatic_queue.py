"""Encrypted daily REAL queue, separate from automatic simulation.

The host must supply a verified execution service and a current strategy/quote
provider. Constructors do no I/O and do not start threads. A durable queue
claim precedes entry; an interrupted claim is never automatically retried.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import secrets
from threading import RLock

from real_order_ledger import RealOrderBlocked, TERMINAL
from real_trade_preparation import normalize_rows, _binding
from schwab_connection import aware
from real_live_storage import RealEncryptedStore as EncryptedSchwabStore

PURPOSE='REAL_AUTOMATIC_QUEUE_V1'


class RealAutomationStore(EncryptedSchwabStore):
    def __init__(self):
        self.path=Path(__file__).resolve().parent/'exports/private_runtime/real_automation.dpapi'


class RealAutomaticQueue:
    def __init__(self, *, store_factory=RealAutomationStore, clock=lambda:datetime.now(timezone.utc)):
        self.store_factory=store_factory;self.clock=clock;self._lock=RLock()

    @staticmethod
    def _document(store):
        doc=store.load() if store.path.exists() else dict(purpose=PURPOSE,profiles={})
        if doc.get('purpose')!=PURPOSE or not isinstance(doc.get('profiles'),dict):
            raise RealOrderBlocked('LIVE_QUEUE_INVALID')
        return doc

    def read(self,binding):
        _binding(binding);store=self.store_factory()
        with store.locked():return deepcopy(self._document(store)['profiles'].get(binding))

    def arm(self,binding,rows,*,session_open,session_close,execution_ready,repeat_new_signals=True,first_entry_only=False):
        """Only an explicit UI action may arm a verified, connected executor."""
        _binding(binding);rows=normalize_rows(rows)
        if type(repeat_new_signals) is not bool:raise RealOrderBlocked('LIVE_REPEAT_SELECTION_INVALID')
        if type(first_entry_only) is not bool:raise RealOrderBlocked('LIVE_FIRST_ENTRY_SELECTION_INVALID')
        if first_entry_only:repeat_new_signals=False
        start=aware(session_open);end=aware(session_close);now=aware(self.clock())
        if start>=end or now>=end:raise RealOrderBlocked('LIVE_QUEUE_SESSION_INVALID')
        if execution_ready() is not True:raise RealOrderBlocked('LIVE_EXECUTOR_NOT_VERIFIED')
        store=self.store_factory()
        with store.locked():
            doc=self._document(store);old=doc['profiles'].get(binding)
            if old and any(r['state'] not in ('PAUSED','EXPIRED','COMPLETED','EXCLUDED_FIRST_ENTRY','REMOVED') for r in old['rows']):
                raise RealOrderBlocked('LIVE_QUEUE_ALREADY_EXISTS')
            # Keep the prior plan/audit; arming is never a destructive reset.
            history=(old.get('history',[])+[{k:v for k,v in old.items() if k!='history'}]) if old else []
            plan=dict(id=secrets.token_hex(16),armed_at=now.isoformat(),session_open=start.isoformat(),
                session_close=end.isoformat(),paused=False,history=history,
                first_entry_only=first_entry_only,entry_owner=None,entry_consumed=False,
                winning_symbol=None,winning_request_id=None,
                rows=[dict(r,id=secrets.token_hex(16),state='ARMED',repeat_new_signals=repeat_new_signals,
                    request_id=None,claim=None,used_signals=[],completed_at=None) for r in rows])
            doc['profiles'][binding]=plan;store.save(doc)
            return deepcopy(plan)

    def pause(self,binding):
        """Stop new entries; never disables exit monitoring or deletes history."""
        _binding(binding);store=self.store_factory()
        with store.locked():
            doc=self._document(store);plan=doc['profiles'].get(binding)
            if not plan:return None
            plan['paused']=True
            for row in plan['rows']:
                row['repeat_new_signals']=False
                if row['state']=='ARMED':row['state']='PAUSED'
            store.save(doc);return deepcopy(plan)

    def _change(self,binding,plan_id,row_id,change):
        store=self.store_factory()
        with store.locked():
            doc=self._document(store);plan=doc['profiles'].get(binding)
            if not plan or plan['id']!=plan_id:raise RealOrderBlocked('LIVE_QUEUE_CHANGED')
            row=next(r for r in plan['rows'] if r['id']==row_id)
            result=change(plan,row);store.save(doc)
            return deepcopy(result)

    def resume(self,binding,plan_id,*,execution_ready):
        """Explicitly resume only untouched paused rows in the same daily plan.

        Keep the original signal boundary, used signals, claims and first-fill
        decision. This does not create a new plan or renew any signal lifetime.
        """
        _binding(binding)
        if execution_ready() is not True:raise RealOrderBlocked('LIVE_EXECUTOR_NOT_VERIFIED')
        store=self.store_factory()
        with store.locked():
            doc=self._document(store);plan=doc['profiles'].get(binding)
            if not plan or plan['id']!=plan_id:raise RealOrderBlocked('LIVE_QUEUE_CHANGED')
            if not plan['paused']:raise RealOrderBlocked('LIVE_QUEUE_NOT_PAUSED')
            if aware(self.clock())>=aware(datetime.fromisoformat(plan['session_close'])):
                raise RealOrderBlocked('LIVE_QUEUE_SESSION_INVALID')
            if plan.get('entry_consumed') or plan.get('entry_owner') or any(
                    r['state'] in ('SUBMITTING','ORDER_SENT','REQUIRES_REVIEW') for r in plan['rows']):
                raise RealOrderBlocked('LIVE_FIRST_ENTRY_RESERVED')
            pending=[r for r in plan['rows'] if r['state']=='PAUSED' and not r.get('claim') and not r.get('request_id')]
            if not pending:raise RealOrderBlocked('LIVE_NO_PAUSED_COMPANIES')
            for row in pending:row.update(state='ARMED',repeat_new_signals=False)
            plan.update(paused=False,resumed_at=aware(self.clock()).isoformat())
            store.save(doc);return deepcopy(plan)

    def remove_waiting(self,binding,plan_id):
        """Atomically remove all unclaimed waiting rows; never cancel an order."""
        _binding(binding);store=self.store_factory()
        with store.locked():
            doc=self._document(store);plan=doc['profiles'].get(binding)
            if not plan or plan['id']!=plan_id:raise RealOrderBlocked('LIVE_QUEUE_CHANGED')
            now=aware(self.clock()).isoformat()
            for row in plan['rows']:
                if (row['state'] in ('ARMED','PAUSED') and not row.get('request_id') and
                        not row.get('claim') and plan.get('entry_owner')!=row['id']):
                    row.update(state='REMOVED',repeat_new_signals=False,removed_at=now)
            plan.update(paused=True,cleared_at=now)
            store.save(doc);return deepcopy(plan)

    def remove(self,binding,plan_id,row_id):
        """Withdraw only an unclaimed row; preserve its audit and other rows.

        The existing atomic claim guard refuses any row no longer ARMED, even
        if an entry worker was already preparing a proposal from an old read.
        No broker cancellation, exposure change, pause or rearming occurs here.
        """
        _binding(binding)
        def withdraw(plan,row):
            if row['state']=='REMOVED':return plan
            if (row['state'] not in ('ARMED','PAUSED') or row.get('request_id') or
                row.get('claim') or plan.get('entry_owner')==row['id']):
                raise RealOrderBlocked('LIVE_QUEUE_ROW_ALREADY_IN_PROGRESS')
            row.update(state='REMOVED',repeat_new_signals=False,removed_at=aware(self.clock()).isoformat())
            return plan
        return self._change(binding,plan_id,row_id,withdraw)

    def step(self,binding,execution,prepare_entry,*,monitor=True):
        """One bounded scheduler turn. Exits run even if queue is paused/empty.

        prepare_entry(row) supplies the exact arguments of execution.enter,
        backed by the shared current detector and current eligible option quote.
        It must return None if there is no eligible opportunity.
        """
        _binding(binding)
        if execution.binding!=binding:raise RealOrderBlocked('LIVE_QUEUE_ACCOUNT_MISMATCH')
        with self._lock:
            events=execution.poll() if monitor else []
            plan=self.read(binding)
            if not plan:return events
            now=aware(self.clock())
            for row in plan['rows']:
                if row['state']=='ORDER_SENT':
                    orders=execution.ledger.requests(binding)
                    buy=next((r for r in orders if r['id']==row['request_id']),None)
                    if buy is None:continue
                    bought=sum(f['quantity'] for f in buy['fills'].values())
                    if plan.get('first_entry_only') and bought>0:
                        def consume(current,item):
                            current['entry_consumed']=True
                            current['winning_symbol']=item['symbol'];current['winning_request_id']=buy['id']
                            for other in current['rows']:
                                if other['id']!=item['id'] and other['state'] in ('ARMED','PAUSED'):
                                    other['state']='EXCLUDED_FIRST_ENTRY';other['repeat_new_signals']=False
                        self._change(binding,plan['id'],row['id'],consume)
                    if buy['state'] not in TERMINAL:continue
                    closes=[r for r in orders if r.get('parent_id')==buy['id']]
                    sold=sum(f['quantity'] for r in closes for f in r['fills'].values())
                    if bought!=sold or any(r['state'] not in TERMINAL for r in closes):continue
                    def complete(current,item):
                        item['completed_at']=now.isoformat();item['request_id']=None;item['claim']=None
                        item['state']='ARMED' if item['repeat_new_signals'] and not current['paused'] else 'COMPLETED'
                        if current.get('first_entry_only') and not current.get('entry_consumed'):
                            # Terminal zero-fill evidence releases the reservation.
                            current['entry_owner']=None
                            item['state']='PAUSED' if current['paused'] else 'ARMED'
                    self._change(binding,plan['id'],row['id'],complete)
                    # A later turn must observe a new signal after completion.
                    continue
                if row['state']!='ARMED' or plan['paused']:continue
                if plan.get('first_entry_only') and (plan.get('entry_owner') or plan.get('entry_consumed')):continue
                if now>=aware(datetime.fromisoformat(plan['session_close'])):
                    self._change(binding,plan['id'],row['id'],lambda p,r:r.update(state='EXPIRED'))
                    continue
                if now<aware(datetime.fromisoformat(plan['session_open'])):continue
                # Give the provider the existing signal boundary before any
                # chain/preview HTTP. The authoritative check below remains.
                candidate=deepcopy(row)
                candidate['_signal_after']=row['completed_at'] or plan['armed_at']
                try:proposal=prepare_entry(candidate)
                except Exception:
                    events.append(dict(id=row['id'],state='LIVE_OPPORTUNITY_UNAVAILABLE'));continue
                if proposal is None:continue
                # A provider cannot change the selected quantity or objective.
                if proposal['draft'].quantity!=row['quantity'] or proposal['target']!=row['target']:
                    raise RealOrderBlocked('LIVE_QUEUE_SELECTION_CHANGED')
                from option_market_data import _parse_occ_symbol
                import re
                _parse_occ_symbol(proposal['draft'].contract.replace(' ',''))
                root=re.match(r'([A-Z0-9.]{1,8}) *\d{6}[CP]\d{8}',proposal['draft'].contract).group(1)
                if root!=row['symbol'] or aware(proposal['session_close'])!=aware(datetime.fromisoformat(plan['session_close'])):
                    raise RealOrderBlocked('LIVE_QUEUE_SELECTION_CHANGED')
                first=aware(proposal['first_signal_at']);key=proposal['signal_key']
                after=aware(datetime.fromisoformat(row['completed_at'] or plan['armed_at']))
                if first<=after or key in row['used_signals']:continue
                def claim(current,item):
                    if current.get('first_entry_only'):
                        if current.get('entry_owner') or current.get('entry_consumed'):
                            raise RealOrderBlocked('LIVE_FIRST_ENTRY_RESERVED')
                        current['entry_owner']=item['id']
                    if current['paused'] or item['state']!='ARMED':raise RealOrderBlocked('LIVE_QUEUE_PAUSED')
                    if aware(self.clock())>=aware(datetime.fromisoformat(current['session_close'])):
                        raise RealOrderBlocked('LIVE_QUEUE_SESSION_INVALID')
                    if key in item['used_signals']:raise RealOrderBlocked('LIVE_SIGNAL_ALREADY_USED')
                    item['state']='SUBMITTING';item['claim']=key;item['used_signals'].append(key)
                try:self._change(binding,plan['id'],row['id'],claim)
                except RealOrderBlocked as error:
                    if str(error)=='LIVE_FIRST_ENTRY_RESERVED':return events
                    raise
                try:order=execution.enter(**proposal)
                except Exception as error:
                    # Includes a crash/failed journal save/ambiguous broker send.
                    # Never renew this signal or clear its durable claim.
                    safe=False;retry_same=False
                    try:
                        journal=execution.ledger.requests(binding)
                        if isinstance(journal,list):
                            request=next((r for r in journal if r.get('intent')==key),None)
                            from real_execution_service import RealEntryNotDispatched
                            if request is None and isinstance(error,RealEntryNotDispatched):safe=True;retry_same=True
                            elif request is not None and request['state']=='PREPARED' and not request.get('broker_id'):
                                execution.ledger.abandon_prepared(binding,request['id']);safe=True
                    except Exception:pass
                    def failed(current,item):
                        item['state']='ARMED' if safe and not current['paused'] else 'REQUIRES_REVIEW'
                        if safe:item['claim']=None
                        if retry_same:item['used_signals'].remove(key)
                        if safe and current.get('first_entry_only') and not current.get('entry_consumed'):
                            current['entry_owner']=None
                    self._change(binding,plan['id'],row['id'],failed)
                    events.append(dict(id=row['id'],state='LIVE_NOT_DISPATCHED' if safe else 'LIVE_QUEUE_REQUIRES_REVIEW'))
                    if plan.get('first_entry_only'):return events
                    continue
                self._change(binding,plan['id'],row['id'],lambda p,r:r.update(
                    state='ORDER_SENT' if order.get('broker_id') or order.get('state') in TERMINAL else 'REQUIRES_REVIEW',request_id=order['id']))
                events.append(order)
                # Do not prepare/preview other companies while a purchase is pending.
                if plan.get('first_entry_only'):return events
            return events
