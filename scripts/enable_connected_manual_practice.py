"""Explicit local rehearsal opt-in; DPAPI only, never real orders or messages.

Run under the existing Administrator identity after the source tests pass.
No credentials/values are accepted on argv or printed. Old encrypted vault is
preserved beside it under the same private ACL; rollback must preserve new tokens.
"""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def enable(store, *, now):
    with store.locked():
        profile=store.load()
        if (profile.get('real_orders_enabled') is not False or profile.get('api_product')!='MARKET_DATA_ONLY'
                or profile.get('manual_simulation_policy') is not None):
            raise ValueError('INCOMPATIBLE_PRIVATE_PROFILE')
        from schwab_simulation import ManualPracticePolicy
        ManualPracticePolicy().require_complete()
        old={k:profile.get(k) for k in ('manual_practice_enabled','telegram_manual_enabled')}
        if old==dict(manual_practice_enabled=True,telegram_manual_enabled=True):
            return dict(status='ALREADY_CONFIGURED',real_orders_enabled=False)
        backup=store.path.with_name('schwab.before_manual_practice.'+now.strftime('%Y%m%dT%H%M%SZ')+'.dpapi')
        with backup.open('xb') as output:output.write(store.path.read_bytes())
        updated=dict(profile,manual_practice_enabled=True,telegram_manual_enabled=True)
        store.save(updated)
        after=store.load()
        if any(after.get(k)!=v for k,v in profile.items() if k not in old):
            raise RuntimeError('UNEXPECTED_PRIVATE_PROFILE_CHANGE')
        return dict(status='CONFIGURED_LOCAL_MANUAL_PRACTICE',real_orders_enabled=False,
            costs_verified=False,new_budgets_added=False,supervisor_reload_required=True)


if __name__=='__main__':
    from schwab_connection import EncryptedSchwabStore
    try:print(json.dumps(enable(EncryptedSchwabStore(),now=datetime.now(timezone.utc))))
    except Exception:
        print(json.dumps(dict(status='CONFIGURATION_BLOCKED',details_hidden=True)));raise SystemExit(2)
