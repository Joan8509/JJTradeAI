"""Normalize broker evidence and report drift. Never adopts orders or sends any.

Missing execution identities/cumulative evidence blocks reconciliation; average
prices or order quantities are never expanded into invented individual fills.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from schwab_contracts import decimal


def contracts_integer(value):
    result = decimal(value)
    if result < 0 or result != result.to_integral_value():
        raise ValueError('Whole nonnegative contract quantity required')
    return int(result)


@dataclass(frozen=True)
class BrokerOrderEvidence:
    broker_id: str = field(repr=False)
    contract: str
    instruction: str
    quantity: int
    filled_quantity: int
    status: str
    fills: tuple[dict, ...] = field(repr=False)
    issues: tuple[str, ...]


def normalize_order(payload):
    issues = []
    legs = payload.get('orderLegCollection', [])
    if len(legs) != 1 or payload.get('childOrderStrategies') or payload.get('orderStrategyType') != 'SINGLE':
        raise ValueError('Complex or unverifiable order requires separate reconciliation')
    leg = legs[0]
    if leg.get('instruction') not in ('BUY_TO_OPEN', 'SELL_TO_CLOSE') or leg.get('instrument', {}).get('assetType') != 'OPTION':
        raise ValueError('Unsupported order instruction or asset')
    quantity = contracts_integer(payload['quantity'])
    filled = contracts_integer(payload['filledQuantity'])
    if quantity <= 0 or filled > quantity or contracts_integer(leg['quantity']) != quantity:
        raise ValueError('Inconsistent order quantities')
    remaining = payload.get('remainingQuantity')
    if remaining is None or contracts_integer(remaining)+filled != quantity:
        issues.append('REMAINING_QUANTITY_UNPROVEN')
    active = {'NEW', 'WORKING', 'QUEUED', 'ACCEPTED', 'PENDING_ACTIVATION',
              'PENDING_ACKNOWLEDGEMENT', 'PENDING_CANCEL', 'PENDING_REPLACE',
              'AWAITING_PARENT_ORDER', 'AWAITING_CONDITION', 'AWAITING_RELEASE_TIME'}
    terminal = {'FILLED', 'CANCELED', 'REJECTED', 'EXPIRED', 'REPLACED'}
    raw_status = payload.get('status', 'UNKNOWN')
    status = ('PARTIALLY_FILLED' if filled else 'WORKING') if raw_status in active else raw_status
    if raw_status not in active | terminal:
        issues.append('UNKNOWN_BROKER_STATE')
    if raw_status in ('PENDING_CANCEL', 'PENDING_REPLACE'):
        status = raw_status  # A request is not an acknowledged cancellation.
    if raw_status == 'FILLED' and filled != quantity:
        issues.append('TERMINAL_FILL_QUANTITY_MISMATCH')
    fills, seen = [], set()
    for activity in payload.get('orderActivityCollection', []):
        if activity.get('executionType') != 'FILL':
            continue
        for execution in activity.get('executionLegs', []):
            identity = execution.get('executionId')
            if identity is None and activity.get('activityId') is not None and execution.get('legId') is not None:
                identity = str(activity['activityId'])+':'+str(execution['legId'])
            if identity is None:
                issues.append('EXECUTION_IDENTITY_UNPROVEN'); continue
            identity = str(identity)
            amount, price = contracts_integer(execution['quantity']), decimal(execution['price'])
            if amount <= 0 or price <= 0 or not execution.get('time'):
                raise ValueError('Invalid execution evidence')
            item = {'execution_id': identity, 'quantity': amount, 'price': str(price), 'time': execution['time']}
            if identity in seen:
                issues.append('DUPLICATE_EXECUTION_IDENTITY'); continue
            seen.add(identity); fills.append(item)
    if sum(f['quantity'] for f in fills) != filled:
        issues.append('EXECUTION_DETAILS_INCOMPLETE')
    return BrokerOrderEvidence(str(payload['orderId']), leg['instrument']['symbol'], leg['instruction'],
                               quantity, filled, status, tuple(fills), tuple(sorted(set(issues))))


def reconcile_read_only(expected_orders, broker_orders, broker_positions, expected_positions):
    """Known broker IDs only. Uncertain submissions without ID remain uncertain.

    Account-wide unexplained positions/orders block readiness; they are not
    silently attached to this strategy, erased or closed.
    """
    issues = []
    remote = {}
    for item in broker_orders:
        if item.broker_id in remote:
            issues.append('DUPLICATE_BROKER_ORDER_ID')
        remote[item.broker_id] = item
        issues.extend(item.issues)
    known = set()
    for expected in expected_orders:
        identity = expected.get('broker_id')
        if not identity:
            issues.append('UNCERTAIN_SUBMISSION_REQUIRES_REVIEW'); continue
        known.add(str(identity)); actual = remote.get(str(identity))
        if actual is None:
            issues.append('KNOWN_ORDER_MISSING'); continue
        if (actual.contract, actual.instruction, actual.quantity) != (
                expected['contract'], expected['instruction'], expected['quantity']):
            issues.append('ORDER_IDENTITY_MISMATCH')
        if actual.filled_quantity < expected.get('filled_quantity', 0):
            issues.append('CUMULATIVE_FILL_REGRESSION')
    if set(remote)-known:
        issues.append('UNEXPLAINED_ACCOUNT_ORDERS')
    positions = {}
    for row in broker_positions:
        instrument = row.get('instrument', {})
        if instrument.get('assetType') != 'OPTION':
            issues.append('UNEXPLAINED_NONOPTION_POSITION'); continue
        if contracts_integer(row.get('shortQuantity', 0)):
            issues.append('UNSUPPORTED_SHORT_POSITION')
        symbol = instrument.get('symbol')
        if not symbol or symbol in positions:
            issues.append('POSITION_IDENTITY_UNPROVEN'); continue
        quantity = contracts_integer(row.get('longQuantity', 0))
        if quantity:
            positions[symbol] = quantity
    if positions != {s: contracts_integer(q) for s, q in expected_positions.items() if q}:
        issues.append('POSITION_MISMATCH')
    return {'status': 'RECONCILED' if not issues else 'BLOCKED', 'issues': sorted(set(issues)),
            'order_count': len(remote), 'position_count': len(positions),
            'orders_sent': 0, 'positions_modified': 0, 'real_orders_enabled': False}
