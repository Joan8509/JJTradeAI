"""Separate loopback account OAuth receiver. No startup at import."""
from pathlib import Path
import argparse,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from real_account_readonly import AccountReadOnlyStore,ACCOUNT_CALLBACK,PRODUCT
from schwab_connection import OAuthConfig,SchwabOAuth
from scripts.schwab_oauth_receiver import handler_for,QuietServer
BACKEND_PORT=8187
COOKIE_NAME='jj_schwab_accounts_state'


def build_oauth(store):
    value=store.load()
    config=OAuthConfig(**value['oauth_config'])
    if value.get('real_orders_enabled') is not False or value.get('api_product')!=PRODUCT or config.callback_url!=ACCOUNT_CALLBACK:
        raise ValueError('ACCOUNT_READ_ONLY_PROFILE_REQUIRED')
    return SchwabOAuth(config,store)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--health-only',action='store_true');args=parser.parse_args()
    oauth=None if args.health_only else build_oauth(AccountReadOnlyStore())
    # health-only still uses the account callback host, not the market-data port.
    server=QuietServer(('127.0.0.1',BACKEND_PORT),handler_for(oauth,cookie_name=COOKIE_NAME,health_callback=ACCOUNT_CALLBACK))
    server.serve_forever(poll_interval=.5)


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit(2)
