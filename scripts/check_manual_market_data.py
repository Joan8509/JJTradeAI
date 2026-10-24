"""Owner-only read-only option preview check. Fixed metadata, no private output."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from manual_trade_service import owner_market_data,ManualDataError


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol',default='AAPL')
    parser.add_argument('--side',choices=('CALL','PUT'),default='CALL')
    args=parser.parse_args()
    try:
        service=owner_market_data()
        market=service.get_chain(args.symbol,args.side,datetime.now(timezone.utc))
        now=datetime.now(timezone.utc)
        quotes=[c.snapshot.quote_timestamp for c in market.chain.contracts if c.snapshot.quote_timestamp]
        result={'status':'READ_ONLY_CHAIN_RECEIVED','checked_utc':now.isoformat(),
            'listed_expirations':len(market.expirations),'normalized_contracts':len(market.chain.contracts),
            'rejected_contracts':market.chain.rejected_contracts,
            'latest_option_age_seconds':round((now-max(quotes)).total_seconds(),3) if quotes else None,
            'verified_price_increments':sum(c.price_increment is not None for c in market.chain.contracts),
            'entry_costs_configured':service.fee_per_contract is not None,
            'accounts_requested':0,'orders_sent':0,'messages_sent':0,'real_orders_enabled':False}
    except ManualDataError as error:
        result={'status':str(error),'orders_sent':0,'messages_sent':0,'real_orders_enabled':False}
    print(json.dumps(result))
    return 0 if result['status']=='READ_ONLY_CHAIN_RECEIVED' else 2


if __name__=='__main__':raise SystemExit(main())
