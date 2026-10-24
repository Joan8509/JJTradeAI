"""Canonical ITM and 30-second quote checks shared by review and simulation."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import math
from zoneinfo import ZoneInfo

from price_ranges import optimal_option_premium


MAX_OTM_STRIKES = 5

MAX_ENTRY_SPREAD = Decimal('0.08')


def select_entry_expiration(listed_expirations, as_of):
    """Choose from the complete provider calendar for this company and side.

    Select before liquidity/ITM/premium filtering; no silent jump to another
    date because the selected expiration has no usable quotes. After14:00ET,
    discard today's expiration and choose the next explicitly listed date,
    including when tomorrow has no expiration. Never invent a calendar date.
    """
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('EXPIRATION_CLOCK_MUST_BE_AWARE')
    if listed_expirations is None:
        raise ValueError('EXPIRATION_CALENDAR_REQUIRED')
    try:
        dates = tuple(listed_expirations)
    except TypeError:
        raise ValueError('EXPIRATION_CALENDAR_INVALID') from None
    if any(type(day) is not date for day in dates):
        raise ValueError('EXPIRATION_CALENDAR_INVALID')
    local = as_of.astimezone(ZoneInfo('America/New_York'))
    available = sorted({day for day in dates if day >= local.date()})
    if not available:
        raise ValueError('EXPIRATION_NONE_AVAILABLE')
    selected = available[0]
    if selected == local.date() and local.time() > time(14):
        if len(available) < 2:
            raise ValueError('EXPIRATION_NONE_AFTER_CUTOFF')
        selected = available[1]
    return selected


def require_entry_premium(bid, ask, optimal_range, *, entry_limit=None):
    """Entry-only gate: exact eight-cent spread, optimal ask and rounded buy limit.

    The user selects the ask, never bid or midpoint; this is not a promise of fill.
    Always recheck the final limit; these entry rules must never veto an exit.
    """
    try:
        values = (bid, ask, *optimal_range, ask if entry_limit is None else entry_limit)
        if any(isinstance(value, bool) for value in values):
            raise ValueError
        bid, ask, low, high, limit = (Decimal(str(value)) for value in values)
        if not all(value.is_finite() for value in (bid, ask, low, high, limit)):
            raise ValueError
        if not 0 < bid <= ask or not 0 < low <= high or limit < ask:
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError('ENTRY_PREMIUM_INVALID') from None
    if ask - bid > MAX_ENTRY_SPREAD:
        raise ValueError('ENTRY_SPREAD_EXCEEDS_MAX')
    if not low <= ask <= high or not low <= limit <= high:
        raise ValueError('ENTRY_OUTSIDE_OPTIMAL_PREMIUM')


def entry_candidates(chain, *, symbol, underlying_price, underlying_stamp, side, as_of,
                     listed_expirations=None, strike_inventory=()):
    """Preliminary candidates shared by future manual/automatic proposal views.

    A missing range raises a blocking reason. Final tick, limits, signal and risk
    must still be verified by the execution engine immediately before a claim.
    """
    selected_expiration = select_entry_expiration(listed_expirations, as_of)
    optimal_range = optimal_option_premium(symbol)
    result = []
    selected_chain=[q for q in chain if q.underlying_symbol==symbol and q.expiration==selected_expiration]
    for quote in entry_market_candidates(selected_chain, strike_inventory=strike_inventory, underlying_price=underlying_price,
            underlying_stamp=underlying_stamp, side=side, as_of=as_of):
        if quote.underlying_symbol != symbol or quote.expiration != selected_expiration:
            continue
        try:
            require_entry_premium(quote.bid, quote.ask, optimal_range)
        except ValueError:
            continue
        result.append(quote)
    return result


def otm_strike_positions(spot, side, listed_strikes):
    """Count distinct listed strikes before liquidity, price or freshness filters."""
    try:
        spot=Decimal(str(spot))
        values={Decimal(str(v)) for v in listed_strikes}
        if side not in ('CALL','PUT') or not spot.is_finite() or spot<=0:
            return {}
        if any(not v.is_finite() or v<=0 for v in values):return {}
        otm=sorted((v for v in values if v>spot),reverse=False) if side=='CALL' else sorted((v for v in values if v<spot),reverse=True)
        return {strike:i for i,strike in enumerate(otm,1)}
    except (TypeError,ValueError,InvalidOperation):return {}


def otm_strike_position(strike, spot, side, listed_strikes):
    return otm_strike_positions(spot,side,listed_strikes).get(Decimal(str(strike)))


def moneyness_allowed(quote, spot, listed_strikes=()):
    if quote.option_type not in ('CALL','PUT'):return False
    strike,spot=Decimal(str(quote.strike)),Decimal(str(spot))
    if not strike.is_finite() or not spot.is_finite() or min(strike,spot)<=0:return False
    if (quote.option_type=='CALL' and strike<spot) or (quote.option_type=='PUT' and strike>spot):return True
    rank=otm_strike_position(strike,spot,quote.option_type,listed_strikes)
    return rank is not None and 1<=rank<=MAX_OTM_STRIKES


def entry_market_candidates(chain, *, underlying_price, underlying_stamp, side, as_of, strike_inventory=()):
    """ITM plus first five OTM from the provider inventory, with current quotes."""
    current=_current_candidates(chain,underlying_price=underlying_price,
        underlying_stamp=underlying_stamp,side=side,as_of=as_of)
    ladders={};positions={};result=[];spot=Decimal(str(underlying_price))
    for expiry,strike in strike_inventory:ladders.setdefault(expiry,[]).append(strike)
    for q in current:
        strike=Decimal(str(q.strike))
        if (side=='CALL' and strike<spot) or (side=='PUT' and strike>spot):
            result.append(q);continue
        if q.expiration not in positions:
            positions[q.expiration]=otm_strike_positions(spot,side,ladders.get(q.expiration,()))
        if positions[q.expiration].get(strike,MAX_OTM_STRIKES+1)<=MAX_OTM_STRIKES:
            result.append(q)
    return result


def itm_candidates(chain, *, underlying_price, underlying_stamp, side, as_of):
    # Compatibility for explicitly ITM-only read-only views and consumers.
    return [q for q in _current_candidates(chain,underlying_price=underlying_price,
        underlying_stamp=underlying_stamp,side=side,as_of=as_of)
        if (side=='CALL' and q.strike<underlying_price) or (side=='PUT' and q.strike>underlying_price)]


def _current_candidates(chain, *, underlying_price, underlying_stamp, side, as_of):
    """Read-only contract eligibility. Real quotes must be refreshed before any order."""
    if side not in ('CALL','PUT') or not math.isfinite(underlying_price) or underlying_price<=0:
        return []
    if not timedelta(0)<=as_of-underlying_stamp<=timedelta(seconds=30):
        return []
    today=as_of.astimezone(ZoneInfo('America/New_York')).date()
    result=[]
    for quote in chain:
        if quote.option_type.upper()!=side or quote.expiration<today or quote.feed!='opra':
            continue
        if quote.quote_timestamp is None or not timedelta(0)<=as_of-quote.quote_timestamp<=timedelta(seconds=30):
            continue
        if not all(math.isfinite(value) for value in (quote.strike,quote.bid,quote.ask)):
            continue
        if quote.bid<=0 or quote.ask<quote.bid or min(quote.bid_size,quote.ask_size)<=0:
            continue
        result.append(quote)
    return sorted(result,key=lambda q:(q.expiration,abs(q.strike-underlying_price)))


