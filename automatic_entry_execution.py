"""Bounded price authorization for explicitly queued LOCAL simulation only."""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

ENTRY_LIFETIME_SECONDS = 10


@dataclass(frozen=True)
class QueuedEntryAuthorization:
    symbol: str
    quantity: int
    max_ask: Decimal
    max_cost: Decimal

    def payload(self, *, symbol, quantity, high, fee, now):
        from schwab_contracts import decimal
        from option_position_sizing import manual_entry_cost
        if (self.symbol != symbol or type(self.quantity) is not int or self.quantity != quantity
                or decimal(self.max_ask) != decimal(high)
                or decimal(self.max_cost) != manual_entry_cost(high, quantity, fee)):
            raise ValueError('QUEUE_PRICE_AUTHORIZATION_INVALID')
        return dict(entry_basis='ARMED_LOCAL_QUEUE_V2',entry_limit_basis='APPROVED_RANGE_CAP',
            entry_deadline=(now+timedelta(seconds=ENTRY_LIFETIME_SECONDS)).isoformat())


def queued_entry_expired(order, now):
    from datetime import datetime
    return (order.get('entry_basis') == 'ARMED_LOCAL_QUEUE_V2'
        and order['instruction'] == 'BUY_TO_OPEN'
        and now >= datetime.fromisoformat(order['entry_deadline']))


def require_queued_match(order, contract, market, now):
    """A price cap never permits stale, wide, crossed or distant contracts."""
    if order.get('entry_basis') != 'ARMED_LOCAL_QUEUE_V2' or order['instruction'] != 'BUY_TO_OPEN':
        return
    from option_contract_selection import entry_market_candidates, MAX_ENTRY_SPREAD
    from schwab_contracts import decimal
    q=contract.snapshot
    if decimal(q.ask)-decimal(q.bid)>MAX_ENTRY_SPREAD:
        raise ValueError('ENTRY_SPREAD_EXCEEDS_MAX')
    if not entry_market_candidates([q],strike_inventory=market.strike_inventory,
            underlying_price=market.chain.underlying_price,
            underlying_stamp=market.chain.underlying_timestamp,side=q.option_type,as_of=now):
        raise ValueError('CONTRACT_NOT_CURRENT_OR_OUTSIDE_OTM5')
