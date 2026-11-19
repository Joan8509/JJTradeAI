"""Complete cumulative SINGLE option snapshots, not fabricated execution IDs.

The record keys identify canonical observations within this order's complete
history. They are never represented as broker execution identities. Repeated
identical records retain their multiplicity; later snapshots must contain the
entire earlier multiset. No quantity or price is inferred from an average.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re

from schwab_connection import aware
from schwab_contracts import decimal
from schwab_reconciliation import contracts_integer

CANCEL_ACTIVITY_REVISION=1


@dataclass(frozen=True)
class ExecutionSnapshot:
    broker_id: str = field(repr=False)
    contract: str
    instruction: str
    quantity: int
    status: str
    fills: tuple = field(repr=False)
    issues: tuple


def _cancellation_record(activity,leg,*,status,unfilled,payload):
    """A zero-price cancellation acknowledgement is not an executed fill.

    Recognize only the observed SINGLE-leg terminal shape. Unknown activities,
    positive prices and mismatched quantities/identities remain unsupported.
    """
    try:
        executions=activity.get('executionLegs')
        if (status!='CANCELED' or activity.get('activityType')!='EXECUTION'
                or activity.get('executionType')!='CANCELED' or unfilled<=0
                or contracts_integer(activity['quantity'])!=unfilled
                or contracts_integer(activity['orderRemainingQuantity'])!=0
                or not isinstance(executions,list) or len(executions)!=1):return False
        item=executions[0]
        if (leg.get('legId') is None or item.get('legId')!=leg['legId']
                or contracts_integer(item['quantity'])!=unfilled
                or decimal(item['price'])!=0 or decimal(item.get('mismarkedQuantity',0))!=0):return False
        instrument=leg.get('instrument',{}).get('instrumentId')
        if instrument is not None and item.get('instrumentId')!=instrument:return False
        stamp=aware(datetime.fromisoformat(item['time'].replace('Z','+00:00')))
        if payload.get('enteredTime') and stamp<aware(datetime.fromisoformat(payload['enteredTime'].replace('Z','+00:00'))):return False
        if payload.get('closeTime') and stamp>aware(datetime.fromisoformat(payload['closeTime'].replace('Z','+00:00'))):return False
        return True
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError):return False


def normalize_execution_snapshot(payload, *, account_number):
    """Require account identity and complete explicit execution leg evidence."""
    if not isinstance(account_number,str) or not re.fullmatch(r'[0-9]{1,32}',account_number):
        raise ValueError('ORDER_ACCOUNT_REQUIRED')
    if not isinstance(payload, dict) or str(payload.get('accountNumber', '')) != account_number:
        raise ValueError('ORDER_ACCOUNT_MISMATCH')
    identity = str(payload.get('orderId', ''))
    if not re.fullmatch(r'[1-9][0-9]{0,18}', identity) or int(identity) > 9223372036854775807:
        raise ValueError('ORDER_ID_INVALID')
    legs = payload.get('orderLegCollection')
    if (payload.get('orderStrategyType') != 'SINGLE' or payload.get('childOrderStrategies')
            or payload.get('replacingOrderCollection') or not isinstance(legs, list) or len(legs) != 1):
        raise ValueError('SINGLE_ORDER_REQUIRED')
    leg = legs[0]
    if (leg.get('instruction') not in ('BUY_TO_OPEN', 'SELL_TO_CLOSE')
            or leg.get('instrument', {}).get('assetType') != 'OPTION'):
        raise ValueError('OPTION_INSTRUCTION_REQUIRED')
    contract = leg['instrument']['symbol']
    if not isinstance(contract, str) or not re.fullmatch(r'[A-Z0-9.]{1,8} *\d{6}[CP]\d{8}', contract):
        raise ValueError('OPTION_IDENTITY_INVALID')
    from option_market_data import _parse_occ_symbol
    _parse_occ_symbol(contract.replace(' ', ''))
    quantity = contracts_integer(payload['quantity'])
    filled = contracts_integer(payload['filledQuantity'])
    remaining = contracts_integer(payload['remainingQuantity'])
    terminal_unfilled=payload.get('status') in ('CANCELED','EXPIRED','REJECTED') and remaining==0 and filled<=quantity
    if quantity <= 0 or contracts_integer(leg['quantity']) != quantity or (filled + remaining != quantity and not terminal_unfilled):
        raise ValueError('ORDER_QUANTITIES_INCONSISTENT')
    issues = []
    raw = payload.get('status')
    active = {'NEW', 'WORKING', 'QUEUED', 'ACCEPTED', 'PENDING_ACTIVATION',
              'PENDING_ACKNOWLEDGEMENT', 'AWAITING_RELEASE_TIME'}
    status = ('PARTIALLY_FILLED' if filled else 'WORKING') if raw in active else raw
    if raw not in active | {'PENDING_CANCEL', 'CANCELED', 'FILLED', 'REJECTED', 'EXPIRED'}:
        issues.append('UNKNOWN_BROKER_STATE')
        status = 'RECONCILIATION_REQUIRED'
    if raw == 'FILLED' and filled != quantity:
        issues.append('TERMINAL_FILL_QUANTITY_MISMATCH')
    if raw == 'REJECTED' and filled:
        issues.append('REJECTED_ORDER_HAS_EXECUTIONS')
    activities = payload.get('orderActivityCollection', [] if filled==0 else None)
    # Schwab reports null, not [], for orders with explicitly zero executions.
    # A nonzero filledQuantity still requires the complete execution records.
    if activities is None and filled==0:activities=[]
    if not isinstance(activities, list):
        raise ValueError('COMPLETE_ACTIVITY_HISTORY_REQUIRED')
    records = []
    for activity in activities:
        if not isinstance(activity, dict):
            raise ValueError('ACTIVITY_INVALID')
        if activity.get('executionType') != 'FILL':
            if _cancellation_record(activity,leg,status=raw,unfilled=quantity-filled,payload=payload):
                continue
            if activity.get('executionLegs'):
                issues.append('UNSUPPORTED_EXECUTION_ACTIVITY')
            continue
        if activity.get('activityType') != 'EXECUTION':
            raise ValueError('EXECUTION_ACTIVITY_REQUIRED')
        executions = activity.get('executionLegs')
        if not isinstance(executions, list) or not executions:
            raise ValueError('EXECUTION_DETAILS_REQUIRED')
        activity_amount = 0
        for execution in executions:
            if execution.get('legId') != leg.get('legId') or leg.get('legId') is None:
                raise ValueError('EXECUTION_LEG_MISMATCH')
            amount = contracts_integer(execution['quantity'])
            price = decimal(execution['price'])
            if amount <= 0 or price <= 0 or decimal(execution.get('mismarkedQuantity', 0)) != 0:
                raise ValueError('EXECUTION_VALUES_INVALID')
            stamp = aware(datetime.fromisoformat(execution['time'].replace('Z', '+00:00')))
            # Fingerprint only canonical, broker-reported execution fields.
            record = dict(quantity=amount, price=str(price.normalize()), time=stamp.isoformat())
            records.append(record)
            activity_amount += amount
        if contracts_integer(activity['quantity']) != activity_amount:
            raise ValueError('ACTIVITY_QUANTITY_MISMATCH')
    if sum(r['quantity'] for r in records) != filled:
        issues.append('EXECUTION_DETAILS_INCOMPLETE')
    counts = Counter()
    fills = []
    for record in sorted(records, key=lambda r: (r['time'], r['price'], r['quantity'])):
        digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        counts[digest] += 1
        fills.append(dict(record, record_key=f'{digest}:{counts[digest]}',
                          evidence_kind='CUMULATIVE_EXECUTION_RECORD'))
    return ExecutionSnapshot(identity, contract, leg['instruction'], quantity, status,
                             tuple(fills), tuple(sorted(set(issues))))
