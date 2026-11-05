"""Encrypted control plane between the dashboard and the supervised REAL host."""
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from contextlib import closing

from schwab_connection import aware
from real_live_storage import RealEncryptedStore as EncryptedSchwabStore
from real_automatic_queue import RealAutomaticQueue
from real_trade_preparation import _binding

ROOT=Path(__file__).resolve().parent


class RealControlStore(EncryptedSchwabStore):
    def __init__(self):self.path=ROOT/'exports/private_runtime/real_control.dpapi'


class RealHostStatusStore(EncryptedSchwabStore):
    def __init__(self):self.path=ROOT/'exports/private_runtime/real_host_status.dpapi'


def control_document(store):
    value=store.load() if store.path.exists() else dict(purpose='REAL_CONTROL_V1',account=None,protocol=None)
    if value.get('purpose')!='REAL_CONTROL_V1':raise ValueError('LIVE_CONTROL_INVALID')
    return value


def register_selected_account(context,*,store_factory=RealControlStore):
    """Persist an already explicitly selected account. Does not arm anything."""
    _binding(context.binding);store=store_factory()
    with store.locked():
        value=control_document(store)
        if value.get('account') and value['account']['binding']!=context.binding:
            from real_order_ledger import RealOrderLedger,TERMINAL
            rows=RealOrderLedger().requests(value['account']['binding'])
            if any(r['state'] not in TERMINAL for r in rows):raise ValueError('LIVE_ACCOUNT_HAS_PENDING_ORDERS')
            contracts={r['contract'] for r in rows}
            if any(sum(sum(f['quantity'] for f in r['fills'].values())*(1 if r['instruction']=='BUY_TO_OPEN' else -1)
                for r in rows if r['contract']==c)>0 for c in contracts):raise ValueError('LIVE_ACCOUNT_HAS_POSITIONS')
            plan=RealAutomaticQueue().read(value['account']['binding'])
            if plan and any(r['state'] in ('ARMED','SUBMITTING','ORDER_SENT','REQUIRES_REVIEW') for r in plan['rows']):
                raise ValueError('LIVE_ACCOUNT_HAS_ACTIVE_QUEUE')
            value['protocol']=None
        value['account']=dict(binding=context.binding,account_number=context.account_number,account_hash=context.account_hash)
        value['execution_authorized']=True
        value['selected_at']=datetime.now(timezone.utc).isoformat()
        store.save(value)


def verified_preview_wire(binding):
    try:
        store=RealControlStore()
        with store.locked():proof=control_document(store).get('protocol') or {}
        if (proof.get('binding')==binding and proof.get('source')=='SCHWAB_PREVIEW_ENDPOINT' and
            proof.get('wire') in ('PREVIEW_ORDER_STRATEGY_V1','ORDER_REQUEST_V1')):return proof['wire']
    except Exception:pass
    return 'PREVIEW_ORDER_STRATEGY_V1'


def next_official_session(now,database=None):
    from market_store import DEFAULT_MARKET_DATABASE
    from zoneinfo import ZoneInfo
    database=Path(database or DEFAULT_MARKET_DATABASE)
    today=aware(now).astimezone(ZoneInfo('America/New_York')).date().isoformat()
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.execute('PRAGMA query_only=ON')
        rows=db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? ORDER BY session_date LIMIT 10',(today,)).fetchall()
    for start,end in rows:
        start,end=aware(datetime.fromisoformat(start)),aware(datetime.fromisoformat(end))
        if start<end and end>aware(now):return start,end
    raise ValueError('OFFICIAL_SESSION_UNAVAILABLE')


