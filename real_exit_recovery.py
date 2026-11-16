"""Proof for one bounded retry of a definitively rejected, unfilled close."""
from datetime import datetime,timedelta
from schwab_connection import aware
from real_order_ledger import RealOrderBlocked


def unresolved_rejections(parent,children):
    resolved=set(parent.get('resolved_exit_rejections',()))
    return [r for r in children if r['state']=='REJECTED' and r['id'] not in resolved]


def validate_retry_proof(proof,*,binding,parent,rejected,quantity,now):
    invalid='LIVE_EXIT_RETRY_EVIDENCE_REQUIRED'
    if (not isinstance(proof,dict) or proof.get('source')!='SCHWAB_POSITION_AND_ORDERS'
            or proof.get('binding')!=binding or proof.get('parent_id')!=parent['id']
            or proof.get('contract')!=parent['contract'] or proof.get('quantity')!=quantity
            or proof.get('rejected_ids')!=sorted(r['id'] for r in rejected)
            or not rejected or parent.get('exit_recovery_used')
            or any(r.get('fills') or not r.get('broker_id') for r in rejected)):
        raise RealOrderBlocked(invalid)
    try:
        observed=aware(datetime.fromisoformat(proof['observed_at']))
        expires=aware(datetime.fromisoformat(proof['valid_until']))
        if (not observed<=aware(now)<expires or expires>observed+timedelta(seconds=5)
                or any(observed<aware(datetime.fromisoformat(r['updated_at'])) for r in rejected)):
            raise ValueError
    except (KeyError,TypeError,ValueError):raise RealOrderBlocked(invalid) from None
