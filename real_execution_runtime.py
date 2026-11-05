"""Explicit wiring and independent entry/exit loops for the real module.

Nothing starts on import or when the dashboard mode changes. The application
host must provide current, server-verified readiness and signal/quote adapters.
No boolean from a widget is a readiness source.
"""
from datetime import datetime, timezone
from threading import Event, Lock, Thread
import time

from real_execution_service import RealExecutionService
from real_order_ledger import RealOrderLedger, RealOrderCoordinator
from schwab_connection import SchwabReadOnlyClient
from schwab_order_gateway import SchwabOrderGateway


def connect_live_execution(context, *, quote_contract, entry_ready, signal_current,
                           ledger=None, clock=lambda:datetime.now(timezone.utc), gateway_factory=SchwabOrderGateway,
                           entry_admission=None,exit_session_provider=None,entry_quote_provider=None,entry_cost=None):
    """Wire only this explicit private account; construction never sends an order."""
    ledger=ledger if ledger is not None else RealOrderLedger(clock=clock)
    reader=SchwabReadOnlyClient(context.oauth)
    service=RealExecutionService(binding=context.binding,account_number=context.account_number,
        ledger=ledger,coordinator=None,
        read_order=lambda identity:reader.order(context.account_hash,identity,clock()),
        quote_contract=quote_contract,entry_ready=entry_ready,signal_current=signal_current,clock=clock,
        entry_admission=entry_admission,exit_session_provider=exit_session_provider,entry_quote_provider=entry_quote_provider,entry_cost=entry_cost)
    gateway=gateway_factory(account_hash=context.account_hash,account_binding=context.binding,oauth=context.oauth,
        draft_provider=service.draft_for,commit_guard=service.commit_guard,utcnow=clock)

    def grant(binding,identity,action):
        if binding!=context.binding:return False
        row=next((r for r in ledger.requests(binding) if r['id']==identity),None)
        if row is None:return False
        if action=='CANCEL':return row['broker_id'] is not None
        if action!='SUBMIT':return False
        service.draft_for(row)
        if row['instruction']=='BUY_TO_OPEN':
            key=service._entry_signals.get(identity)
            return (key is not None and entry_ready() is True and signal_current(key) is True
                and service.entry_admission(service.draft_for(row)) is True)
        return row.get('parent_id') is not None

    service.coordinator=RealOrderCoordinator(ledger,gateway,grant)
    return service


