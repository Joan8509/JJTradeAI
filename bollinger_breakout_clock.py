"""No network or waits: bound opportunity age from its first observed exit."""
from datetime import datetime, timedelta

BREAKOUT_WINDOW_SECONDS = 30


def observe_breakout(firsts, price, upper, lower, stamp, *, allow_new=True):
    """Never renew a side's first exit after retraction/reference refresh."""
    side = 'SUPERIOR' if price > upper else 'INFERIOR' if price < lower else None
    if side is None:
        return None
    if side not in firsts and not allow_new:
        return None  # Reconnection cannot invent the missing first exit.
    firsts.setdefault(side, stamp.isoformat())
    first = datetime.fromisoformat(firsts[side])
    deadline = first + timedelta(seconds=BREAKOUT_WINDOW_SECONDS)
    return dict(side=side, first_at=first.isoformat(), deadline=deadline.isoformat(),
                age_seconds=(stamp-first).total_seconds(),
                current=first <= stamp < deadline)


def breakout_deadline(signal, now):
    """Optional legacy evidence; new stream signals always supply both fields."""
    # First-cross timestamps remain audit evidence. New signals use the
    # first COMPLETE strategy's durable deadline, without waiting for it.
    if 'first_strategy_at' in signal or 'strategy_deadline' in signal:
        try:
            first = datetime.fromisoformat(signal['first_strategy_at'])
            deadline = datetime.fromisoformat(signal['strategy_deadline'])
            crossing = datetime.fromisoformat(signal['first_breakout_at'])
            crossing_end = datetime.fromisoformat(signal['breakout_deadline'])
            candle = datetime.fromisoformat(signal['candle'])
            if (any(t.tzinfo is None for t in (first, deadline, crossing, crossing_end, candle, now))
                    or deadline != first+timedelta(seconds=BREAKOUT_WINDOW_SECONDS)
                    or crossing_end != crossing+timedelta(seconds=BREAKOUT_WINDOW_SECONDS)
                    or not candle <= crossing <= first < candle+timedelta(minutes=15)
                    or not first <= now < deadline):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise ValueError('SIGNAL_ENTRY_WINDOW_EXPIRED') from None
        return deadline
    first = signal.get('first_breakout_at')
    deadline = signal.get('breakout_deadline')
    if first is None and deadline is None:
        return None
    try:
        first = datetime.fromisoformat(first)
        deadline = datetime.fromisoformat(deadline)
        candle = datetime.fromisoformat(signal['candle'])
        if (first.tzinfo is None or deadline.tzinfo is None or candle.tzinfo is None
                or deadline != first+timedelta(seconds=BREAKOUT_WINDOW_SECONDS)
                or not candle <= first < candle+timedelta(minutes=15)
                or not first <= now < deadline):
            raise ValueError
    except (KeyError,ValueError,TypeError):
        raise ValueError('SIGNAL_ENTRY_WINDOW_EXPIRED') from None
    return deadline
