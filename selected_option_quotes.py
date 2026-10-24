"""Refresh prices from a batched Schwab quote, preserving verified identities.

No accounts or orders. Provider timestamps are retained, never stamped as fresh
merely because an HTTP response arrived. Eligibility is checked by the caller.
"""
from dataclasses import replace
from datetime import date
from schwab_contracts import decimal,milliseconds,positive_int


def refresh_selected(market,contract_symbol,payload,fetched_at):
    original=next((c for c in market.chain.contracts if c.snapshot.symbol==contract_symbol),None)
    if original is None:raise ValueError('SELECTED_QUOTE_IDENTITY_INVALID')
    original.validate_identity();q=original.snapshot
    stock=payload[market.symbol];option=payload[contract_symbol]
    if (stock.get('symbol'),stock.get('assetMainType'))!=(market.symbol,'EQUITY') or stock.get('realtime') is not True:
        raise ValueError('SELECTED_QUOTE_IDENTITY_INVALID')
    if (option.get('symbol'),option.get('assetMainType'))!=(contract_symbol,'OPTION') or option.get('realtime') is not True:
        raise ValueError('SELECTED_QUOTE_IDENTITY_INVALID')
    ref=option['reference'];quote=option['quote'];underlying=stock['quote']
    if (ref['underlying']!=market.symbol or ref['contractType']!=('C' if market.side=='CALL' else 'P')
            or decimal(ref['strikePrice'])!=decimal(q.strike)
            or date(ref['expirationYear'],ref['expirationMonth'],ref['expirationDay'])!=q.expiration
            or decimal(ref['multiplier'])!=100 or ref['deliverables']!='100 '+market.symbol
            or quote['securityStatus']!='Normal' or underlying['securityStatus']!='Normal'):
        raise ValueError('SELECTED_QUOTE_IDENTITY_INVALID')
    price=float(decimal(underlying['lastPrice']))
    if price<=0:raise ValueError('SELECTED_QUOTE_IDENTITY_INVALID')
    fresh=replace(original,snapshot=replace(q,bid=float(decimal(quote['bidPrice'])),
        ask=float(decimal(quote['askPrice'])),bid_size=positive_int(quote['bidSize']),
        ask_size=positive_int(quote['askSize']),quote_timestamp=milliseconds(quote['quoteTime'])))
    fresh.validate_identity()
    contracts=tuple(fresh if c.snapshot.symbol==contract_symbol else c for c in market.chain.contracts)
    return replace(market,chain=replace(market.chain,contracts=contracts,underlying_price=price,
        underlying_timestamp=milliseconds(underlying['quoteTime'])),fetched_at=fetched_at)
