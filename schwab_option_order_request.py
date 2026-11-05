"""Option LIMIT request drafts from the documented Schwab OrderRequest schema.

Enums supplied from the authenticated developer portal, 2026-11-01. No HTTP,
account selection, order submission or simulation imports. A valid draft is
not evidence of broker acceptance, buying power, risk approval or exit coverage.
"""
from dataclasses import dataclass
from datetime import datetime,timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from schwab_connection import aware,SchwabError
from schwab_contracts import SchwabContract,positive_int,decimal


@dataclass(frozen=True)
class OptionLimitRequest:
    contract: str
    instruction: str
    quantity: int
    limit: Decimal
    created_at: datetime
    expires_at: datetime
    price_validation: str='VERIFIED_INCREMENT'

    def payload(self,now):
        """Only a serializer; callers still need account/strategy/risk validation."""
        now=aware(now)
        if not aware(self.created_at)<=now<aware(self.expires_at):
            raise SchwabError('ORDER_REQUEST_NOT_CURRENT')
        if self.instruction not in ('BUY_TO_OPEN','SELL_TO_CLOSE'):
            raise SchwabError('ORDER_INSTRUCTION_NOT_ALLOWED')
        positive_int(self.quantity)
        price=decimal(self.limit)
        if price<=0:raise SchwabError('ORDER_LIMIT_INVALID')
        return dict(session='NORMAL',duration='DAY',orderType='LIMIT',orderStrategyType='SINGLE',
            price=format(price,'f'),orderLegCollection=[dict(instruction=self.instruction,quantity=self.quantity,
                instrument=dict(symbol=self.contract,assetType='OPTION'))])


def prepare_option_limit(contract,*,instruction,quantity,now,valid_until,close_limit=None):
    """Buy at the observed Ask; sell at explicit close limit or observed Bid.

    A sell draft does not prove ownership. The encrypted execution journal must
    reserve confirmed owned contracts before any future network dispatch.
    A stop-triggered Bid limit is a LIMIT order and does not guarantee a fill.
    Minimum request acceptance and broker protection support still need review.
    """
    if type(contract) is not SchwabContract:raise SchwabError('OPTION_CONTRACT_REQUIRED')
    contract.validated();positive_int(quantity)
    if instruction not in ('BUY_TO_OPEN','SELL_TO_CLOSE'):
        raise SchwabError('ORDER_INSTRUCTION_NOT_ALLOWED')
    now=aware(now);q=contract.snapshot
    stamp=aware(q.quote_timestamp)
    if not timedelta(0)<=now-stamp<timedelta(seconds=30):raise SchwabError('OPTION_QUOTE_NOT_CURRENT')
    if q.expiration<now.astimezone(ZoneInfo('America/New_York')).date():
        raise SchwabError('OPTION_CONTRACT_EXPIRED')
    if instruction=='BUY_TO_OPEN':
        if close_limit is not None:raise SchwabError('BUY_LIMIT_MUST_BE_ASK')
        price=decimal(q.ask)
    else:price=decimal(q.bid if close_limit is None else close_limit)
    if price<=0 or price%decimal(contract.price_increment)!=0:
        raise SchwabError('LIMIT_NOT_ON_VERIFIED_INCREMENT')
    deadline=min(aware(valid_until),stamp+timedelta(seconds=30))
    if now>=deadline:raise SchwabError('ORDER_REQUEST_NOT_CURRENT')
    return OptionLimitRequest(q.symbol,instruction,quantity,price,now,deadline)


def prepare_option_preview(contract,*,instruction,quantity,now,valid_until):
    """An exact quoted price for non-executing preview, never an increment grant."""
    if type(contract) is not SchwabContract:raise SchwabError('OPTION_CONTRACT_REQUIRED')
    contract.validate_identity();positive_int(quantity)
    if instruction not in ('BUY_TO_OPEN','SELL_TO_CLOSE'):raise SchwabError('ORDER_INSTRUCTION_NOT_ALLOWED')
    now=aware(now);q=contract.snapshot;stamp=aware(q.quote_timestamp)
    if not timedelta(0)<=now-stamp<timedelta(seconds=30):raise SchwabError('OPTION_QUOTE_NOT_CURRENT')
    if q.expiration<now.astimezone(ZoneInfo('America/New_York')).date():raise SchwabError('OPTION_CONTRACT_EXPIRED')
    deadline=min(aware(valid_until),stamp+timedelta(seconds=30))
    if now>=deadline:raise SchwabError('ORDER_REQUEST_NOT_CURRENT')
    price=decimal(q.ask if instruction=='BUY_TO_OPEN' else q.bid)
    return OptionLimitRequest(q.symbol,instruction,quantity,price,now,deadline,'PREVIEW_ONLY')


def prepare_observed_limit(contract,*,instruction,quantity,now,valid_until):
    """Exact Schwab BBO only, without claiming a general tick-size schedule.

    No computed or rounded price is permitted. The broker remains authoritative
    and can reject the submitted limit. Never upgrades a preview-only draft.
    """
    draft=prepare_option_preview(contract,instruction=instruction,quantity=quantity,now=now,valid_until=valid_until)
    if contract.snapshot.feed not in ('opra','SCHWAB'):
        raise SchwabError('SCHWAB_OBSERVED_QUOTE_REQUIRED')
    from dataclasses import replace
    return replace(draft,price_validation='OBSERVED_SCHWAB_QUOTE')
