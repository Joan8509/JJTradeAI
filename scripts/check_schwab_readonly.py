"""Explicit owner-console account selection and read-only connection receipt.

Not run by collector/radar. Prints only allowlisted metadata, never account
numbers, hashes, positions, order details, URLs, tokens or raw exceptions.
"""
from datetime import datetime, timedelta, timezone
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schwab_connection import EncryptedSchwabStore, OAuthConfig, SchwabOAuth, SchwabReadOnlyClient


def inspect_account(client, profile, now):
    accounts = client.accounts(now)
    result = {'account_count':len(accounts),'messages_sent':0,'orders_sent':0,
              'real_orders_enabled':False,'options_permissions_verified':False}
    selected = profile.get('selected_account_hash')
    if not selected:
        return dict(result,status='ACCOUNT_SELECTION_REQUIRED')
    linked = [row for row in accounts if row.get('hashValue') == selected]
    if len(linked)!=1:
        return dict(result,status='SELECTED_ACCOUNT_NOT_UNIQUELY_LINKED')
    account = client.positions(selected,now).get('securitiesAccount',{})
    if str(account.get('accountNumber')) != str(linked[0].get('accountNumber')):
        return dict(result,status='ACCOUNT_IDENTITY_MISMATCH')
    orders = client.orders(selected,now-timedelta(days=1),now,now)
    return dict(result,status='AUTHENTICATED_READ_ONLY',positions_readable=True,
                position_count=len(account.get('positions',[])),orders_readable=True,
                observed_order_count=len(orders),account_identity_matches=True)


def main():
    store=EncryptedSchwabStore()
    profile=store.load()
    oauth=SchwabOAuth(OAuthConfig(**profile['oauth_config']),store)
    client=SchwabReadOnlyClient(oauth)
    now=datetime.now(timezone.utc)
    if '--select-account' in sys.argv:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError('Owner console required')
        accounts=client.accounts(now)
        for index,row in enumerate(accounts,1):
            # Masked identifiers only in the actual interactive private console.
            print(str(index)+': cuenta terminada en '+str(row['accountNumber'])[-4:])
        selection=getpass.getpass('Número de selección (oculto): ')
        if not selection.isdecimal() or not 1<=int(selection)<=len(accounts):
            raise ValueError('Explicit valid selection required')
        alias=input('Alias privado para esta cuenta: ').strip()
        if not alias:
            raise ValueError('Alias required')
        with store.locked():
            profile=store.load()  # Keep any refreshed tokens, never overwrite with stale copy.
            profile.update(selected_account_hash=accounts[int(selection)-1]['hashValue'],account_alias=alias,
                           real_orders_enabled=False)
            store.save(profile)
    result=inspect_account(client,profile,datetime.now(timezone.utc))
    result['checked_utc']=datetime.now(timezone.utc).isoformat()
    from vps_private_runtime import write_receipt
    write_receipt('schwab_readonly.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status':'SCHWAB_READONLY_UNAVAILABLE','error_type':type(error).__name__,
                          'orders_sent':0,'real_orders_enabled':False}))
        raise SystemExit(2)
