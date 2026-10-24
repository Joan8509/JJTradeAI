"""Owner-only real market-data audit. No accounts, orders, Telegram or raw logs."""
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from schwab_connection import EncryptedSchwabStore,OAuthConfig,SchwabOAuth,SchwabReadOnlyClient,SchwabError
from manual_trade_service import decode_manual_chain
from watchlist_config import load_watchlist
from option_contract_selection import select_entry_expiration


def chain_summary(payload,symbol,side,now,*,increments=None):
    market=decode_manual_chain(payload,symbol,side,now,verified_increments=increments)
    chain=market.chain;mapping=payload.get('callExpDateMap' if side=='CALL' else 'putExpDateMap',{})
    raw=[item for strikes in mapping.values() for group in strikes.values() for item in group]
    quotes=[c.snapshot for c in chain.contracts]
    stamps=[q.quote_timestamp for q in quotes if q.quote_timestamp]
    nearest=select_entry_expiration(market.expirations,now) if market.expirations else None
    nearest_quotes=[q for q in quotes if q.expiration==nearest]
    # These are structural observations. Sunday quote ages never imply eligibility.
    fresh=[q for q in nearest_quotes if 0<=(now-q.quote_timestamp).total_seconds()<=30]
    return dict(status='CHAIN_RECEIVED',symbol=symbol,side=side,is_delayed=payload.get('isDelayed'),
        listed_expirations=len(market.expirations),nearest_expiration=nearest.isoformat() if nearest else None,
        raw_contracts=len(raw),normalized_contracts=len(quotes),rejected_contracts=chain.rejected_contracts,
        nearest_normalized=len(nearest_quotes),nearest_with_spread_le_005=sum(Decimal(str(q.ask))-Decimal(str(q.bid))<=Decimal('.05') for q in nearest_quotes),
        nearest_fresh_30s=len(fresh),latest_option_timestamp=max(stamps).isoformat() if stamps else None,
        latest_option_age_seconds=round((now-max(stamps)).total_seconds(),3) if stamps else None,
        underlying_quote_timestamp=chain.underlying_timestamp.isoformat(),
        underlying_quote_age_seconds=round((now-chain.underlying_timestamp).total_seconds(),3),
        verified_increments=sum(c.price_increment is not None for c in chain.contracts),
        chain_status=payload.get('status'),raw_increment_fields=sorted({k for item in raw for k in item
            if any(part in k.lower() for part in ('increment','tick','penny'))}))


def quote_summary(payload,symbol,now):
    row=payload.get(symbol)
    if not isinstance(row,dict):return dict(symbol=symbol,status='QUOTE_MISSING')
    quote=row.get('quote') or {};stamp=quote.get('quoteTime')
    trade=quote.get('tradeTime')
    def parsed(value):
        return datetime.fromtimestamp(value/1000,timezone.utc) if type(value) in (int,float) and value>0 else None
    qtime=parsed(stamp);ttime=parsed(trade)
    return dict(symbol=symbol,status='QUOTE_RECEIVED',realtime=row.get('realtime'),
        quote_timestamp=qtime.isoformat() if qtime else None,
        quote_age_seconds=round((now-qtime).total_seconds(),3) if qtime else None,
        trade_timestamp=ttime.isoformat() if ttime else None,
        trade_age_seconds=round((now-ttime).total_seconds(),3) if ttime else None,
        bid_ask_fields_present=all(quote.get(k) is not None for k in ('bidPrice','askPrice','bidSize','askSize')),
        last_price_present=quote.get('lastPrice') is not None)


def main():
    stage=ROOT/json.loads((ROOT/'exports/backups/schwab_readiness_current.json').read_text())['directory']
    stage.mkdir(parents=True,exist_ok=True)
    result=dict(started_utc=datetime.now(timezone.utc).isoformat(),real_orders_enabled=False,
        accounts_requested=0,orders_sent=0,messages_sent=0,chains=[],quotes=[])
    store=EncryptedSchwabStore();profile=store.load()
    if profile.get('real_orders_enabled') is not False or profile.get('api_product')!='MARKET_DATA_ONLY':
        raise ValueError('READ_ONLY_PROFILE_REQUIRED')
    before=dict(profile.get('tokens') or {})
    result['access_expired_before']=bool(before.get('expires_at') and datetime.fromisoformat(before['expires_at'])<=datetime.now(timezone.utc))
    oauth=SchwabOAuth(OAuthConfig(**profile['oauth_config']),store);client=SchwabReadOnlyClient(oauth)
    symbols=load_watchlist(ROOT/'config/watchlist.json')['symbols']
    try:
        quotes=client.quotes(list(symbols),datetime.now(timezone.utc));now=datetime.now(timezone.utc)
        result['quotes']=[quote_summary(quotes,s,now) for s in symbols]
        print(json.dumps(dict(step='QUOTES',received=sum(q['status']=='QUOTE_RECEIVED' for q in result['quotes']),requested=len(symbols))),flush=True)
        for symbol in symbols:
            for side in ('CALL','PUT'):
                started=time.monotonic()
                try:
                    payload=client.full_chain(symbol,side,datetime.now(timezone.utc))
                    item=chain_summary(payload,symbol,side,datetime.now(timezone.utc),
                        increments=profile.get('verified_contract_price_increments'))
                except SchwabError as error:
                    if error.code in ('AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED','TRANSPORT_FAILURE'):raise
                    item=dict(symbol=symbol,side=side,status=error.code,http_status=error.http_status)
                except Exception:item=dict(symbol=symbol,side=side,status='CHAIN_UNAVAILABLE_OR_INVALID')
                item['elapsed_seconds']=round(time.monotonic()-started,3)
                result['chains'].append(item)
                (stage/'market_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                print(json.dumps({k:item[k] for k in ('symbol','side','status','normalized_contracts','nearest_expiration') if k in item}),flush=True)
    except SchwabError as error:
        result.update(blocking_error=error.code,retry_after_seconds=error.retry_after_seconds)
    after=store.load().get('tokens') or {}
    result.update(completed_utc=datetime.now(timezone.utc).isoformat(),
        token_expiry_advanced=bool(before.get('expires_at') and after.get('expires_at') and after['expires_at']>before['expires_at']),
        refresh_token_rotated=bool(before.get('refresh_token') and after.get('refresh_token')!=before.get('refresh_token')),
        profile_real_orders_still_disabled=store.load().get('real_orders_enabled') is False)
    (stage/'market_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    summary=dict(chains_requested=len(symbols)*2,chains_checked=len(result['chains']),
        statuses=dict(Counter(item['status'] for item in result['chains'])),
        normalized_contracts=sum(i.get('normalized_contracts',0) for i in result['chains']),
        nearest_fresh_30s=sum(i.get('nearest_fresh_30s',0) for i in result['chains']),
        blocking_error=result.get('blocking_error'),orders_sent=0,messages_sent=0)
    print(json.dumps(summary));return 0 if not result.get('blocking_error') else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:print(json.dumps(dict(status='AUDIT_NOT_COMPLETED',details_hidden=True)));raise SystemExit(2)
