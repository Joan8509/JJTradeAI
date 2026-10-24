"""Read-only owner check: fixed metadata only, no network, orders or messages."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from schwab_connection import EncryptedSchwabStore
from schwab_simulation import policy_from_dict


def inspect(profile):
    payload=profile.get('manual_simulation_policy')
    complete=False
    if isinstance(payload,dict):
        try:policy_from_dict(payload).require_complete();complete=True
        except (ValueError,TypeError,KeyError,RuntimeError,AttributeError):pass
    return dict(checked_utc=datetime.now(timezone.utc).isoformat(),
        api_market_data_only=profile.get('api_product')=='MARKET_DATA_ONLY',
        real_orders_enabled=profile.get('real_orders_enabled') is not False,
        telegram_manual_opt_in=profile.get('telegram_manual_enabled') is True,
        manual_practice_opt_in=profile.get('manual_practice_enabled') is True,
        manual_practice_profile_compatible=(profile.get('manual_practice_enabled') is True
            and profile.get('real_orders_enabled') is False and profile.get('api_product')=='MARKET_DATA_ONLY'
            and payload is None),
        simulation_policy_present=isinstance(payload,dict),simulation_policy_complete=complete,
        verified_fees_present=profile.get('fee_per_contract') is not None,
        verified_increment_count=len(profile.get('verified_contract_price_increments') or {}),
        tokens_present=isinstance(profile.get('tokens'),dict),
        network_used=False,messages_sent=0,orders_sent=0)


def main():
    try:result=inspect(EncryptedSchwabStore().load())
    except Exception:result={'status':'OWNER_PRIVATE_CONFIG_UNAVAILABLE','network_used':False,'messages_sent':0,'orders_sent':0}
    print(json.dumps(result))
    return 0 if 'status' not in result else 2


if __name__=='__main__':raise SystemExit(main())
