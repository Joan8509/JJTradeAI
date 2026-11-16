"""Place the chosen profit LIMIT after a final confirmed buy, in its own loop."""
from datetime import datetime,timedelta,timezone
from threading import Lock
from real_order_ledger import TERMINAL,UNCERTAIN
from schwab_connection import aware
from schwab_contracts import decimal
from schwab_target_limit import target_candidate,confirm_target_preview


class BrokerProfitTargets:
    def __init__(self,execution,preview,*,clock=lambda:datetime.now(timezone.utc)):
        self.execution=execution;self.preview=preview;self.clock=clock
        self._lock=Lock();self._status={};self._retry={}

    def status(self):
        with self._lock:return {k:dict(v) for k,v in self._status.items()}

    def step(self):
        rows=self.execution.ledger.requests(self.execution.binding)
        for buy in rows:
            plan=buy.get('exit_plan') or {}
            if (buy['instruction']!='BUY_TO_OPEN' or buy['state'] not in TERMINAL or not buy['fills']
                    or plan.get('target') in (None,'MANUAL')):continue
            children=[r for r in rows if r.get('parent_id')==buy['id']]
            bought=sum(f['quantity'] for f in buy['fills'].values())
            sold=sum(f['quantity'] for r in children for f in r['fills'].values())
            if sold>=bought:
                with self._lock:self._status.pop(buy['contract'],None)
                continue
            if buy.get('external_close_hold'):
                self._publish(buy['contract'],'EXTERNAL_MANUAL_CLOSE_DETECTED');continue
            from real_exit_recovery import unresolved_rejections
            if unresolved_rejections(buy,children):
                self._publish(buy['contract'],'BROKER_TARGET_REJECTED',error=True,review=True,parent_id=buy['id']);continue
            uncertain=next((r for r in children if r.get('exit_role')=='BROKER_TARGET' and r['state'] in UNCERTAIN),None)
            if uncertain:
                self._publish(buy['contract'],'BROKER_TARGET_'+uncertain['state'],error=True,review=True,parent_id=buy['id']);continue
            if buy.get('exit_trigger') in ('STOP','MANUAL'):
                self._publish(buy['contract'],buy['exit_trigger']+'_PRIORITY');continue
            active=[r for r in children if r['state'] not in TERMINAL]
            now=aware(self.clock())
            for row in active:
                if row.get('exit_role')=='BROKER_TARGET' and row['state']=='PREPARED' and now>=datetime.fromisoformat(row['expires_at']):
                    self.execution.ledger.abandon_prepared(self.execution.binding,row['id'])
            if active:
                native=next((r for r in active if r.get('exit_role')=='BROKER_TARGET'),None)
                if native:self._publish(buy['contract'],'BROKER_TARGET_'+native['state'],limit=native['limit'])
                else:self._publish(buy['contract'],'PRICE_EXIT_'+active[0]['state'],limit=active[0]['limit'],
                    error=active[0]['state'] in UNCERTAIN,review=active[0]['state'] in UNCERTAIN,parent_id=buy['id'])
                continue
            if now<self._retry.get(buy['id'],now):continue
            start,end=self.execution.exit_session_provider(now) if self.execution.exit_session_provider else (
                now,datetime.fromisoformat(plan['session_close']))
            if not aware(start)<=now<aware(end):continue
            try:
                if self.execution.exit_admission(buy['contract']) is not True:continue
                cost=sum(decimal(f['price'])*f['quantity'] for f in buy['fills'].values())/bought
                candidate=target_candidate(buy['contract'],bought-sold,cost,plan['target'],now=now,
                    valid_until=min(now+timedelta(seconds=10),aware(end)))
                self._publish(buy['contract'],'PREVIEWING_TARGET',limit=str(candidate.limit))
                # No price-monitor lock or entry HTTP is held during preview.
                report=self.preview.preview(candidate)
                draft,proof=confirm_target_preview(candidate,report,binding=self.execution.binding,
                    parent_id=buy['id'],account_number=self.execution._account_number,now=self.clock())
                result=self.execution.place_broker_target(buy['id'],draft,proof)
                review=result['state'] in UNCERTAIN or result['state']=='REJECTED'
                not_sent=result['state']=='EXPIRED' and 'ORDER_HTTP_NOT_ATTEMPTED' in result.get('issues',[])
                self._publish(buy['contract'],'BROKER_TARGET_'+result['state'],limit=result['limit'],
                    error=review or not_sent,review=review,parent_id=buy['id'])
                if not_sent:self._retry[buy['id']]=aware(self.clock())+timedelta(seconds=15)
            except Exception as error:
                code=getattr(error,'code',None) or str(error)
                import re
                if not re.fullmatch('[A-Z_]{1,100}',code):code='BROKER_TARGET_NOT_REGISTERED'
                self._publish(buy['contract'],code,error=True,parent_id=buy['id'])
                self._retry[buy['id']]=aware(self.clock())+timedelta(seconds=max(15,getattr(error,'retry_after_seconds',None) or 0))

    def _publish(self,contract,state,**fields):
        with self._lock:self._status[contract]=dict(state=state,checked_at=aware(self.clock()).isoformat(),**fields)
