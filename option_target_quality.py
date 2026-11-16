"""Offline, descriptive target effort for already-qualified contracts. No trading authority."""
from decimal import Decimal,ROUND_CEILING
from math import isfinite

REVISION='target_effort_research_v1'

def number(value):
    if isinstance(value,bool):return None
    try:
        x=float(value)
        return x if isfinite(x) else None
    except (ValueError,TypeError):return None

def target_effort(contract,*,spot,target='10',quantity=1,now):
    """No range, expiry or risk policy is supplied here; caller must qualify first.

    Delta projection assumes constant Greeks/IV/time and is NOT a forecast or
    calibrated probability. Tick absence stays unknown, not a fabricated cent.
    """
    contract.validate_identity();q=contract.snapshot
    if type(quantity) is not int or quantity<1:raise ValueError('QUANTITY_REQUIRED')
    if now.tzinfo is None or q.quote_timestamp is None or q.quote_timestamp.tzinfo is None:
        raise ValueError('AWARE_QUOTE_REQUIRED')
    age=(now-q.quote_timestamp).total_seconds()
    if not 0<=age<30:raise ValueError('QUOTE_NOT_CURRENT')
    a,b=Decimal(str(q.ask)),Decimal(str(q.bid));t=Decimal(str(target));s=number(spot)
    if not t.is_finite() or t<=0 or s is None or s<=0:raise ValueError('POSITIVE_TARGET_AND_SPOT_REQUIRED')
    gross=a*t/100;ideal=a+gross
    increment=contract.price_increment
    limit=((ideal/increment).to_integral_value(rounding=ROUND_CEILING)*increment) if increment is not None else None
    delta=number(q.delta)
    aligned=delta is not None and ((q.option_type=='CALL' and 0<delta<=1) or (q.option_type=='PUT' and -1<=delta<0))
    desired=(limit if limit is not None else ideal)-b
    move=float(desired)/abs(delta) if aligned else None
    return dict(revision=REVISION,contract=q.symbol,ask=str(a),bid=str(b),target_pct=str(t),
        quantity=quantity,quote_age_seconds=age,spread_fraction=float((a-b)/a),
        spread_to_target_profit=float((a-b)/gross),gross_goal_dollars=str(gross*100*quantity),
        ideal_target_price=str(ideal),verified_tick_target_price=str(limit) if limit is not None else None,
        favorable_underlying_move_delta_only=move,
        favorable_underlying_move_pct_delta_only=100*move/s if move is not None else None,
        delta=delta,delta_direction_valid=aligned,calibrated=False,order_authorized=False,
        assumptions=['Constant delta, volatility, time and Bid/Ask spread','Fees excluded','Actual target tick requires broker verification'])

def dominates(left,right):
    """Research Pareto comparison: improve one effort measure without worsening another."""
    keys=('spread_fraction','favorable_underlying_move_pct_delta_only')
    a=[number(left.get(k)) for k in keys];b=[number(right.get(k)) for k in keys]
    if any(v is None for v in a+b):return None
    return all(x<=y for x,y in zip(a,b)) and any(x<y for x,y in zip(a,b))

def frontier(rows):
    """Unknown Greek evidence is reported separately, never treated as failure."""
    comparable=[r for r in rows if r.get('favorable_underlying_move_pct_delta_only') is not None]
    return dict(frontier=[r['contract'] for r in comparable if not any(dominates(other,r) is True for other in comparable)],
        unknown=[r['contract'] for r in rows if r.get('favorable_underlying_move_pct_delta_only') is None],
        dominated=[r['contract'] for r in comparable if any(dominates(other,r) is True for other in comparable)],
        selected_contract=None,order_authorized=False)
