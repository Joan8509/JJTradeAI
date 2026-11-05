"""Read-only one-contract budget planning. A range is not a live quote."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def current_budget(status, binding, now=None):
    now=now or datetime.now(timezone.utc)
    try:
        budget=status['budget']
        if not binding or status['binding']!=binding or budget['binding']!=binding:raise ValueError
        for stamp,limit in ((status['checked_at'],5),(budget['checked_at'],30)):
            age=(now-datetime.fromisoformat(stamp)).total_seconds()
            if not 0<=age<limit:raise ValueError
        values={key:Decimal(budget[key]) for key in ('capacity','reserved','available')}
        if any(not value.is_finite() or value<0 for value in values.values()):raise ValueError
        if values['available']!=max(Decimal(0),values['capacity']-values['reserved']):raise ValueError
        return values
    except (KeyError,TypeError,ValueError,InvalidOperation):
        raise ValueError('BUDGET_NOT_CURRENT') from None


def range_candidates(symbols, available, ranges):
    """Premium-only planning; commissions and actual availability remain unknown."""
    available=Decimal(available)
    if not available.is_finite() or available<0:raise ValueError('BUDGET_INVALID')
    result=[]
    for symbol in symbols:
        row=dict(symbol=symbol,quantity=1,state='RANGE_MISSING',candidate=False)
        if symbol in ranges:
            low,high=(Decimal(v) for v in ranges[symbol])
            if not low.is_finite() or not high.is_finite() or not 0<low<=high:
                raise ValueError('RANGE_INVALID')
            minimum,maximum=low*100,high*100
            # Equality leaves no room for unconfirmed commission/fees.
            candidate=minimum<available
            row.update(low=low,high=high,minimum=minimum,maximum=maximum,
                ask_ceiling=min(high,available/100),candidate=candidate,
                state='CANDIDATE_COSTS_PENDING' if candidate else
                    'COSTS_LEAVE_NO_MARGIN' if minimum==available else 'OUT_OF_BUDGET')
        result.append(row)
    return sorted(result,key=lambda r:(not r['candidate'],r.get('minimum',Decimal('Infinity')),r['symbol']))


def verify_contract_budget(symbol,side,*,context,market,preview,budget_reader,idle,
                          session_provider,clock=lambda:datetime.now(timezone.utc)):
    """One explicit read-only check. No strategy/permit/queue/order is created."""
    from datetime import timedelta
    from hashlib import sha256
    import json
    from option_contract_selection import entry_candidates
    from schwab_option_order_request import prepare_option_preview
    from schwab_preview_client import wire_payload
    from real_live_capital import preview_cost
    def evidence():
        now=clock();start,end=session_provider(now)
        if not start<=now<end:raise ValueError('OUTSIDE_OFFICIAL_SESSION')
        if idle() is not True:raise ValueError('BUDGET_CHECK_EXECUTOR_BUSY')
        return current_budget(budget_reader(),context.binding,now),end
    budget,end=evidence()
    chain=market.get_catalog_chain(symbol,side,clock())
    budget,end=evidence()
    quotes=entry_candidates([c.snapshot for c in chain.chain.contracts],symbol=symbol,side=side,
        underlying_price=chain.chain.underlying_price,underlying_stamp=chain.chain.underlying_timestamp,
        as_of=clock(),listed_expirations=chain.expirations,strike_inventory=chain.strike_inventory)
    quotes=sorted((q for q in quotes if Decimal(str(q.ask))*100<=budget['available']),key=lambda q:Decimal(str(q.ask)))
    if not quotes:raise ValueError('NO_CURRENT_AFFORDABLE_CONTRACT')
    quote=quotes[0]
    contract=next(c for c in chain.chain.contracts if c.snapshot.symbol==quote.symbol)
    draft=prepare_option_preview(contract,instruction='BUY_TO_OPEN',quantity=1,now=clock(),
        valid_until=min(end,clock()+timedelta(seconds=30)))
    evidence()
    report=preview.preview(draft)
    budget,_=evidence()
    expected=sha256(json.dumps(wire_payload(draft,context.account_number,clock(),preview.wire_format),
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if report.get('request_fingerprint')!=expected:raise ValueError('LIVE_PREVIEW_IDENTITY_MISMATCH')
    cost=preview_cost(report,draft)
    if cost>budget['available']:raise ValueError('BUDGET_COST_EXCEEDS_AVAILABLE')
    return dict(binding=context.binding,symbol=symbol,side=side,contract=quote.symbol,
        ask=str(quote.ask),cost=str(cost),expires_at=draft.expires_at.isoformat())