class RealExecutionWorker:
    """Two bounded loops; slow GET/cancel observation never holds the entry loop.

    The process supervisor still has to own/restart this worker. A browser tab
    is not a supervisor. This class does not install or change Windows tasks.
    """
    def __init__(self,queue,execution,prepare_entry,*,monotonic=time.monotonic,preparation=None,
                 separate_observation=False,notices=None):
        self.queue=queue;self.execution=execution;self.prepare_entry=prepare_entry
        self._clock=monotonic;self._stop=Event();self._wake=Event();self._mutex=Lock()
        self._threads=[];self._heartbeat={};self._last_errors={};self._turn_seconds={}
        self.preparation=preparation
        self.separate_observation=separate_observation;self.notices=notices
        self.targets=None
        self.external_closes=None

    def start(self):
        with self._mutex:
            if self._threads:raise RuntimeError('LIVE_WORKER_ALREADY_STARTED')
            roles=[('exits',.2 if self.separate_observation else 1.),('entries',.2)]
            if self.separate_observation:roles.append(('orders',1.))
            if self.notices is not None:roles.append(('notices',.5))
            if self.targets is not None:roles.append(('targets',.2))
            if self.external_closes is not None:roles.append(('external_closes',2.))
            if self.preparation is not None:roles.append(('preparation',2.))
            for role,interval in roles:
                thread=Thread(target=self._loop,args=(role,interval),name='JJTrade-real-'+role,daemon=True)
                self._threads.append(thread)
            for thread in self._threads:thread.start()

    def notify_signal(self):self._wake.set()

    def _loop(self,role,interval):
        while not self._stop.is_set():
            started=self._clock()
            error=None
            try:
                if role=='exits':
                    events=self.execution.monitor_positions() if self.separate_observation else self.execution.poll()
                    if any(r.get('state') in ('LIVE_ORDER_READ_UNAVAILABLE','LIVE_EXIT_REQUIRES_REVIEW') for r in events):
                        error='LIVE_MONITOR_REQUIRES_REVIEW'
                elif role=='orders':
                    events=self.execution.observe_orders()
                    if any(r.get('state')=='LIVE_ORDER_READ_UNAVAILABLE' for r in events):error='LIVE_ORDER_MONITOR_REQUIRES_REVIEW'
                elif role=='notices':self.notices.step()
                elif role=='targets':self.targets.step()
                elif role=='external_closes':self.external_closes.step()
                elif role=='preparation':self.preparation.step()
                else:
                    self.queue.step(self.execution.binding,self.execution,self.prepare_entry,monitor=False)
            except Exception:
                error=('LIVE_MONITOR_REQUIRES_REVIEW' if role=='exits' else
                    'LIVE_ORDER_MONITOR_REQUIRES_REVIEW' if role=='orders' else
                    'LIVE_EXECUTION_NOTICE_UNAVAILABLE' if role=='notices' else
                    'LIVE_BROKER_TARGET_UNAVAILABLE' if role=='targets' else
                    'LIVE_EXTERNAL_CLOSE_MONITOR_UNAVAILABLE' if role=='external_closes' else
                    'LIVE_PREPARATION_UNAVAILABLE' if role=='preparation' else 'LIVE_ENTRY_REQUIRES_REVIEW')
            with self._mutex:
                self._heartbeat[role]=self._clock();self._last_errors[role]=error
                self._turn_seconds[role]=self._heartbeat[role]-started
            if role=='entries':
                self._wake.wait(interval);self._wake.clear()
            else:self._stop.wait(max(0.,interval-(self._clock()-started)))

    def status(self):
        with self._mutex:
            now=self._clock()
            return dict(started=bool(self._threads),
                external_closes_current=bool(self.external_closes is None or (not self._stop.is_set() and
                    'external_closes' in self._heartbeat and now-self._heartbeat['external_closes']<5 and
                    self._last_errors.get('external_closes') is None)),
                orders_current=bool(not self.separate_observation or (not self._stop.is_set() and
                    'orders' in self._heartbeat and now-self._heartbeat['orders']<3 and self._last_errors.get('orders') is None)),
                targets_current=bool(self.targets is None or (not self._stop.is_set() and
                    'targets' in self._heartbeat and now-self._heartbeat['targets']<3 and self._last_errors.get('targets') is None)),
                notices_current=bool(self.notices is None or (not self._stop.is_set() and
                    'notices' in self._heartbeat and now-self._heartbeat['notices']<3 and self._last_errors.get('notices') is None)),
                exits_current=bool(not self._stop.is_set() and 'exits' in self._heartbeat and now-self._heartbeat['exits']<3 and
                    self._last_errors.get('exits') is None),
                entries_current=bool(not self._stop.is_set() and 'entries' in self._heartbeat and now-self._heartbeat['entries']<3 and
                    self._last_errors.get('entries') is None),
                errors=dict(self._last_errors),
                heartbeat_age_seconds={role:round(now-stamp,3) for role,stamp in self._heartbeat.items()},
                turn_seconds={role:round(value,3) for role,value in self._turn_seconds.items()})

    def shutdown(self):
        """Host shutdown only; pausing entries uses queue.pause instead."""
        self._stop.set();self._wake.set()
        for thread in self._threads:thread.join(timeout=.25)


class RealLiveRuntime:
    """Host-owned runtime handle; the dashboard only arms/pauses its queue.

    configuration_ready must verify the connected account/protocol/cost/price
    configuration on the server. session_provider must use the official stored
    calendar, not a weekday or fixed-hour approximation.
    """
    def __init__(self, *, queue, execution, prepare_entry, configuration_ready, session_provider):
        self.queue=queue;self.execution=execution;self.binding=execution.binding
        self.configuration_ready=configuration_ready;self.session_provider=session_provider
        self.worker=RealExecutionWorker(queue,execution,prepare_entry)

    def start(self):
        if self.configuration_ready() is not True:raise RuntimeError('LIVE_EXECUTOR_NOT_VERIFIED')
        self.worker.start()

    def can_arm(self):
        return self.configuration_ready() is True and self.worker.status()['exits_current']

    def arm(self,rows,*,repeat_new_signals=False,first_entry_only=True):
        start,end=self.session_provider()
        return self.queue.arm(self.binding,rows,session_open=start,session_close=end,execution_ready=self.can_arm,
            repeat_new_signals=repeat_new_signals,first_entry_only=first_entry_only)

    def pause(self):return self.queue.pause(self.binding)
