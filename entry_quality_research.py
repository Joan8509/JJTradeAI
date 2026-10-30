"""Pure, observation-only entry diagnostics; no order or notification authority.

Band expansion and BandWidth measure different things. Historical references
must be from prior dates, the same symbol and clock slot, and already known.
This module is deliberately not imported by the detector or execution path.
"""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

AUTHORITY = 'OBSERVATION_ONLY_NO_ORDER_NO_NOTICE_AUTHORITY'
POLICIES = ('BASELINE', 'WIDTH_P20', 'WIDTH_P40', 'EXPOSURE_1',
            'WIDTH_P20_EXPOSURE_1', 'EARLY_300', 'WIDTH_P20_EARLY_300')


def positive(value):
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError('QUALITY_INVALID_POSITIVE_VALUE')
    return number


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('QUALITY_TIMEZONE_REQUIRED')
    return value


@dataclass(frozen=True)
class WidthSample:
    symbol: str
    slot: str
    session_day: str
    available_at: datetime
    bandwidth_pct: float


def reference_widths(samples, *, symbol, slot, session_day, now, minimum=10, maximum=20):
    aware(now)
    if minimum < 1 or maximum < minimum:
        raise ValueError('QUALITY_INVALID_SAMPLE_LIMITS')
    by_day = {}
    for sample in samples:
        aware(sample.available_at)
        positive(sample.bandwidth_pct)
        if (sample.symbol != symbol or sample.slot != slot or
                sample.session_day >= session_day or sample.available_at > now):
            continue
        if sample.session_day in by_day:
            raise ValueError('QUALITY_DUPLICATE_REFERENCE_DAY')
        by_day[sample.session_day] = sample.bandwidth_pct
    selected = [by_day[d] for d in sorted(by_day)[-maximum:]]
    if len(selected) < minimum:
        return dict(state='INSUFFICIENT_REFERENCE', count=len(selected), p20=None, p40=None)
    ordered = sorted(selected)
    quantile = lambda fraction: ordered[int((len(ordered)-1)*fraction)]
    return dict(state='AVAILABLE', count=len(selected), p20=quantile(.2), p40=quantile(.4))


def observe(*, side, price, upper, lower, middle, candle, at, reference):
    price, upper, lower, middle = map(positive, (price, upper, lower, middle))
    aware(at); aware(candle)
    if side not in ('SUPERIOR', 'INFERIOR') or not lower < middle < upper:
        raise ValueError('QUALITY_INVALID_GEOMETRY')
    age = (at-candle).total_seconds()
    if not 0 <= age < 900:
        raise ValueError('QUALITY_OUTSIDE_CANDLE')
    distance = price-upper if side == 'SUPERIOR' else lower-price
    if distance <= 0:
        raise ValueError('QUALITY_NOT_A_BREAKOUT')
    width = upper-lower
    return dict(authority=AUTHORITY, bandwidth_pct=100*width/middle,
                exposure_pct_width=100*distance/width, candle_age_seconds=age,
                reference=dict(reference), delay_added_seconds=0)


def compare_policies(observation):
    if observation.get('authority') != AUTHORITY:
        raise ValueError('QUALITY_OBSERVATION_REQUIRED')
    reference = observation['reference']
    available = reference['state'] == 'AVAILABLE'
    width20 = observation['bandwidth_pct'] >= reference['p20'] if available else None
    width40 = observation['bandwidth_pct'] >= reference['p40'] if available else None
    exposure = observation['exposure_pct_width'] >= 1
    early = observation['candle_age_seconds'] <= 300
    # Unknown references are explicit unknowns, never inferred as valid.
    combine = lambda gate, other: None if gate is None else gate and other
    return dict(BASELINE=True, WIDTH_P20=width20, WIDTH_P40=width40,
                EXPOSURE_1=exposure, WIDTH_P20_EXPOSURE_1=combine(width20, exposure),
                EARLY_300=early, WIDTH_P20_EARLY_300=combine(width20, early))


def spread_observation(*, bid, ask, stop_pct, target_pct):
    bid, ask, stop = map(positive, (bid, ask, stop_pct))
    target = None if target_pct is None else positive(target_pct)
    if ask < bid or stop >= 100:
        raise ValueError('QUALITY_INVALID_SPREAD_OR_STOP')
    spread_pct = 100*(ask-bid)/ask
    return dict(authority=AUTHORITY, spread_dollars=ask-bid,
                spread_pct_ask=spread_pct, stop_room_pct=stop-spread_pct,
                spread_to_target_ratio=spread_pct/target if target is not None else None,
                stop_consumed_by_spread=spread_pct >= stop-1e-9)


def execution_observation(tick, quote, *, stop_pct, target_pct, dispatched_at, first_signal_at):
    """Called only by the optional worker AFTER dispatch and monitor wakeup.

    Snapshot-only: never loads history, queries a provider, or changes an order.
    Keeping the exact initial quote/geometry fixes gaps in later trade studies.
    """
    aware(dispatched_at)
    source = aware(datetime.fromisoformat(tick['source_timestamp']))
    first = aware(datetime.fromisoformat(first_signal_at))
    if not first <= source <= dispatched_at:
        raise ValueError('QUALITY_INVALID_SOURCE_ORDER')
    qtime = aware(quote.quote_timestamp)
    if qtime > dispatched_at:
        raise ValueError('QUALITY_FUTURE_QUOTE')
    geometry = tick.get('geometry')
    result = dict(authority=AUTHORITY, schema=1, source_at=source.isoformat(),
                  first_signal_at=first.isoformat(), dispatched_at=dispatched_at.isoformat(),
                  first_signal_to_order_seconds=(dispatched_at-first).total_seconds(),
                  selected_bid=positive(quote.bid), selected_ask=positive(quote.ask),
                  selected_bid_size=int(quote.bid_size), selected_ask_size=int(quote.ask_size),
                  selected_quote_at=qtime.isoformat(), selected_quote_age_seconds=(dispatched_at-qtime).total_seconds(),
                  spread=spread_observation(bid=quote.bid,ask=quote.ask,stop_pct=stop_pct,target_pct=target_pct),
                  strategy_version=tick.get('version'), reference_scope=tick.get('reference_scope'),
                  volatility_reference_state='NOT_PRELOADED',
                  entry_gate_enabled=False)
    if geometry:
        result['geometry']={name:float(geometry[name]) for name in (
            'upper','lower','mid','previous_upper','previous_lower','previous_mid','price','opening')}
        result['signal_quality']=observe(side=tick['signal']['side'],price=geometry['price'],
            upper=geometry['upper'],lower=geometry['lower'],middle=geometry['mid'],
            candle=datetime.fromisoformat(tick['signal']['candle']),at=source,
            reference=dict(state='NOT_PRELOADED',count=0,p20=None,p40=None))
    else:
        result['signal_quality']=None
    return result
