"""Manual standard100 quantity review and optional budget utility; no account IO."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _price(value):
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError('MANUAL_ENTRY_NUMBER_INVALID') from None


def manual_entry_cost(ask, quantity, fee_per_contract):
    """Estimate a standard100 entry for the exact user-selected whole quantity."""
    if type(quantity) is not int or quantity <= 0:
        raise ValueError('MANUAL_QUANTITY_INVALID')
    price, fee = _price(ask), _price(fee_per_contract)
    if price <= 0 or fee < 0:
        raise ValueError('MANUAL_ENTRY_NUMBER_INVALID')
    return (price*100+fee)*quantity


@dataclass(frozen=True)
class ManualQuantityConfirmation:
    account_alias: str
    underlying_symbol: str
    contract_symbol: str
    signal_key: str
    quantity: int
    ask: Decimal
    entry_cost: Decimal
    confirmed_at: datetime


def require_manual_confirmation(confirmation, *, account_alias, underlying_symbol,
        contract_symbol, signal_key, ask, fee_per_contract, as_of):
    """No fallback quantity and no reuse across accounts/contracts/signals/prices.

    Confirmation does not replace current signal/quote/risk/dedup checks. A newer
    quote at the same ask can be used; a changed ask or cost requires a new review.
    """
    if type(confirmation) is not ManualQuantityConfirmation:
        raise ValueError('MANUAL_QUANTITY_CONFIRMATION_REQUIRED')
    if (confirmation.account_alias, confirmation.underlying_symbol,
            confirmation.contract_symbol, confirmation.signal_key) != (
            account_alias, underlying_symbol, contract_symbol, signal_key):
        raise ValueError('MANUAL_CONFIRMATION_IDENTITY_CHANGED')
    for stamp in (confirmation.confirmed_at, as_of):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('MANUAL_CONFIRMATION_CLOCK_INVALID')
    age = as_of.astimezone(timezone.utc)-confirmation.confirmed_at.astimezone(timezone.utc)
    if not timedelta(0) <= age <= timedelta(seconds=30):
        raise ValueError('MANUAL_CONFIRMATION_NOT_CURRENT')
    if _price(confirmation.ask) != _price(ask):
        raise ValueError('MANUAL_CONFIRMATION_ASK_CHANGED')
    cost = manual_entry_cost(ask, confirmation.quantity, fee_per_contract)
    if _price(confirmation.entry_cost) != cost:
        raise ValueError('MANUAL_CONFIRMATION_COST_CHANGED')
    return confirmation.quantity, cost


def contracts_for_budget(budget_usd, ask, fee_per_contract):
    """Floor budget/(ask*100+entry costs), with no floating-point over-allocation.

    Budget must already be resolved in USD. Percentage policies require a
    separately verified capital basis; this function never assumes one. Supports
    only the standard100 multiplier validated by the contract adapter.
    Zero quantity is returned if one contract is unaffordable; never force one.
    Fees must be explicitly supplied (including an explicit verified zero).
    """
    try:
        values = (budget_usd, ask, fee_per_contract)
        if any(isinstance(value, bool) for value in values):
            raise ValueError
        budget, price, fees = (Decimal(str(value)) for value in values)
        if not all(value.is_finite() for value in (budget, price, fees)):
            raise ValueError
        if budget <= 0 or price <= 0 or fees < 0:
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError('BUDGET_SIZING_INPUT_INVALID') from None
    unit_cost = Fraction(price)*100 + Fraction(fees)
    return int(Fraction(budget) // unit_cost)
