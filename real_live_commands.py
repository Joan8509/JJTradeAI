"""Durable, account-bound manual-close commands for the supervised executor."""
from datetime import datetime,timezone
import secrets

from real_live_storage import RealEncryptedStore as EncryptedSchwabStore
from real_live_control import ROOT
from real_order_ledger import RealOrderLedger


class RealCommandStore(EncryptedSchwabStore):
    def __init__(self):self.path=ROOT/'exports/private_runtime/real_commands.dpapi'


def document(store):
    value=store.load() if store.path.exists() else dict(purpose='REAL_MANUAL_COMMANDS_V1',commands=[])
    if value.get('purpose')!='REAL_MANUAL_COMMANDS_V1':raise ValueError('LIVE_COMMAND_STORE_INVALID')
    return value


def request_close(binding,buy_id,*,store_factory=RealCommandStore,ledger=None):
    ledger=ledger or RealOrderLedger()
    row=next((r for r in ledger.requests(binding) if r['id']==buy_id and r['instruction']=='BUY_TO_OPEN'),None)
    if not row or not row.get('exit_plan') or not row['fills']:raise ValueError('LIVE_OWNED_POSITION_REQUIRED')
    store=store_factory()
    with store.locked():
        value=document(store)
        existing=next((c for c in value['commands'] if c['binding']==binding and c['buy_id']==buy_id and
            c['state'] in ('PENDING','CLAIMED')),None)
        if existing:return existing['id']
        item=dict(id=secrets.token_hex(16),binding=binding,buy_id=buy_id,state='PENDING',
            requested_at=datetime.now(timezone.utc).isoformat())
        value['commands'].append(item);store.save(value);return item['id']


class CommandExecution:
    """Manual close latches the journal plan; it is not a blind order retry."""
    def __init__(self,execution,*,store_factory=RealCommandStore):
        self.execution=execution;self.binding=execution.binding;self.store_factory=store_factory

    def __getattr__(self,name):return getattr(self.execution,name)

    def _commands(self):
        store=self.store_factory()
        with store.locked():
            value=document(store)
            pending=[dict(c) for c in value['commands'] if c['binding']==self.binding and c['state'] in ('PENDING','CLAIMED')]
            if pending:
                for c in value['commands']:
                    if any(p['id']==c['id'] for p in pending):c['state']='CLAIMED'
                store.save(value)
        for command in pending:
            state='ACKNOWLEDGED'
            try:self.execution.close_manually(command['buy_id'])
            except Exception:state='REQUIRES_REVIEW'
            with store.locked():
                value=document(store)
                next(c for c in value['commands'] if c['id']==command['id'])['state']=state
                store.save(value)
    def poll(self):
        self._commands()
        return self.execution.poll()

    def monitor_positions(self):
        self._commands()
        return self.execution.monitor_positions()
