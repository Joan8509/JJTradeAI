"""Owner-only status audit. No broker requests, order changes or account IDs."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import json,sys
import shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from real_live_control import RealControlStore,RealHostStatusStore,control_document,next_official_session,ROOT
from real_order_ledger import RealOrderLedger
from real_automatic_queue import RealAutomaticQueue


def main():
    result=dict(checked_at=datetime.now(timezone.utc).isoformat(),audit_only=True,broker_requests_sent=0)
    result['free_disk_mb']=int(shutil.disk_usage(ROOT).free/1024**2)
    try:
        start,end=next_official_session(datetime.now(timezone.utc))
        result.update(next_session_available=True,next_session_open=start.isoformat(),next_session_close=end.isoformat())
    except Exception:result['next_session_available']=False
    try:
        control=RealControlStore()
        with control.locked():config=control_document(control)
        selected=config.get('account') or {};binding=selected.get('binding')
        if not binding:
            result['state']='LIVE_EXPLICIT_ACCOUNT_SELECTION_REQUIRED';return result
        store=RealHostStatusStore()
        with store.locked():status=store.load()
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(status['checked_at'])).total_seconds()
        current=0<=age<5 and status.get('binding')==binding
        rows=RealOrderLedger().requests(binding);queue=RealAutomaticQueue().read(binding)
        result.update(state='LIVE_HOST_CURRENT' if current else 'LIVE_HOST_NOT_CURRENT',host_current=current,
            host_pid=status.get('pid'),ready_to_arm=bool(current and status.get('ready_to_arm')),
            account_current=status.get('account_current'),protocol_verified=status.get('protocol_verified'),
            deployment_hold=config.get('deployment_hold',True),worker=status.get('worker'),blockers=status.get('blockers'),
            request_count=len(rows),request_states=dict(Counter(r['state'] for r in rows)),
            owned_contracts=sum(sum(f['quantity'] for f in r['fills'].values())*(1 if r['instruction']=='BUY_TO_OPEN' else -1) for r in rows),
            queue_row_count=len(queue['rows']) if queue else 0,
            queue_states=dict(Counter(r['state'] for r in queue['rows'])) if queue else {},
            queue_armed=bool(queue and not queue['paused'] and any(r['state']=='ARMED' for r in queue['rows'])))
    except Exception:result['state']='LIVE_STATUS_UNAVAILABLE'
    return result


if __name__=='__main__':print(json.dumps(main(),ensure_ascii=True))
