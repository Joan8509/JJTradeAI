"""Strict Schwab-to-canonical option normalization and explicit policy checks."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
import re

from option_market_data import OptionSnapshot, _parse_occ_symbol
from option_contract_selection import itm_candidates


def decimal(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a price')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Finite number required')
    return result


def positive_int(value):
    if type(value) is not int or value <= 0:
        raise ValueError('Positive integer required')
    return value


def price_on_tick(value, increment, *, up):
    value, step = decimal(value), decimal(increment)
    if value <= 0 or step <= 0:
        raise ValueError('Positive price and verified increment required')
    result = (value/step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*step
    if result <= 0:
        raise ValueError('Price below permitted increment')
    return result


def milliseconds(value):
    stamp = decimal(value)
    if stamp <= 0:
        raise ValueError('Explicit quote timestamp required')
    return datetime.fromtimestamp(float(stamp/1000), timezone.utc)


@dataclass(frozen=True)
class SchwabContract:
    snapshot: OptionSnapshot
    multiplier: int
    standard_deliverable: bool
    price_increment: Decimal | None = None

    def validate_identity(self):
        q = self.snapshot
        if self.multiplier != 100 or not self.standard_deliverable:
            raise ValueError('Adjusted or unverified deliverable unsupported')
        compact = q.symbol.replace(' ', '')
        side, strike, expiration = _parse_occ_symbol(compact)
        root = re.fullmatch(r'([A-Z0-9.]{1,8})\d{6}[CP]\d{8}', compact).group(1)
        if (side != q.option_type or decimal(strike) != decimal(q.strike) or
                expiration != q.expiration or root != q.underlying_symbol):
            raise ValueError('Contract identity mismatch')
        if not all(math.isfinite(x) for x in (q.strike, q.bid, q.ask)):
            raise ValueError('Invalid option price')
        if q.strike <= 0 or q.bid <= 0 or q.ask < q.bid:
            raise ValueError('Invalid option market')
        positive_int(q.bid_size); positive_int(q.ask_size)
        if q.delta is not None and (not math.isfinite(q.delta) or not -1 <= q.delta <= 1):
            raise ValueError('Invalid option delta')
        return self

    def validated(self):
        self.validate_identity()
        if self.price_increment is None or decimal(self.price_increment) <= 0:
            raise ValueError('Verified price increment required')
        return self


@dataclass(frozen=True)
class SchwabChain:
    underlying_price: float
    underlying_timestamp: datetime
    contracts: tuple[SchwabContract, ...]
    rejected_contracts: int


def _standard_stock_delivery(item, underlying):
    """Accept only absent legacy detail or the observed exact 100-stock delivery.

    A populated list does not itself mean an adjusted option. Never accept cash,
    baskets, a different symbol, unknown fields, or inferred/coerced quantities.
    Explicit nonStandard flags, multiplier and OCC identity are checked separately.
    """
    delivery = item.get('optionDeliverablesList')
    if delivery is None or delivery == []:
        return True
    if not isinstance(delivery, list) or len(delivery) != 1 or not isinstance(delivery[0], dict):
        return False
    stock = delivery[0]
    return (set(stock) == {'symbol', 'assetType', 'deliverableUnits', 'currencyType'} and
            stock['symbol'] == underlying and stock['assetType'] == 'STOCK' and
            type(stock['deliverableUnits']) in (int, float) and stock['deliverableUnits'] == 100 and
            stock['currencyType'] is None)


def normalize_chain(payload, underlying, *, verified_increments=None):
    """Missing real-time flags, identity and deliverable metadata fail closed.

    `verified_increments` must come from approved instrument metadata or an
    explicit reviewed policy, never guessed from price/penny-pilot membership.
    No OPRA rights or live connection are proved by parsing a fixture.
    """
    if payload.get('symbol') != underlying or payload.get('isDelayed') is not False:
        raise ValueError('Underlying identity or real-time evidence missing')
    spot = payload.get('underlying', {})
    price = float(spot['last'])
    if not math.isfinite(price) or price <= 0:
        raise ValueError('Invalid underlying price')
    stamp = milliseconds(spot['quoteTime'])
    contracts, rejected = [], 0
    for key, side in (('callExpDateMap', 'CALL'), ('putExpDateMap', 'PUT')):
        for strikes in payload.get(key, {}).values():
            for group in strikes.values():
                for item in group:
                    try:
                        symbol = item['symbol']
                        expiration = date.fromisoformat(item['expirationDate'][:10])
                        # Live Schwab chains use nonStandard. Preserve the old adapter
                        # alias only with explicit false flags; missing or conflicting
                        # metadata must never certify a standard deliverable.
                        standard_flags = [item[name] for name in ('nonStandard', 'isNonStandard') if name in item]
                        if (item['putCall'] != side or not standard_flags or
                                any(value is not False for value in standard_flags) or
                                item.get('isDelayed', False) is not False or not _standard_stock_delivery(item, underlying)):
                            raise ValueError('Unsupported contract')
                        bid_size, ask_size = positive_int(item['bidSize']), positive_int(item['askSize'])
                        quote = OptionSnapshot(symbol=symbol, underlying_symbol=underlying,
                            option_type=side, strike=float(item['strikePrice']), expiration=expiration,
                            bid=float(item['bid']), ask=float(item['ask']), bid_size=bid_size,
                            ask_size=ask_size, quote_timestamp=milliseconds(item['quoteTimeInLong']),
                            latest_trade=None, implied_volatility=None,
                            delta=float(item['delta']) if item.get('delta') is not None else None,
                            gamma=None, theta=None, vega=None, feed='opra')
                        step = (verified_increments or {}).get(symbol)
                        contract = SchwabContract(quote, item['multiplier'], True,
                                                 decimal(step) if step is not None else None)
                        contract.validate_identity()
                        contracts.append(contract)
                    except (KeyError, ValueError, TypeError, OverflowError):
                        rejected += 1
    return SchwabChain(price, stamp, tuple(contracts), rejected)


def canonical_itm_contracts(chain, side, now):
    quotes = itm_candidates([c.snapshot for c in chain.contracts],
        underlying_price=chain.underlying_price, underlying_stamp=chain.underlying_timestamp,
        side=side, as_of=now)
    by_symbol = {c.snapshot.symbol: c for c in chain.contracts}
    return tuple(by_symbol[q.symbol] for q in quotes)
