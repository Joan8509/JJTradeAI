"""Explicit option-premium exit reviews for local simulation, without broker IO."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from option_position_sizing import ManualQuantityConfirmation, _price
from schwab_contracts import price_on_tick


PROFIT_PERCENT_CHOICES = (Decimal('10'), Decimal('20'), Decimal('35'), Decimal('100'))
GLOBAL_EXIT_POLICY_PATH = Path(__file__).resolve().parent/'config'/'option_exit_policy.json'


@dataclass(frozen=True)
class GlobalExitPolicy:
    stop_loss_pct: Decimal
    manual_close_available: bool


def load_global_exit_policy(path=GLOBAL_EXIT_POLICY_PATH):
    """Public risk decision only. Loading this file never enables execution."""
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        required={'schema_version','stop_loss_pct','stop_scope','basis','trigger',
                  'manual_close_available','real_orders_enabled'}
        if (not isinstance(data,dict) or set(data)!=required or
                type(data['schema_version']) is not int or data['schema_version']!=1 or
                data['stop_scope']!='GLOBAL_ALL_SYMBOLS' or data['basis']!='OPTION_FILL_VWAP_GROSS' or
                data['trigger']!='BID_AT_OR_BELOW' or data['manual_close_available'] is not True or
                data['real_orders_enabled'] is not False):
            raise ValueError('GLOBAL_EXIT_POLICY_INVALID')
        stop=_price(data['stop_loss_pct'])
        if not 0<stop<100:
            raise ValueError('GLOBAL_EXIT_POLICY_INVALID')
        return GlobalExitPolicy(stop,True)
    except (OSError,ValueError,TypeError):
        raise ValueError('GLOBAL_EXIT_POLICY_UNAVAILABLE') from None


def require_current_review(stamp, now):
    for value in (stamp, now):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('EXIT_REVIEW_CLOCK_INVALID')
    age = now.astimezone(timezone.utc)-stamp.astimezone(timezone.utc)
    if not timedelta(0) <= age <= timedelta(seconds=30):
        raise ValueError('EXIT_REVIEW_NOT_CURRENT')


@dataclass(frozen=True)
class ExitPlan:
    """Manual profit-taking still retains the explicitly selected loss/time limits."""
    profit_mode: str
    target_return_pct: Decimal | None
    stop_loss_pct: Decimal
    max_holding_minutes: int | None
    pricing_model: str = 'VERIFIED_TICK'

    def validated(self):
        if self.profit_mode not in ('TARGET_PERCENT', 'MANUAL'):
            raise ValueError('EXIT_PROFIT_MODE_INVALID')
        if self.profit_mode == 'MANUAL':
            if self.target_return_pct is not None:
                raise ValueError('MANUAL_PROFIT_CANNOT_HAVE_TARGET')
        elif _price(self.target_return_pct) not in PROFIT_PERCENT_CHOICES:
            raise ValueError('EXIT_TARGET_CHOICE_INVALID')
        if not 0 < _price(self.stop_loss_pct) < 100:
            raise ValueError('EXIT_STOP_PERCENT_INVALID')
        if self.pricing_model not in ('VERIFIED_TICK', 'OBSERVED_QUOTES_MANUAL_V1'):
            raise ValueError('EXIT_PRICING_MODEL_INVALID')
        if self.pricing_model == 'OBSERVED_QUOTES_MANUAL_V1':
            if self.max_holding_minutes is not None:
                raise ValueError('MANUAL_PRACTICE_HAS_NO_TIME_EXIT')
        elif type(self.max_holding_minutes) is not int or self.max_holding_minutes <= 0:
            raise ValueError('EXIT_TIME_LIMIT_INVALID')
        return self

    def levels(self, average_fill, increment):
        """Gross premium levels from actual fill VWAP; no hypothetical fill/fees."""
        self.validated()
        average = _price(average_fill)
        if average <= 0:
            raise ValueError('EXIT_FILL_PRICE_INVALID')
        # Validate the verified increment even when profit-taking is manual.
        observed = self.pricing_model == 'OBSERVED_QUOTES_MANUAL_V1'
        if observed:
            if increment is not None:
                raise ValueError('OBSERVED_PRICE_IS_NOT_VERIFIED_TICK')
        else:
            price_on_tick(average, increment, up=True)
        target = average*(1+_price(self.target_return_pct)/100) if self.profit_mode == 'TARGET_PERCENT' else None
        if target is not None and not observed:
            target = price_on_tick(target, increment, up=True)
        stop = average*(1-_price(self.stop_loss_pct)/100)
        return target, stop

    def payload(self, increment):
        self.validated()
        payload = {'profit_mode': self.profit_mode,
                'target_pct': str(_price(self.target_return_pct)) if self.target_return_pct is not None else None,
                'stop_pct': str(_price(self.stop_loss_pct)),
                'max_holding_minutes': self.max_holding_minutes, 'increment': str(increment)}
        if self.pricing_model == 'OBSERVED_QUOTES_MANUAL_V1':
            if increment is not None:
                raise ValueError('OBSERVED_PRICE_IS_NOT_VERIFIED_TICK')
            payload.update(pricing_model=self.pricing_model, increment=None)
        return payload


@dataclass(frozen=True)
class ExitPlanConfirmation:
    entry_review: ManualQuantityConfirmation
    plan: ExitPlan
    confirmed_at: datetime


def require_exit_plan(confirmation, entry_review, now):
    if type(confirmation) is not ExitPlanConfirmation or type(confirmation.plan) is not ExitPlan:
        raise ValueError('EXIT_PLAN_CONFIRMATION_REQUIRED')
    if type(confirmation.entry_review) is not ManualQuantityConfirmation or confirmation.entry_review != entry_review:
        raise ValueError('EXIT_ENTRY_REVIEW_CHANGED')
    require_current_review(confirmation.confirmed_at, now)
    return confirmation.plan.validated()


@dataclass(frozen=True)
class ManualCloseConfirmation:
    account_alias: str
    entry_client_key: str
    contract_symbol: str
    quantity: int
    minimum_price: Decimal
    confirmed_at: datetime


def require_manual_close(confirmation, *, account_alias, entry_client_key,
                         contract_symbol, quantity, limit_price, now):
    if type(confirmation) is not ManualCloseConfirmation:
        raise ValueError('MANUAL_CLOSE_CONFIRMATION_REQUIRED')
    if (confirmation.account_alias, confirmation.entry_client_key, confirmation.contract_symbol) != (
            account_alias, entry_client_key, contract_symbol):
        raise ValueError('MANUAL_CLOSE_IDENTITY_CHANGED')
    require_current_review(confirmation.confirmed_at, now)
    if type(confirmation.quantity) is not int or confirmation.quantity <= 0 or confirmation.quantity != quantity:
        raise ValueError('MANUAL_CLOSE_POSITION_CHANGED')
    if _price(confirmation.minimum_price) <= 0 or _price(confirmation.minimum_price) != _price(limit_price):
        raise ValueError('MANUAL_CLOSE_PRICE_CHANGED')
