"""Non-actionable option preparation; fixed diagnostics, no secrets or orders."""
from datetime import timedelta
from decimal import Decimal
from option_contract_selection import entry_candidates,select_entry_expiration
from manual_trade_service import ManualDataError

CONTRACT_REASONS=frozenset({'NOT_ITM','OUTSIDE_ALLOWED_MONEYNESS','ASK_OUTSIDE_RANGE','SPREAD_EXCEEDS_005','SPREAD_EXCEEDS_MAX',
    'QUOTE_NOT_CURRENT','UNDERLYING_NOT_CURRENT','INVALID_OPTION_MARKET','UNVERIFIED_FEED',
    'NOT_SELECTED_BY_CANONICAL_CHECKS','EXPIRATION_NOT_SELECTED','CONTRACT_UNAVAILABLE'})

def safe_contract_reasons(values):
    return list(dict.fromkeys(v for v in values if isinstance(v,str) and v in CONTRACT_REASONS)) if isinstance(values,(list,tuple)) else []

PUBLIC_ERRORS={'NO_CURRENT_SIGNAL','TRADE_NOT_CURRENT','DETECTOR_STATE_INVALID','COLLECTOR_NOT_CURRENT',
    'OUTSIDE_OFFICIAL_SESSION','SIGNAL_STATE_UNAVAILABLE','MONITOR_NOT_READY','SIGNAL_CHANGED',
    'SIGNAL_DIRECTION_CHANGED','OPTION_CHAIN_NOT_CURRENT','NO_ELIGIBLE_EXPIRATION_OR_RANGE',
    'OPTION_QUOTES_UNAVAILABLE','NO_ELIGIBLE_CONTRACTS','MARKET_DATA_COOLDOWN','RATE_LIMITED',
    'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','MARKET_DATA_UNAVAILABLE','TRANSPORT_FAILURE',
    'CONTRACT_NO_LONGER_ELIGIBLE','PRICE_CHANGED','GLOBAL_STOP_POLICY_MISMATCH',
    'ASK_CHANGED_PREPARE_AGAIN','REVIEW_SIGNAL_CHANGED','REVIEW_POLICY_CHANGED',
    'POSITION_RECONCILIATION_REQUIRED','TELEGRAM_AUTH_REQUIRED','NO_CURRENT_V4_EXIT',
    'UNDERLYING_QUOTE_NOT_CURRENT','PREPARATION_CHECK_FAILED','MANUAL_CONFIRMATION_ASK_CHANGED',
    'MANUAL_CONFIRMATION_COST_CHANGED','EXIT_REVIEW_NOT_CURRENT','OPTIMAL_PREMIUM_RANGE_MISSING',
    'DELIVERED_ALERT_REQUIRED','ALERT_WINDOW_ENDED','ALERT_REFERENCE_QUARANTINED','MANUAL_ALERT_PRACTICE_ONLY'}

def safe_entry_code(code):return code if code in PUBLIC_ERRORS else 'ENTRY_CHECK_FAILED'

def public_entry_error(error):
    from schwab_simulation import ExecutionBlocked
    from telegram_manual import TelegramManualError
    if isinstance(error,(ManualDataError,ExecutionBlocked,TelegramManualError)):
        return safe_entry_code(str(error))
    return 'ENTRY_CHECK_FAILED'

def preparation_candidates(market,symbol,side,now):
    """Prepare using real Schwab quotes while the IEX strategy is waiting.

    These candidates NEVER authorize an entry. Existing manual_candidates and
    validated_signal still require the actual fresh IEX EXIT when buying.
    """
    if (market.symbol,market.side)!=(symbol,side):raise ManualDataError('OPTION_CHAIN_NOT_CURRENT')
    if not timedelta(0)<=now-market.fetched_at<=timedelta(seconds=30):
        raise ManualDataError('OPTION_CHAIN_NOT_CURRENT')
    underlying=market.chain.underlying_price;stamp=market.chain.underlying_timestamp
    if stamp is None or not timedelta(0)<=now-stamp<=timedelta(seconds=30):
        raise ManualDataError('UNDERLYING_QUOTE_NOT_CURRENT')
    expiry=select_entry_expiration(market.expirations,now)
    snapshots=entry_candidates([c.snapshot for c in market.chain.contracts],symbol=symbol,side=side,
        underlying_price=float(underlying),underlying_stamp=stamp,as_of=now,listed_expirations=market.expirations, strike_inventory=market.strike_inventory)
    codes={q.symbol for q in snapshots}
    return expiry,tuple(c for c in market.chain.contracts if c.snapshot.symbol in codes)
