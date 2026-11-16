"""Bounded session metadata preparation, with no order/preview interface."""
from datetime import datetime, timedelta, timezone
from threading import Lock

from schwab_connection import aware


class RealEntryPreparation:
    def __init__(self, queue, binding, market, *, clock=lambda:datetime.now(timezone.utc),authorization_current=lambda:True):
        self.queue=queue;self.binding=binding;self.market=market;self.clock=clock
        self.authorization_current=authorization_current
        self._retry_after={}
        self._cursor=0;self._lock=Lock();self._status=dict(state='WAITING_FOR_ARMED_RADAR',prepared=0,revision=3,lead_minutes=30)

    def status(self):
        with self._lock:return dict(self._status)

    def step(self):
        plan=self.queue.read(self.binding)
        now=aware(self.clock())
        if not plan or plan.get('paused') or plan.get('entry_owner') or plan.get('entry_consumed'):
            with self._lock:self._status.update(state='WAITING_FOR_ARMED_RADAR',ready_count=0,selected_count=0)
            return
        start=aware(datetime.fromisoformat(plan['session_open']))
        end=aware(datetime.fromisoformat(plan['session_close']))
        if not start<end or not start-timedelta(minutes=30)<=now<end:
            with self._lock:self._status.update(state='OUTSIDE_PREPARATION_SESSION',ready_count=0)
            return
        jobs=list(dict.fromkeys((r['symbol'],side) for r in plan['rows'] if r['state']=='ARMED' for side in ('CALL','PUT')))
        if not jobs:
            with self._lock:self._status.update(state='WAITING_FOR_ARMED_RADAR',ready_count=0,selected_count=0)
            return
        try:authorized=self.authorization_current() is True
        except Exception:authorized=False
        if not authorized:
            with self._lock:self._status.update(state='WAITING_FOR_DATA_AUTHORIZATION',ready_count=0,selected_count=len(jobs))
            return
        # Refresh metadata before its existing five-minute lifetime expires.
        # Missing/old catalogs come first; no HTTP, preview or order on entry's thread.
        rotated=jobs[self._cursor%len(jobs):]+jobs[:self._cursor%len(jobs)]
        states={job:self.market.calendar_preparation_state(*job,now) for job in rotated}
        due_all=[job for job in rotated if states[job]['refresh_due']]
        self._retry_after={job:at for job,at in self._retry_after.items() if job in states and now<at}
        due=[job for job in due_all if job not in self._retry_after]
        with self._lock:self._status.update(selected_count=len(jobs),
            ready_count=sum(state['current'] for state in states.values()),checked_at=now.isoformat())
        if not due:
            with self._lock:self._status['state']='WAITING_FOR_PREPARATION_RETRY' if due_all else 'CALENDARS_CURRENT'
            return
        # Cold catalogs first; rotation breaks ties and lets another job proceed
        # after an instrument-specific failure. Provider backoff remains shared.
        symbol,side=min(due,key=lambda job:(0 if states[job]['age_seconds'] is None else 1,
            -(states[job]['age_seconds'] or 0)))
        self._cursor=(jobs.index((symbol,side))+1)%len(jobs)
        try:
            self.market.prepare_calendar(symbol,side,now,refresh_after=timedelta(minutes=3))
        except Exception as error:
            if str(error)=='BACKGROUND_REQUEST_DEFERRED':
                with self._lock:self._status.update(state='YIELDED_TO_LIVE_REQUEST')
                return
            # Shared market client preserves provider cooldown/Retry-After.
            # No raw error, account, token or broker body is exposed here.
            self._retry_after[(symbol,side)]=aware(self.clock())+timedelta(seconds=15)
            with self._lock:self._status.update(state='PREPARATION_UNAVAILABLE')
            return
        with self._lock:
            self._status.update(state='CALENDAR_PREPARED',prepared=self._status['prepared']+1,
                symbol=symbol,side=side,checked_at=aware(self.clock()).isoformat())
