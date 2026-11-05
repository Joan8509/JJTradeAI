"""Bounded pre-opening metadata preparation, with no order/preview interface."""
from datetime import datetime, timedelta, timezone
from threading import Lock

from schwab_connection import aware


class RealEntryPreparation:
    def __init__(self, queue, binding, market, *, clock=lambda:datetime.now(timezone.utc)):
        self.queue=queue;self.binding=binding;self.market=market;self.clock=clock
        self._cursor=0;self._lock=Lock();self._status=dict(state='WAITING_FOR_ARMED_RADAR',prepared=0)

    def status(self):
        with self._lock:return dict(self._status)

    def step(self):
        plan=self.queue.read(self.binding)
        now=aware(self.clock())
        if not plan or plan.get('paused') or plan.get('entry_owner') or plan.get('entry_consumed'):
            return
        start=aware(datetime.fromisoformat(plan['session_open']))
        # Finish background starts before opening, keeping the foreground free.
        # Every purchase still requires current quotes and the current strategy.
        if not start-timedelta(minutes=5)<=now<start-timedelta(seconds=20):return
        jobs=[(r['symbol'],side) for r in plan['rows'] if r['state']=='ARMED' for side in ('CALL','PUT')]
        if not jobs:return
        symbol,side=jobs[self._cursor%len(jobs)];self._cursor+=1
        try:
            self.market.prepare_calendar(symbol,side,now)
        except Exception:
            # Shared market client preserves provider cooldown/Retry-After.
            # No raw error, account, token or broker body is exposed here.
            with self._lock:self._status.update(state='PREPARATION_UNAVAILABLE')
            return
        with self._lock:
            self._status.update(state='CALENDAR_PREPARED',prepared=self._status['prepared']+1,
                symbol=symbol,side=side,checked_at=aware(self.clock()).isoformat())
