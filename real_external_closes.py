"""Observe manual Schwab/thinkorswim closes of app-owned contracts only."""
from datetime import datetime,timezone
from threading import Lock

from real_order_ledger import TERMINAL,RealOrderBlocked
from schwab_connection import aware
from schwab_execution_snapshot import normalize_execution_snapshot


def _order_legs(order,depth=0):
    if not isinstance(order,dict) or depth>5:return []
    legs=order.get('orderLegCollection') or []
    result=[leg for leg in legs if isinstance(leg,dict)] if isinstance(legs,list) else []
    for child in order.get('childOrderStrategies') or []:
        result.extend(_order_legs(child,depth+1))
    return result


class ExternalManualCloses:
    def __init__(self,execution,queue,read_orders,*,clock=lambda:datetime.now(timezone.utc)):
        self.execution=execution;self.queue=queue;self.read_orders=read_orders;self.clock=clock
        self._lock=Lock();self._status={}

    def status(self):
        with self._lock:return {key:dict(value) for key,value in self._status.items()}

    def _publish(self,parent,state,**fields):
        with self._lock:self._status[parent['contract']]=dict(state=state,parent_id=parent['id'],
            checked_at=aware(self.clock()).isoformat(),**fields)

    def step(self):
        execution=self.execution;binding=execution.binding
        rows=execution.ledger.requests(binding)
        parents=[]
        for buy in rows:
            if buy['instruction']!='BUY_TO_OPEN' or not buy['fills']:continue
            sold=sum(f['quantity'] for r in rows if r.get('parent_id')==buy['id'] for f in r['fills'].values())
            if buy.get('external_close_hold') or sum(f['quantity'] for f in buy['fills'].values())>sold:
                parents.append(buy)
        if not parents:return
        now=aware(self.clock())
        start=min(aware(datetime.fromisoformat(p['created_at'])) for p in parents)
        orders=self.read_orders(start,now)
        if not isinstance(orders,list):raise RealOrderBlocked('EXTERNAL_CLOSE_ORDERS_UNAVAILABLE')
        known={str(r['broker_id']) for r in rows if r.get('broker_id')}
        for parent in parents:
            ids=set(parent.get('external_close_ids',()))-set(parent.get('external_close_resolved',()))
            same_contract_buys=[]
            for order in orders:
                if not isinstance(order,dict):continue
                if str(order.get('accountNumber',''))!=execution._account_number:continue
                try:
                    entered=aware(datetime.fromisoformat(order['enteredTime'].replace('Z','+00:00')))
                    if entered<aware(datetime.fromisoformat(parent['created_at'])):continue
                except (KeyError,TypeError,ValueError):pass
                identity=str(order.get('orderId',''))
                if identity in known or identity in parent.get('external_close_resolved',()):continue
                legs=_order_legs(order)
                matching=[leg for leg in legs if isinstance(leg,dict) and
                    (leg.get('instrument') or {}).get('symbol')==parent['contract']]
                if any(leg.get('instruction')=='SELL_TO_CLOSE' for leg in matching):ids.add(identity)
                if any(leg.get('instruction')=='BUY_TO_OPEN' for leg in matching):same_contract_buys.append(identity)
            if not ids:continue
            try:
                if not parent.get('external_close_hold') or not ids<=set(parent.get('external_close_ids',())):
                    execution.ledger.flag_external_close(binding,parent['id'],ids)
                self._publish(parent,'MANUAL_CLOSE_DETECTED',detected=True)
                # Persist before any network action. A later close never rearms.
                plan=self.queue.read(binding)
                if plan and (not plan['paused'] or any(r.get('repeat_new_signals') for r in plan['rows'])):
                    self.queue.pause(binding)
                if len([p for p in parents if p['contract']==parent['contract']])!=1 or same_contract_buys:
                    raise RealOrderBlocked('EXTERNAL_CLOSE_ATTRIBUTION_REQUIRES_REVIEW')
                if not self._quiesce_own_orders(parent):
                    self._publish(parent,'WAITING_APP_ORDER_CANCELLATION',detected=True);continue
                observations=[]
                for identity in sorted(ids):
                    raw=execution.read_order(identity)
                    evidence=normalize_execution_snapshot(raw,account_number=execution._account_number)
                    if (evidence.broker_id!=identity or evidence.contract!=parent['contract'] or
                            evidence.instruction!='SELL_TO_CLOSE' or evidence.issues or
                            raw.get('orderType') not in ('MARKET','LIMIT')):
                        raise RealOrderBlocked('EXTERNAL_CLOSE_EVIDENCE_REQUIRES_REVIEW')
                    entered=aware(datetime.fromisoformat(raw['enteredTime'].replace('Z','+00:00')))
                    if not aware(datetime.fromisoformat(parent['created_at']))<=entered<=aware(self.clock()):
                        raise RealOrderBlocked('EXTERNAL_CLOSE_TIME_REQUIRES_REVIEW')
                    observations.append((raw,evidence))
                if any(e.status not in TERMINAL for _,e in observations):
                    self._publish(parent,'WAITING_MANUAL_ORDER_FINAL',detected=True);continue
                for raw,evidence in observations:
                    if evidence.fills:
                        execution.ledger.record_detected_manual_close(binding,parent['id'],raw,
                            account_number=execution._account_number)
                execution.ledger.resolve_external_close(binding,parent['id'],ids)
                current=execution.ledger.requests(binding)
                fresh_parent=next(r for r in current if r['id']==parent['id'])
                remaining=sum(f['quantity'] for f in fresh_parent['fills'].values())-sum(
                    f['quantity'] for r in current if r.get('parent_id')==parent['id'] for f in r['fills'].values())
                self._publish(parent,'MANUAL_CLOSE_RECONCILED',detected=True,remaining=remaining)
            except Exception as error:
                import re
                code=str(error)
                if not re.fullmatch('[A-Z_]{1,100}',code):code='EXTERNAL_CLOSE_REQUIRES_REVIEW'
                self._publish(parent,code,detected=True,review=True)

    def _quiesce_own_orders(self,parent):
        execution=self.execution;binding=execution.binding
        rows=execution.ledger.requests(binding)
        active=[r for r in rows if (r['id']==parent['id'] or r.get('parent_id')==parent['id']) and r['state'] not in TERMINAL]
        for row in active:
            if row['state']=='PREPARED' and not row.get('broker_id'):
                execution.ledger.abandon_prepared(binding,row['id']);continue
            if not row.get('broker_id'):return False
            payload=execution.read_order(row['broker_id'])
            observed=execution.ledger.reconcile_snapshot(binding,row['id'],payload,account_number=execution._account_number)
            if observed['state'] in ('ACKNOWLEDGED','WORKING','PARTIALLY_FILLED'):
                execution.coordinator.cancel(binding,row['id'])
            elif observed['state'] not in TERMINAL:return False
        return not any(r['state'] not in TERMINAL for r in execution.ledger.requests(binding)
            if r['id']==parent['id'] or r.get('parent_id')==parent['id'])
