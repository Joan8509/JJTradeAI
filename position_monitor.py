"""Read-only valuation of the remaining option position; never authorizes orders."""
from datetime import datetime, timedelta, timezone

from option_exit_plan import ExitPlan
from option_position_sizing import _price


def position_mark(position, market, *, now, unavailable=False):
    """Bid is indicative liquidation, gross targets use actual remaining VWAP.

    Previous/future/closed/unavailable quotes never generate a current P&L.
    Missing costs remain unknown. No underlying price enters option P&L.
    """
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('POSITION_CLOCK_INVALID')
    quantity=position['quantity'];average=_price(position['average_fill'])
    if type(quantity) is not int or quantity<=0 or average<=0:
        raise ValueError('POSITION_BASIS_INVALID')
    stored=position['plan']
    plan=ExitPlan(stored['profit_mode'],
        _price(stored['target_pct']) if stored['target_pct'] is not None else None,
        _price(stored['stop_pct']),stored['max_holding_minutes'],stored.get('pricing_model','VERIFIED_TICK'))
    target,stop=plan.levels(average,stored['increment'])
    result=dict(average_fill=average,quantity=quantity,target=target,stop=stop,
        bid=None,ask=None,quote_timestamp=None,age_seconds=None,status='UNAVAILABLE',
        value=None,gross_pnl=None,gross_pct=None,net_estimate=None,net_pct=None,
        underlying_price=None,underlying_timestamp=None,underlying_current=False)
    if not market:
        return result
    q=market.get('snapshot')
    if q is None:
        return result
    try:
        if (q.symbol,q.underlying_symbol,q.option_type)!=(
                position['contract'],position['symbol'],position['side']) or q.feed!='opra':
            raise ValueError
        bid,ask=_price(q.bid),_price(q.ask)
        if bid<=0 or ask<bid or type(q.bid_size) is not int or type(q.ask_size) is not int or min(q.bid_size,q.ask_size)<=0:
            raise ValueError
        stamp=q.quote_timestamp
        if not isinstance(stamp,datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        age=(now.astimezone(timezone.utc)-stamp.astimezone(timezone.utc)).total_seconds()
        result.update(bid=bid,ask=ask,quote_timestamp=stamp,age_seconds=age)
        status=('UNAVAILABLE' if unavailable else 'FUTURE' if age<0 else
                'CLOSED' if market.get('session_open') is not True else 'STALE' if age>30 else 'LIVE')
        result['status']=status
    except (ValueError,TypeError,AttributeError):
        result['status']='INVALID';return result
    try:
        spot=_price(market['underlying_price']);spot_stamp=market['underlying_timestamp']
        if spot<=0 or spot_stamp.tzinfo is None or spot_stamp.utcoffset() is None:
            raise ValueError
        age_spot=(now.astimezone(timezone.utc)-spot_stamp.astimezone(timezone.utc)).total_seconds()
        if age_spot<0:
            raise ValueError
        result.update(underlying_price=spot,underlying_timestamp=spot_stamp,
            underlying_current=(status=='LIVE' and 0<=age_spot<=3))
    except (ValueError,TypeError,KeyError,AttributeError):
        pass
    if status!='LIVE':
        return result
    basis=average*quantity*100
    value=bid*quantity*100;gross=value-basis
    result.update(value=value,gross_pnl=gross,gross_pct=gross/basis*100)
    # Fees of remaining fills plus estimated exit costs; unknown is never zero.
    if position.get('entry_fees') is not None and position.get('exit_fee_per_contract') is not None:
        entry_fees=_price(position['entry_fees']);exit_fees=_price(position['exit_fee_per_contract'])*quantity
        if min(entry_fees,exit_fees)<0:
            raise ValueError('POSITION_FEES_INVALID')
        net=gross-entry_fees-exit_fees
        result.update(net_estimate=net,net_pct=net/(basis+entry_fees)*100)
    return result


def append_bid_observation(history, mark, *, limit=300):
    """RAM chart only: one point per provider timestamp, gaps are not joined."""
    points=list(history)
    if mark['status']!='LIVE':
        return points[-limit:]
    stamp=mark['quote_timestamp']
    previous=datetime.fromisoformat(points[-1]['time']) if points else None
    if previous is not None and stamp<=previous:
        return points[-limit:]
    segment=points[-1]['segment'] if points else 0
    if previous is not None and stamp-previous>timedelta(seconds=30):
        segment+=1
    points.append(dict(time=stamp.isoformat(),bid=float(mark['bid']),segment=segment))
    return points[-limit:]
