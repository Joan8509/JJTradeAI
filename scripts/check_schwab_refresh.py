"""Explicit owner OAuth renewal and real GET; never prints or logs token material."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from schwab_connection import EncryptedSchwabStore,OAuthConfig,SchwabOAuth,SchwabReadOnlyClient,SchwabError


def main():
    store=EncryptedSchwabStore();profile=store.load()
    if profile.get('real_orders_enabled') is not False or profile.get('api_product')!='MARKET_DATA_ONLY':
        raise ValueError('READ_ONLY_PROFILE_REQUIRED')
    before=profile.get('tokens') or {}
    oauth=SchwabOAuth(OAuthConfig(**profile['oauth_config']),store)
    oauth.refresh(datetime.now(timezone.utc))
    # Independent request reads the persisted refreshed credentials, not a logged token.
    fresh=store.load();client=SchwabReadOnlyClient(SchwabOAuth(OAuthConfig(**fresh['oauth_config']),store))
    quotes=client.quotes(['AAPL','SPY','QQQ'],datetime.now(timezone.utc))
    after=fresh.get('tokens') or {}
    result=dict(checked_utc=datetime.now(timezone.utc).isoformat(),oauth_refresh_verified=True,
        refreshed_access_verified_by_get=all(s in quotes for s in ('AAPL','SPY','QQQ')),
        expiry_advanced=bool(before.get('expires_at') and after.get('expires_at','')>before['expires_at']),
        authorization_age_preserved=before.get('authorization_started_at')==after.get('authorization_started_at'),
        non_token_profile_preserved={k:v for k,v in profile.items() if k!='tokens'}=={k:v for k,v in fresh.items() if k!='tokens'},
        real_orders_enabled=fresh.get('real_orders_enabled') is not False,orders_sent=0,messages_sent=0)
    stage=ROOT/json.loads((ROOT/'exports/backups/schwab_readiness_current.json').read_text())['directory']
    (stage/'oauth_refresh_check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result));return 0 if result['refreshed_access_verified_by_get'] else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        code=getattr(error,'code',None)
        print(json.dumps(dict(status=code if code in ('AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED','TRANSPORT_FAILURE') else 'REFRESH_CHECK_UNAVAILABLE',details_hidden=True)))
        raise SystemExit(2)
