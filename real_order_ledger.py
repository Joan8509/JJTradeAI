"""Durable encrypted execution journal, separate from simulation and credentials.

This module has no HTTP client, worker or production dispatch factory. A request
is committed before an injected gateway is called. Tests use fault injection;
production order wiring remains unavailable until its protocol is verified.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re,secrets

from schwab_connection import aware
from real_live_storage import RealEncryptedStore as EncryptedSchwabStore
from schwab_contracts import decimal,positive_int
from schwab_reconciliation import normalize_order

PURPOSE='REAL_ORDER_JOURNAL_V1'
TERMINAL={'FILLED','CANCELED','REJECTED','EXPIRED'}
UNCERTAIN={'SUBMITTING','UNCERTAIN','CANCEL_SUBMITTING','CANCEL_UNCERTAIN','RECONCILIATION_REQUIRED'}


class RealOrderBlocked(RuntimeError):pass


class RealOrderStore(EncryptedSchwabStore):
    def __init__(self):
        self.path=Path(__file__).resolve().parent/'exports/private_runtime/real_orders.dpapi'


def _key(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise RealOrderBlocked('ACCOUNT_BINDING_REQUIRED')


class RealOrderLedger:
    def __init__(self,store_factory=RealOrderStore,clock=lambda:datetime.now(timezone.utc)):
        self.store_factory=store_factory;self.clock=clock

    @contextmanager
    def _document(self,*,write=False):
        store=self.store_factory()
        with store.locked():
            doc=store.load() if store.path.exists() else dict(purpose=PURPOSE,requests={},events=[])
            if doc.get('purpose')!=PURPOSE or not isinstance(doc.get('requests'),dict) or not isinstance(doc.get('events'),list):
                raise RealOrderBlocked('ORDER_JOURNAL_INVALID')
            yield doc
            if write:store.save(doc)

    def _event(self,doc,row,state):
        row['state']=state;row['updated_at']=aware(self.clock()).isoformat()
        doc['events'].append(dict(request=row['id'],state=state,at=row['updated_at']))

    @staticmethod
    def _row(doc,binding,identity):
        row=doc['requests'].get(identity)
        if not row or row['account']!=binding:raise RealOrderBlocked('REQUEST_NOT_OWNED')
        return row

    def requests(self,binding):
        _key(binding)
        with self._document() as doc:
            return deepcopy([r for r in doc['requests'].values() if r['account']==binding])

    @staticmethod
    def _available(doc,binding,contract):
        owned=reserved=0
        for row in doc['requests'].values():
            if row['account']!=binding or row['contract']!=contract:continue
            filled=sum(f['quantity'] for f in row['fills'].values())
            if row['instruction']=='BUY_TO_OPEN':owned+=filled
            else:
                owned-=filled
                if row['state'] not in TERMINAL:reserved+=row['quantity']-filled
        return owned-reserved

    def available_to_close(self,binding,contract):
        _key(binding)
        with self._document() as doc:return self._available(doc,binding,contract)

    def prepare(self,binding,*,intent,contract,instruction,quantity,limit,expires_at,price_increment,
                exit_plan=None,parent_id=None,enforce_symbol_exposure=False,price_validation='VERIFIED_INCREMENT',estimated_cost=None,
                price_proof=None,exit_role=None,exit_retry_proof=None):
        """Reserve only owned closes; persist no inferred account-wide positions."""
        _key(binding);positive_int(quantity)
        if (not isinstance(intent,str) or not 1<=len(intent)<=256 or
            not isinstance(contract,str) or not re.fullmatch(r'[A-Z0-9.]{1,8} *\d{6}[CP]\d{8}',contract)):
            raise RealOrderBlocked('ORDER_IDENTITY_INVALID')
        from option_market_data import _parse_occ_symbol
        _parse_occ_symbol(contract.replace(' ',''))
        if instruction not in ('BUY_TO_OPEN','SELL_TO_CLOSE'):raise RealOrderBlocked('INSTRUCTION_NOT_SUPPORTED')
        limit=decimal(limit)
        if price_validation not in ('VERIFIED_INCREMENT','OBSERVED_SCHWAB_QUOTE','SCHWAB_PREVIEWED_LIMIT') or limit<=0:
            raise RealOrderBlocked('PRICE_INCREMENT_NOT_VERIFIED')
        if price_validation=='VERIFIED_INCREMENT':
            increment=decimal(price_increment)
            if increment<=0 or limit%increment!=0:raise RealOrderBlocked('PRICE_INCREMENT_NOT_VERIFIED')
        if estimated_cost is not None and decimal(estimated_cost)<limit*100*quantity:raise RealOrderBlocked('ENTRY_COST_INVALID')
        expires=aware(expires_at);now=aware(self.clock())
        if expires<=now:raise RealOrderBlocked('REQUEST_EXPIRED')
        if price_validation=='SCHWAB_PREVIEWED_LIMIT':
            from schwab_target_limit import validate_target_proof
            if exit_role!='BROKER_TARGET':raise RealOrderBlocked('BROKER_TARGET_ROLE_REQUIRED')
            validate_target_proof(price_proof,binding=binding,parent_id=parent_id,contract=contract,
                instruction=instruction,quantity=quantity,limit=limit,expires_at=expires)
        elif price_proof is not None or exit_role is not None:raise RealOrderBlocked('BROKER_TARGET_PROOF_INVALID')
        if exit_plan is not None:
            if instruction!='BUY_TO_OPEN' or not isinstance(exit_plan,dict) or set(exit_plan)!={'target','stop','session_close'}:
                raise RealOrderBlocked('EXIT_PLAN_INVALID')
            if exit_plan['target'] not in ('10','20','35','100','MANUAL') or exit_plan['stop']!='20':
                raise RealOrderBlocked('EXIT_PLAN_INVALID')
            if aware(datetime.fromisoformat(exit_plan['session_close']))<=now:raise RealOrderBlocked('EXIT_PLAN_INVALID')
        symbol=re.match(r'([A-Z0-9.]{1,8}) *\d{6}[CP]\d{8}',contract).group(1)
        with self._document(write=True) as doc:
            rows=[r for r in doc['requests'].values() if r['account']==binding]
            existing=next((r for r in rows if r['intent']==intent),None)
            if existing:
                if (existing['contract'],existing['instruction'],existing['quantity'],decimal(existing['limit']))!=(contract,instruction,quantity,limit):
                    raise RealOrderBlocked('INTENT_ALREADY_BOUND')
                if existing.get('exit_plan')!=exit_plan or existing.get('parent_id')!=parent_id:
                    raise RealOrderBlocked('INTENT_ALREADY_BOUND')
                if existing.get('price_validation','VERIFIED_INCREMENT')!=price_validation:raise RealOrderBlocked('INTENT_ALREADY_BOUND')
                if existing.get('price_proof')!=price_proof or existing.get('exit_role')!=exit_role:raise RealOrderBlocked('INTENT_ALREADY_BOUND')
                return deepcopy(existing)
            if instruction=='BUY_TO_OPEN':
                if any(r['state'] in UNCERTAIN for r in rows):raise RealOrderBlocked('ACCOUNT_HAS_UNCERTAIN_ORDER')
                if any(r['contract']==contract and r['state'] not in TERMINAL for r in rows):
                    raise RealOrderBlocked('CONTRACT_HAS_ACTIVE_ORDER')
                if enforce_symbol_exposure:
                    company_contracts={r['contract'] for r in rows if re.match(
                        r'([A-Z0-9.]{1,8}) *\d{6}[CP]\d{8}',r['contract']).group(1)==symbol}
                    for other in company_contracts:
                        owned=sum(sum(f['quantity'] for f in r['fills'].values()) *
                            (1 if r['instruction']=='BUY_TO_OPEN' else -1) for r in rows if r['contract']==other)
                        if owned>0 or any(r['contract']==other and r['state'] not in TERMINAL for r in rows):
                            raise RealOrderBlocked('SYMBOL_HAS_EXPOSURE')
            elif quantity>self._available(doc,binding,contract):raise RealOrderBlocked('CLOSE_QUANTITY_NOT_OWNED')
            if parent_id is not None:
                parent=self._row(doc,binding,parent_id)
                if instruction!='SELL_TO_CLOSE' or parent['instruction']!='BUY_TO_OPEN' or parent['contract']!=contract:
                    raise RealOrderBlocked('CLOSE_PARENT_INVALID')
                parent_owned=sum(f['quantity'] for f in parent['fills'].values())
                for child in rows:
                    if child.get('parent_id')!=parent_id:continue
                    filled=sum(f['quantity'] for f in child['fills'].values())
                    parent_owned-=filled
                    if child['state'] not in TERMINAL:parent_owned-=child['quantity']-filled
                if quantity>parent_owned:raise RealOrderBlocked('CLOSE_PARENT_QUANTITY_NOT_OWNED')
                from real_exit_recovery import unresolved_rejections,validate_retry_proof
                rejected=unresolved_rejections(parent,[r for r in rows if r.get('parent_id')==parent_id])
                if rejected or exit_retry_proof is not None:
                    validate_retry_proof(exit_retry_proof,binding=binding,parent=parent,
                        rejected=rejected,quantity=quantity,now=now)
                    parent['exit_recovery_used']=True
                    parent['resolved_exit_rejections']=sorted(set(parent.get('resolved_exit_rejections',()))|
                        {r['id'] for r in rejected})
                    doc['events'].append(dict(request=parent_id,exit_recovery_proof=deepcopy(exit_retry_proof),at=now.isoformat()))
            elif exit_retry_proof is not None:raise RealOrderBlocked('CLOSE_PARENT_INVALID')
            identity=secrets.token_hex(16)
            row=dict(id=identity,account=binding,intent=intent,contract=contract,instruction=instruction,
                quantity=quantity,limit=str(limit),expires_at=expires.isoformat(),broker_id=None,
                fills={},created_at=now.isoformat(),issues=[],terminal_state=None,price_validation=price_validation)
            if exit_plan is not None:row['exit_plan']=deepcopy(exit_plan)
            if estimated_cost is not None:row['estimated_cost']=str(decimal(estimated_cost))
            if parent_id is not None:row['parent_id']=parent_id
            if exit_retry_proof is not None:
                row['exit_recovery_proof']=deepcopy(exit_retry_proof)
                parent['exit_recovery_request']=identity
            if price_proof is not None:row['price_proof']=deepcopy(price_proof);row['exit_role']=exit_role
            doc['requests'][identity]=row;self._event(doc,row,'PREPARED')
            return deepcopy(row)

    def trigger_exit(self,binding,identity,reason):
        """Persist a local trigger before dispatch; STOP never reverts to profit."""
        if reason not in ('STOP','TARGET','MANUAL'):raise RealOrderBlocked('EXIT_REASON_INVALID')
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row['instruction']!='BUY_TO_OPEN' or not row.get('exit_plan'):
                raise RealOrderBlocked('EXIT_PLAN_REQUIRED')
            if row.get('exit_trigger')!='STOP':row['exit_trigger']=reason
            doc['events'].append(dict(request=identity,exit_trigger=row['exit_trigger'],at=aware(self.clock()).isoformat()))
            return deepcopy(row)

    def begin_submit(self,binding,identity):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row['state']!='PREPARED':raise RealOrderBlocked('REQUEST_ALREADY_DISPATCHED')
            if aware(self.clock())>=datetime.fromisoformat(row['expires_at']):raise RealOrderBlocked('REQUEST_EXPIRED')
            if row['instruction']=='BUY_TO_OPEN' and any(r['account']==binding and r['state'] in UNCERTAIN for r in doc['requests'].values()):
                raise RealOrderBlocked('ACCOUNT_HAS_UNCERTAIN_ORDER')
            self._event(doc,row,'SUBMITTING');return deepcopy(row)

    def abandon_prepared(self,binding,identity):
        """Only a request proven never dispatched may expire locally."""
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row['state']!='PREPARED' or row.get('broker_id'):
                raise RealOrderBlocked('REQUEST_MAY_HAVE_BEEN_DISPATCHED')
            row['issues']=['LOCAL_REQUEST_NOT_DISPATCHED'];row['terminal_state']='EXPIRED'
            self._release_exit_retry(doc,row)
            self._event(doc,row,'EXPIRED');return deepcopy(row)

    @staticmethod
    def _release_exit_retry(doc,row):
        proof=row.get('exit_recovery_proof')
        if not proof:return
        parent=doc['requests'].get(row.get('parent_id'))
        if parent and parent.get('exit_recovery_request')==row['id']:
            parent['exit_recovery_used']=False
            parent['resolved_exit_rejections']=sorted(set(parent.get('resolved_exit_rejections',()))-set(proof['rejected_ids']))
            parent.pop('exit_recovery_request',None)

    def submission_result(self,binding,identity,broker_id=None):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if isinstance(broker_id,str) and row.get('broker_id')==broker_id:
                return deepcopy(row) # Independent receipt recovery already committed it.
            if row['state']!='SUBMITTING':raise RealOrderBlocked('SUBMISSION_STATE_INVALID')
            valid=isinstance(broker_id,str) and re.fullmatch('[0-9]{1,32}',broker_id)
            if valid and any(r['account']==binding and r['broker_id']==broker_id for r in doc['requests'].values()):valid=False
            row['broker_id']=broker_id if valid else None
            self._event(doc,row,'ACKNOWLEDGED' if valid else 'UNCERTAIN')
            return deepcopy(row)

    def submission_not_attempted(self,binding,identity,code):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row['state']!='SUBMITTING' or row.get('broker_id') or row['fills']:
                raise RealOrderBlocked('REQUEST_MAY_HAVE_BEEN_DISPATCHED')
            row['issues']=['ORDER_HTTP_NOT_ATTEMPTED',code if re.fullmatch('[A-Z_]{1,100}',code) else 'ORDER_PREPARATION_FAILED']
            self._release_exit_retry(doc,row)
            row['terminal_state']='EXPIRED';self._event(doc,row,'EXPIRED');return deepcopy(row)

    def recover_submission_receipt(self,binding,identity,broker_id):
        if not isinstance(broker_id,str) or not re.fullmatch('[0-9]{1,32}',broker_id):
            raise RealOrderBlocked('ORDER_RECEIPT_INVALID')
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row.get('broker_id')==broker_id:return deepcopy(row)
            if row.get('broker_id') or row['state'] not in ('SUBMITTING','UNCERTAIN') or row['fills']:
                raise RealOrderBlocked('SUBMISSION_STATE_INVALID')
            if any(r['account']==binding and r.get('broker_id')==broker_id for r in doc['requests'].values()):
                raise RealOrderBlocked('BROKER_ORDER_IDENTITY_MISMATCH')
            row['broker_id']=broker_id
            self._event(doc,row,'ACKNOWLEDGED');return deepcopy(row)

    def reconcile(self,binding,identity,payload):
        """Only exact confirmed IDs; partial fills and identities never regress."""
        evidence=normalize_order(payload)
        return self._reconcile_evidence(binding,identity,evidence,'BROKER_EXECUTION_ID')

    def reconcile_snapshot(self,binding,identity,payload,*,account_number):
        """Complete GET history for the explicitly bound server-side account.

        Never accepts a preview, average-price reconstruction or anonymous fill.
        The caller supplies account_number from its private account context.
        """
        from schwab_execution_snapshot import normalize_execution_snapshot
        evidence=normalize_execution_snapshot(payload,account_number=account_number)
        return self._reconcile_evidence(binding,identity,evidence,'CUMULATIVE_EXECUTION_RECORD')

    def record_confirmed_manual_close(self,binding,parent_id,payload,*,account_number):
        """Explicit reconciliation of a user-confirmed external LIMIT close.

        Never called by automatic discovery. No order is created at the broker,
        and no external buy/position is adopted. Unknown concurrent closes must
        first be reconciled to terminal evidence, preserving reservations.
        """
        return self._record_manual_close(binding,parent_id,payload,account_number=account_number,automatic=False)

    def flag_external_close(self,binding,parent_id,broker_ids):
        """Durable hold precedes cancellation/import; a restart cannot resell."""
        if not broker_ids or any(not re.fullmatch('[1-9][0-9]{0,18}',str(v)) for v in broker_ids):
            raise RealOrderBlocked('MANUAL_CLOSE_ID_REQUIRED')
        with self._document(write=True) as doc:
            parent=self._row(doc,binding,parent_id)
            if parent['instruction']!='BUY_TO_OPEN' or not parent['fills']:
                raise RealOrderBlocked('MANUAL_CLOSE_PARENT_INVALID')
            parent['external_close_hold']=True
            parent['external_close_ids']=sorted(set(parent.get('external_close_ids',()))|set(map(str,broker_ids)))
            doc['events'].append(dict(request=parent_id,external_close_hold=True,at=aware(self.clock()).isoformat()))

    def resolve_external_close(self,binding,parent_id,broker_ids):
        with self._document(write=True) as doc:
            parent=self._row(doc,binding,parent_id)
            related=[r for r in doc['requests'].values() if r['account']==binding and
                (r.get('parent_id')==parent_id or r['id']==parent_id)]
            if any(r['state'] not in TERMINAL for r in related):
                raise RealOrderBlocked('MANUAL_CLOSE_ACTIVE_ORDER_REQUIRES_REVIEW')
            resolved=set(parent.get('external_close_resolved',()))|set(broker_ids)
            if not set(parent.get('external_close_ids',()))<=resolved:
                raise RealOrderBlocked('MANUAL_CLOSE_UNRESOLVED_ORDER')
            parent['external_close_resolved']=sorted(resolved);parent['external_close_hold']=False
            doc['events'].append(dict(request=parent_id,external_close_hold=False,at=aware(self.clock()).isoformat()))

    def record_detected_manual_close(self,binding,parent_id,payload,*,account_number):
        """User-authorized automatic attribution of a terminal external close."""
        return self._record_manual_close(binding,parent_id,payload,account_number=account_number,automatic=True)

    def _record_manual_close(self,binding,parent_id,payload,*,account_number,automatic):
        from schwab_execution_snapshot import normalize_execution_snapshot
        _key(binding)
        evidence=normalize_execution_snapshot(payload,account_number=account_number)
        order_type=payload.get('orderType')
        allowed={'FILLED','CANCELED','EXPIRED'} if automatic else {'FILLED'}
        if (evidence.status not in allowed or evidence.issues or evidence.instruction!='SELL_TO_CLOSE'
                or order_type not in ({'LIMIT','MARKET'} if automatic else {'LIMIT'}) or not evidence.fills):
            raise RealOrderBlocked('MANUAL_CLOSE_EXECUTION_REQUIRED')
        limit=decimal(payload['price']) if order_type=='LIMIT' else None
        entered=aware(datetime.fromisoformat(payload['enteredTime'].replace('Z','+00:00')))
        now=aware(self.clock())
        if (limit is not None and limit<=0) or entered>now:raise RealOrderBlocked('MANUAL_CLOSE_EXECUTION_INVALID')
        for fill in evidence.fills:
            if not entered<=aware(datetime.fromisoformat(fill['time']))<=now or (limit is not None and decimal(fill['price'])<limit):
                raise RealOrderBlocked('MANUAL_CLOSE_EXECUTION_INVALID')
        with self._document(write=True) as doc:
            parent=self._row(doc,binding,parent_id)
            if (parent['instruction']!='BUY_TO_OPEN' or parent['contract']!=evidence.contract
                    or parent['state'] not in TERMINAL or not parent['fills']
                    or entered<aware(datetime.fromisoformat(parent['created_at']))):
                raise RealOrderBlocked('MANUAL_CLOSE_PARENT_INVALID')
            rows=[r for r in doc['requests'].values() if r['account']==binding]
            origin='BROKER_DETECTED_MANUAL_CLOSE' if automatic else 'USER_CONFIRMED_MANUAL_CLOSE'
            if automatic and (not parent.get('external_close_hold') or
                    evidence.broker_id not in parent.get('external_close_ids',())):
                raise RealOrderBlocked('MANUAL_CLOSE_HOLD_REQUIRED')
            existing=next((r for r in rows if r.get('broker_id')==evidence.broker_id),None)
            fills={f['record_key']:dict(f) for f in evidence.fills}
            if existing:
                if (existing.get('origin')!=origin or existing.get('parent_id')!=parent_id
                        or existing['fills']!=fills or existing['quantity']!=evidence.quantity):
                    raise RealOrderBlocked('BROKER_ORDER_IDENTITY_MISMATCH')
                return deepcopy(existing)
            if any(r['contract']==evidence.contract and r['state'] not in TERMINAL for r in rows):
                raise RealOrderBlocked('MANUAL_CLOSE_ACTIVE_ORDER_REQUIRES_REVIEW')
            children=[r for r in rows if r.get('parent_id')==parent_id]
            remaining=sum(f['quantity'] for f in parent['fills'].values())-sum(
                f['quantity'] for r in children for f in r['fills'].values())
            actual=sum(f['quantity'] for f in evidence.fills) if automatic else evidence.quantity
            if (evidence.quantity>sum(f['quantity'] for f in parent['fills'].values()) or
                    actual>remaining or actual>self._available(doc,binding,evidence.contract)):
                raise RealOrderBlocked('CLOSE_QUANTITY_NOT_OWNED')
            if any(aware(datetime.fromisoformat(f['time']))>entered for f in parent['fills'].values()):
                raise RealOrderBlocked('MANUAL_CLOSE_PARENT_INVALID')
            identity=secrets.token_hex(16)
            row=dict(id=identity,account=binding,intent='EXTERNAL_CLOSE:'+evidence.broker_id,
                contract=evidence.contract,instruction='SELL_TO_CLOSE',quantity=evidence.quantity,
                limit=str(limit) if limit is not None else None,expires_at=now.isoformat(),created_at=entered.isoformat(),
                broker_id=evidence.broker_id,fills=fills,issues=[],terminal_state=evidence.status,
                evidence_mode='CUMULATIVE_EXECUTION_RECORD',parent_id=parent_id,
                origin=origin,external_order_type=order_type,price_validation='BROKER_CONFIRMED_EXECUTION')
            doc['requests'][identity]=row;self._event(doc,row,evidence.status)
            return deepcopy(row)

    def _reconcile_evidence(self,binding,identity,evidence,mode):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if not row['broker_id'] or (evidence.broker_id,evidence.contract,evidence.instruction,evidence.quantity)!=(
                row['broker_id'],row['contract'],row['instruction'],row['quantity']):
                raise RealOrderBlocked('BROKER_ORDER_IDENTITY_MISMATCH')
            prior=row['fills'];incoming={}
            issues=list(evidence.issues)
            if row.get('evidence_mode',mode)!=mode:issues.append('EXECUTION_EVIDENCE_MODE_CHANGED')
            if evidence.status=='REPLACED':issues.append('REPLACEMENT_REQUIRES_REVIEW')
            try:
                for fill in evidence.fills:
                    stamp=aware(datetime.fromisoformat(fill['time'].replace('Z','+00:00')))
                    if not datetime.fromisoformat(row['created_at'])<=stamp<=aware(self.clock()):issues.append('EXECUTION_TIME_UNPROVEN')
                    if row['instruction']=='BUY_TO_OPEN' and decimal(fill['price'])>decimal(row['limit']):issues.append('LIMIT_PRICE_VIOLATION')
                    if row['instruction']=='SELL_TO_CLOSE' and decimal(fill['price'])<decimal(row['limit']):issues.append('LIMIT_PRICE_VIOLATION')
                    key=fill['record_key'] if mode=='CUMULATIVE_EXECUTION_RECORD' else fill['execution_id']
                    incoming[key]=dict(fill,price=str(decimal(fill['price']).normalize()),time=stamp.isoformat())
            except (ValueError,TypeError,KeyError):issues.append('EXECUTION_TIME_UNPROVEN')
            if any(k not in incoming or incoming[k]!=v for k,v in prior.items()):issues.append('EXECUTION_HISTORY_REGRESSION')
            if row.get('terminal_state') and evidence.status!=row['terminal_state']:issues.append('TERMINAL_STATE_CHANGED')
            row['issues']=sorted(set(issues))
            if issues:
                self._event(doc,row,'RECONCILIATION_REQUIRED')
            else:
                row['fills']=incoming
                row['evidence_mode']=mode
                if evidence.status in TERMINAL:row['terminal_state']=evidence.status
                status=evidence.status
                if row.get('cancel_requested') and status not in TERMINAL:
                    status=('CANCEL_SUBMITTING' if row['state']=='CANCEL_SUBMITTING' else
                        'PENDING_CANCEL' if row.get('cancel_accepted') is True else 'CANCEL_UNCERTAIN')
                self._event(doc,row,status)
            return deepcopy(row)

    def begin_cancel(self,binding,identity):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if not row['broker_id'] or row['state'] not in ('ACKNOWLEDGED','WORKING','PARTIALLY_FILLED'):
                raise RealOrderBlocked('CANCELLATION_NOT_READY')
            row['cancel_previous_state']=row['state'];row['cancel_requested']=True
            self._event(doc,row,'CANCEL_SUBMITTING');return deepcopy(row)

    def cancellation_not_attempted(self,binding,identity):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row['state'] in TERMINAL:return deepcopy(row)
            if row['state']!='CANCEL_SUBMITTING':raise RealOrderBlocked('CANCELLATION_STATE_INVALID')
            row['cancel_requested']=False;row['cancel_accepted']=None
            row['issues']=['CANCEL_HTTP_NOT_ATTEMPTED']
            self._event(doc,row,row.get('cancel_previous_state','WORKING'));return deepcopy(row)

    def cancel_result(self,binding,identity,*,accepted):
        with self._document(write=True) as doc:
            row=self._row(doc,binding,identity)
            if row['state'] in TERMINAL:
                row['cancel_accepted']=accepted is True
                return deepcopy(row)
            if row['state']!='CANCEL_SUBMITTING':raise RealOrderBlocked('CANCELLATION_STATE_INVALID')
            row['cancel_accepted']=accepted is True
            self._event(doc,row,'PENDING_CANCEL' if accepted is True else 'CANCEL_UNCERTAIN')
            return deepcopy(row)


class RealOrderCoordinator:
    """Gateway protocol under test. No production gateway is constructed here.

    The future production service must verify account, cash, signal, increments,
    risk, session and exit-monitor readiness before issuing its submission grant.
    Selecting a UI view or saving a draft never supplies such a grant.
    """
    def __init__(self,ledger,gateway,submission_grant,*,receipts=None):
        self.ledger=ledger;self.gateway=gateway;self.grant=submission_grant
        self.receipts=receipts
        self._pending_results={}
        self.submission_observer=None

    def _wake_observer(self):
        if callable(self.submission_observer):
            try:self.submission_observer()
            except Exception:pass

    def recover_receipts(self,binding):
        from real_submission_receipts import fingerprint
        receipts=self.receipts.read(binding) if self.receipts is not None else []
        receipts+=list(self._pending_results.values())
        rows={r['id']:r for r in self.ledger.requests(binding)}
        for receipt in receipts:
            if receipt['account']!=binding:continue
            row=rows.get(receipt['request'])
            if row is None or fingerprint(row)!=receipt['fingerprint']:
                raise RealOrderBlocked('ORDER_RECEIPT_IDENTITY_MISMATCH')
            if row.get('broker_id'):
                if row['broker_id']!=receipt['broker_id']:raise RealOrderBlocked('ORDER_RECEIPT_IDENTITY_MISMATCH')
            elif row['state'] in ('SUBMITTING','UNCERTAIN'):
                # UNCERTAIN is not permission to POST again. Rebind only an
                # authentic, locally persisted exact-ID receipt, then normal GET.
                self.ledger.recover_submission_receipt(binding,row['id'],receipt['broker_id'])
            self._pending_results.pop(row['id'],None)

    def submit(self,binding,identity):
        from schwab_order_gateway import OrderNotDispatched
        if self.grant(binding,identity,'SUBMIT') is not True:raise RealOrderBlocked('LIVE_SUBMISSION_NOT_AUTHORIZED')
        row=self.ledger.begin_submit(binding,identity)
        try:broker_id=self.gateway.submit(row)
        except OrderNotDispatched as error:return self.ledger.submission_not_attempted(binding,identity,error.code)
        except Exception:broker_id=None
        if broker_id is not None:
            from real_submission_receipts import fingerprint
            self._pending_results[identity]=dict(account=binding,request=identity,
                broker_id=broker_id,fingerprint=fingerprint(row))
            if self.receipts is not None:
                # Independent durable copy before the normal journal update.
                # If this local save fails, still try the journal; no HTTP retry.
                try:self.receipts.record(row,broker_id)
                except Exception:pass
        try:return self.ledger.submission_result(binding,identity,broker_id)
        finally:self._wake_observer()

    def cancel(self,binding,identity):
        from schwab_order_gateway import OrderNotDispatched
        if self.grant(binding,identity,'CANCEL') is not True:raise RealOrderBlocked('LIVE_CANCELLATION_NOT_AUTHORIZED')
        row=self.ledger.begin_cancel(binding,identity)
        try:accepted=self.gateway.cancel(row) is True
        except OrderNotDispatched:return self.ledger.cancellation_not_attempted(binding,identity)
        except Exception:accepted=False
        try:return self.ledger.cancel_result(binding,identity,accepted=accepted)
        finally:self._wake_observer()


def production_gateway():
    raise RealOrderBlocked('LIVE_PROTOCOL_NOT_VERIFIED')
