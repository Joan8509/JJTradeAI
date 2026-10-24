"""Market-only explanations; observed rows never authorize or select a purchase."""
from datetime import timedelta

from option_contract_selection import MAX_ENTRY_SPREAD, MAX_OTM_STRIKES, otm_strike_positions
from schwab_contracts import decimal


def contract_diagnostics(market, *, symbol, side, expiration, as_of,
                         underlying_price, underlying_stamp, optimal_range, eligible):
    low, high = map(decimal, optimal_range)
    underlying = decimal(underlying_price)
    underlying_current = (underlying_stamp is not None and
        timedelta(0) <= as_of - underlying_stamp <= timedelta(seconds=30))
    approved = {c.snapshot.symbol for c in eligible}
    quotes = [c.snapshot for c in market.chain.contracts
        if c.snapshot.underlying_symbol == symbol and c.snapshot.option_type == side
        and c.snapshot.expiration == expiration]
    rows = []
    strikes=[strike for day,strike in market.strike_inventory if day==expiration]
    positions=otm_strike_positions(underlying,side,strikes)
    for q in quotes:
        bid, ask, strike = map(decimal, (q.bid, q.ask, q.strike))
        itm = strike < underlying if side == 'CALL' else strike > underlying
        age = None if q.quote_timestamp is None else (as_of-q.quote_timestamp).total_seconds()
        fresh = age is not None and 0 <= age <= 30
        in_range = low <= ask <= high
        spread = ask-bid
        spread_ok = 0 <= spread <= MAX_ENTRY_SPREAD
        market_ok = bid > 0 and ask >= bid and min(q.bid_size, q.ask_size) > 0
        rank=positions.get(strike)
        money_ok=itm or (rank is not None and rank<=MAX_OTM_STRIKES)
        reasons = []
        for passed, code in ((money_ok, 'OUTSIDE_ALLOWED_MONEYNESS'), (in_range, 'ASK_OUTSIDE_RANGE'),
                (spread_ok, 'SPREAD_EXCEEDS_MAX'), (fresh, 'QUOTE_NOT_CURRENT'),
                (underlying_current, 'UNDERLYING_NOT_CURRENT'),
                (market_ok, 'INVALID_OPTION_MARKET'), (q.feed == 'opra', 'UNVERIFIED_FEED')):
            if not passed:
                reasons.append(code)
        eligible_now = q.symbol in approved
        if not eligible_now and not reasons:
            reasons.append('NOT_SELECTED_BY_CANONICAL_CHECKS')
        rows.append(dict(symbol=q.symbol, strike=str(strike), bid=str(bid), ask=str(ask),
            spread=str(spread), itm=itm, otm_position=rank, moneyness_allowed=money_ok, in_range=in_range, spread_ok=spread_ok,
            fresh=fresh, eligible=eligible_now, reasons=reasons,
            quote_timestamp=q.quote_timestamp.isoformat() if q.quote_timestamp else None,
            age_seconds=age,bid_size=q.bid_size,ask_size=q.ask_size))
    counts = dict(observed=len(rows), eligible=len(approved),
        itm=sum(r['itm'] for r in rows), in_range=sum(r['in_range'] for r in rows),
        spread_ok=sum(r['spread_ok'] for r in rows), fresh=sum(r['fresh'] for r in rows))
    # Show nearby strikes on both sides, so a cheap OTM is never described as ITM.
    rows.sort(key=lambda r: (abs(decimal(r['strike'])-underlying), decimal(r['strike'])))
    return dict(read_only=True, expiration=expiration.isoformat(), underlying_price=str(underlying),
        premium_low=str(low), premium_high=str(high), max_spread=str(MAX_ENTRY_SPREAD),
        checked_utc=as_of.isoformat(), counts=counts, observed=rows[:4],
        nearest_itm=next((r for r in rows if r['itm']),None),
        itm_contracts=[r for r in rows if r['itm']][:200],contracts=rows)
