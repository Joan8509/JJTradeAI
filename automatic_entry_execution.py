"""Bounded price authorization for explicitly queued LOCAL simulation only."""
from dataclasses import dataclass
from datetime import datetime,timedelta
from decimal import Decimal

ENTRY_LIFETIME_SECONDS = 10
SIGNAL_ENTRY_WINDOW_SECONDS = 30
SIGNAL_WINDOW_REVISION = 'durable_first_signal_30s_v1'


def signal_entry_deadline(first_source_at, now):
    if (first_source_at.tzinfo is None or first_source_at.utcoffset() is None or
            now.tzinfo is None or now.utcoffset() is None or first_source_at>now):
        raise ValueError('SIGNAL_ENTRY_CLOCK_INVALID')
    deadline=first_source_at+timedelta(seconds=SIGNAL_ENTRY_WINDOW_SECONDS)
    if now>=deadline:raise ValueError('SIGNAL_ENTRY_WINDOW_EXPIRED')
    return deadline


@dataclass(frozen=True)
class QueuedEntryAuthorization:
    symbol: str
    quantity: int
    max_ask: Decimal
    max_cost: Decimal
    first_signal_at: datetime | None = None

    def payload(self, *, symbol, quantity, high, fee, now):
        from schwab_contracts import decimal
        from option_position_sizing import manual_entry_cost
        if (self.symbol != symbol or type(self.quantity) is not int or self.quantity != quantity
                or decimal(self.max_ask) != decimal(high)
                or decimal(self.max_cost) != manual_entry_cost(high, quantity, fee)):
            raise ValueError('QUEUE_PRICE_AUTHORIZATION_INVALID')
        deadline=now+timedelta(seconds=ENTRY_LIFETIME_SECONDS)
        evidence={}
        if self.first_signal_at is not None:
            signal_deadline=signal_entry_deadline(self.first_signal_at,now)
            deadline=min(deadline,signal_deadline)
            evidence=dict(entry_first_signal_at=self.first_signal_at.isoformat(),
                entry_signal_deadline=signal_deadline.isoformat(),
                entry_signal_window_seconds=SIGNAL_ENTRY_WINDOW_SECONDS)
        return dict(entry_basis='ARMED_LOCAL_QUEUE_V2',entry_limit_basis='APPROVED_RANGE_CAP',
            entry_deadline=deadline.isoformat(),**evidence)


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