class RealRuntimeProxy:
    """Dashboard owns no worker, OAuth client or broker gateway."""
    def __init__(self,binding,*,queue=None,status_factory=RealHostStatusStore,control_factory=RealControlStore,
                 clock=lambda:datetime.now(timezone.utc),session_provider=None):
        self.binding=binding;self.queue=queue or RealAutomaticQueue();self.status_factory=status_factory
        self.control_factory=control_factory;self.clock=clock;self.session_provider=session_provider

    def status(self):
        try:
            store=self.status_factory()
            with store.locked():status=store.load()
            age=(aware(self.clock())-aware(datetime.fromisoformat(status['checked_at']))).total_seconds()
            if status.get('binding')!=self.binding or not 0<=age<5:raise ValueError
            return status
        except Exception:return dict(ready_to_arm=False,blockers=['LIVE_HOST_NOT_CURRENT'])

    def can_arm(self):return self.status().get('ready_to_arm') is True

    def arm(self,rows,*,repeat_new_signals=False,first_entry_only=True):
        store=self.control_factory()
        with store.locked():value=control_document(store)
        if not value.get('execution_authorized') or (value.get('account') or {}).get('binding')!=self.binding:
            raise ValueError('LIVE_ACCOUNT_NOT_SELECTED')
        start,end=self.session_provider() if self.session_provider else next_official_session(self.clock())
        return self.queue.arm(self.binding,rows,session_open=start,session_close=end,execution_ready=self.can_arm,
            repeat_new_signals=repeat_new_signals,first_entry_only=first_entry_only)

    def pause(self):return self.queue.pause(self.binding)

    def resume(self,plan_id):
        store=self.control_factory()
        with store.locked():value=control_document(store)
        if not value.get('execution_authorized') or (value.get('account') or {}).get('binding')!=self.binding:
            raise ValueError('LIVE_ACCOUNT_NOT_SELECTED')
        return self.queue.resume(self.binding,plan_id,execution_ready=self.can_arm)

    def remove_waiting(self,plan_id):return self.queue.remove_waiting(self.binding,plan_id)

    def remove(self,plan_id,row_id):return self.queue.remove(self.binding,plan_id,row_id)

    def close_manually(self,buy_id):
        from real_live_commands import request_close
        return request_close(self.binding,buy_id)

    def positions(self):
        from real_order_ledger import RealOrderLedger
        rows=RealOrderLedger().requests(self.binding);positions=[]
        for buy in rows:
            if buy['instruction']!='BUY_TO_OPEN' or not buy['fills']:continue
            bought=sum(f['quantity'] for f in buy['fills'].values())
            sells=[r for r in rows if r.get('parent_id')==buy['id']]
            sold=sum(f['quantity'] for r in sells for f in r['fills'].values())
            if bought>sold:
                positions.append(dict(id=buy['id'],contract=buy['contract'],quantity=bought-sold,
                    target=buy.get('exit_plan',{}).get('target','MANUAL'),state=buy['state'],
                    external_close_pending=bool(buy.get('external_close_hold')),
                    exit_trigger=buy.get('exit_trigger'),pending_close=any(r['state'] not in ('FILLED','CANCELED','REJECTED','EXPIRED') for r in sells)))
        return positions

    def trade_history(self):
        from real_order_ledger import RealOrderLedger
        from schwab_contracts import decimal
        rows=RealOrderLedger().requests(self.binding);result=[]
        for buy in rows:
            if buy['instruction']!='BUY_TO_OPEN' or not buy['fills']:continue
            bought=sum(f['quantity'] for f in buy['fills'].values())
            closes=[r for r in rows if r.get('parent_id')==buy['id']]
            sold=sum(f['quantity'] for r in closes for f in r['fills'].values())
            average=sum(decimal(f['price'])*f['quantity'] for f in buy['fills'].values())/bought
            result.append(dict(contract=buy['contract'],bought=bought,sold=sold,entry_average=str(average),
                entered_at=min(f['time'] for f in buy['fills'].values()),
                state='CLOSED' if sold==bought else 'OPEN',
                manual_close=any(r.get('origin') in ('USER_CONFIRMED_MANUAL_CLOSE','BROKER_DETECTED_MANUAL_CLOSE') for r in closes)))
        return result[-20:]
