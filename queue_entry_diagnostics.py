"""Explain selection using the same entry predicate; never authorizes a trade."""
from datetime import datetime
from option_contract_selection import entry_candidates, entry_market_candidates, select_entry_expiration, require_entry_premium
from price_ranges import optimal_option_premium
from schwab_contracts import decimal


def catalog_check(market, symbol, side, now):
    expiry=select_entry_expiration(market.expirations,now)
    quotes=[c.snapshot for c in market.chain.contracts]
    parameters=dict(underlying_price=market.chain.underlying_price,
        underlying_stamp=market.chain.underlying_timestamp,side=side,as_of=now)
    itm=[q for q in entry_market_candidates(quotes,strike_inventory=market.strike_inventory,**parameters) if q.expiration==expiry]
    eligible=entry_candidates(quotes,symbol=symbol,listed_expirations=market.expirations,strike_inventory=market.strike_inventory,**parameters)
    low,high=optimal_option_premium(symbol)
    rejected={}
    for q in itm:
        try:require_entry_premium(q.bid,q.ask,(low,high))
        except ValueError as error:
            code=str(error);rejected[code]=rejected.get(code,0)+1
    nearest=itm[0] if itm else None
    return dict(expiry=expiry.isoformat(),side=side,spot=market.chain.underlying_price,
        itm=len(itm),eligible=len(eligible),low=str(low),high=str(high),rejected=rejected,
        nearest_ask=str(decimal(nearest.ask)) if nearest else None,
        nearest_bid=str(decimal(nearest.bid)) if nearest else None,
        nearest_spread=str(decimal(nearest.ask)-decimal(nearest.bid)) if nearest else None,
        nearest_quote_at=nearest.quote_timestamp.isoformat() if nearest else None)


def check_caption(row):
    details=row['details'];local=datetime.fromisoformat(row['at']).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York'))
    text=f"Revisión Schwab {local:%H:%M:%S} ET · {details['side']} · Vence {details['expiry']} · "
    text+=f"ITM/OTM≤5 con cotización apta: {details['itm']} · En rango y spread: {details['eligible']}."
    if details.get('nearest_ask') is not None:
        text+=f" Contrato apto más cercano: Bid ${details['nearest_bid']} / Ask ${details['nearest_ask']} · spread ${details['nearest_spread']}."
    text+=' Es la última revisión guardada; la compra siempre exige cotizaciones actuales.'
    return text
