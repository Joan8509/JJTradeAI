"""Optional Administrator radar companion. Off unless encrypted profile opts in.

No task credentials or secrets are passed as command-line arguments. HTTP and
poller share the same local simulation/market-data client. No Alpaca connection.
"""
from datetime import datetime,timezone
import base64
import json
import os
from pathlib import Path
import threading

from manual_execution import configured_workflow
from manual_trade_service import owner_market_data,read_manual_state
from market_store import DEFAULT_MARKET_DATABASE
from schwab_connection import EncryptedSchwabStore
from telegram_manual import TelegramManualService,TelegramManualStore
from telegram_manual_controls import STATUS,LOCK,poller_lock,preparation_button
from telegram_manual_bot import TelegramManualBot,TelegramCallbackPoller
from telegram_manual_http import LoopbackServer,handler_for
from trade_close_notifications import SaleNotifier,SaleNoticeStore
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
PORT=8184
ENTRY_POLL_SECONDS=.2
ENTRY_LATENCY_REVISION='fresh_signal_priority_v1'


def _status(state,**fields):
    data=dict(state=state,pid=os.getpid(),heartbeat=datetime.now(timezone.utc).isoformat(),
              real_orders_enabled=False,**fields)
    try:
        STATUS.parent.mkdir(parents=True,exist_ok=True)
        temporary=STATUS.with_suffix('.tmp');temporary.write_text(json.dumps(data),encoding='utf-8');temporary.replace(STATUS)
    except OSError:pass


def create_service(profile,*,token,user_id,base_url):
    if profile.get('telegram_manual_enabled') is not True or profile.get('api_product')!='MARKET_DATA_ONLY':
        raise RuntimeError('TELEGRAM_MANUAL_DISABLED')
    def state(symbol):
        today=datetime.now(timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
        return read_manual_state(DEFAULT_MARKET_DATABASE,symbol,today)
    workflow=configured_workflow(profile,ROOT/'exports/trade_review/manual_simulation',
        read_state=state,market_data=owner_market_data())
    from schwab_simulation import practice_policy
    if practice_policy(workflow.engine.policy):
        from manual_alert_entry import read_alert_reference
        workflow.alert_reader=lambda symbol,side,candle:read_alert_reference(
            DEFAULT_MARKET_DATABASE,symbol,side,candle,str(user_id))
    return TelegramManualService(workflow,TelegramManualStore(ROOT/'exports/trade_review/telegram_manual/state.db'),
        token=token,user_id=user_id,base_url=base_url)


class Companion:
    def __init__(self,service,api,*,notifier=None):
        self.service=service;self.api=api;self.stop=threading.Event();self.threads=[]
        self.server=LoopbackServer(('127.0.0.1',PORT),handler_for(service))
        self.poller=TelegramCallbackPoller(TelegramManualBot(service,api));self.poll_ready=False
        self.poll_error_code=None;self.poll_error_operation=None;self.poll_error_at=None;self.poll_retry_after=None
        self.poll_last_success=None
        self.poll_transport_backoff=5
        self.monitor_ready=False;self.monitor_at=None
        self.monitor_wake=threading.Event()
        service.workflow.observation_requested=self.monitor_wake
        self.notifier=notifier;self.notice_state='DISABLED' if notifier is None else 'WAITING'
        service.operational_check=self.ready
        service.direct_operational_check=self.monitor_active
        self.entry_queue=None;self.queue_notifier=None
        self.position_publisher=None
        # Empty by default. Only explicit dashboard plans authorize local entries.
        try:
            from automatic_entry_queue import QueueStore,QueueRunner,QueueNotifier
            from schwab_simulation import ManualPracticePolicy
            if type(service.workflow.engine.policy) is ManualPracticePolicy:
                from queue_position_cards import PositionCardPublisher
                self.position_publisher=PositionCardPublisher(service.workflow)
                self.entry_queue=QueueRunner(service.workflow,QueueStore(),ready=self.monitor_active,service=service)
                self.queue_notifier=QueueNotifier(self.entry_queue.store,service,api)
        except Exception:
            pass  # Queue failure must never disable management of existing positions.

    def ready(self):
        return self.poll_ready and self.monitor_active()

    def monitor_active(self):
        return (self.monitor_ready and self.monitor_at is not None and
                0<=(datetime.now(timezone.utc)-self.monitor_at).total_seconds()<=10)

    def _poll(self):
        try:
            with poller_lock():
                from urllib.request import urlopen
                from telegram_alerts import _tls_context
                with urlopen(self.service.base_url+'health',timeout=10,context=_tls_context()) as response:
                    health=json.load(response)
                if health.get('real_orders_enabled') is not False or health.get('status')!='LOCAL_SIMULATION':
                    raise RuntimeError('HTTPS_ROUTE_NOT_VERIFIED')
                self.poller.bootstrap();self.poll_ready=True
                while not self.stop.is_set():
                    try:self.poller.once()
                    except Exception as error:
                        self.poll_ready=False
                        allowed={'HTTP_400','HTTP_401','HTTP_403','HTTP_409','HTTP_429','HTTP_FAILURE',
                                 'TRANSPORT_FAILURE','API_REJECTED','TELEGRAM_ERROR'}
                        code=getattr(error,'code',None)
                        self.poll_error_code=code if code in allowed else 'UNEXPECTED_FAILURE'
                        operation=getattr(error,'operation',None)
                        self.poll_error_operation=operation if operation in {'getUpdates','getWebhookInfo',
                            'sendMessage','answerCallbackQuery','editMessageText'} else 'UNKNOWN'
                        self.poll_error_at=datetime.now(timezone.utc).isoformat()
                        if (self.poll_error_code=='TRANSPORT_FAILURE' and
                                self.poll_error_operation=='getUpdates' and
                                not getattr(error,'retry_after_seconds',None)):
                            # Only the read-side long poll is retried sooner.
                            # Its durable offset/update claims are unchanged;
                            # message/order outcomes are never resent here.
                            self.poll_retry_after=self.poll_transport_backoff
                            self.poll_transport_backoff=min(60,self.poll_transport_backoff*2)
                        else:self.poll_retry_after=max(15,getattr(error,'retry_after_seconds',None) or 60)
                        if self.stop.wait(self.poll_retry_after):break
                    else:
                        self.poll_ready=True;self.poll_last_success=datetime.now(timezone.utc).isoformat()
                        self.poll_transport_backoff=5
        except Exception:self.poll_ready=False

    def _monitor(self):
        while not self.stop.is_set():
            # Clear before work: a registration during a slow observation must
            # remain signaled and run again without the idle one-second wait.
            self.monitor_wake.clear()
            try:
                if self.service.workflow.pending_orders() or self.service.workflow.positions():
                    self.service.workflow.observe()
                self.monitor_ready=True
            except Exception:self.monitor_ready=False
            self.monitor_at=datetime.now(timezone.utc)
            if self.position_publisher is not None:
                try:self.position_publisher.publish(monitor_ready=self.monitor_ready)
                except Exception:pass  # Display failure cannot disable exits or retry orders.
            if self.stop.is_set():break
            state='READY' if self.ready() else 'MONITOR_BLOCKED' if not self.monitor_ready else 'BOT_NOT_READY'
            _status(state,port=PORT,monitor_ready=self.monitor_ready,sale_notices_state=self.notice_state,
                automatic_entry_revision=ENTRY_LATENCY_REVISION,automatic_entry_poll_ms=int(ENTRY_POLL_SECONDS*1000),
                automatic_entry_lifetime_seconds=10,entry_monitor_wakeup=True,
                preopen_preparation_enabled=bool(self.entry_queue is not None and
                    getattr(self.service.workflow.market_data,'direct_quotes',False) is True),
                stop_loss_pct=str(self.service.workflow.engine.policy.stop_loss_pct),
                poll_error_code=self.poll_error_code,poll_error_at=self.poll_error_at,
                poll_error_operation=self.poll_error_operation,
                poll_retry_after_seconds=self.poll_retry_after,poll_last_success=self.poll_last_success)
            self.monitor_wake.wait(1)

    def _notifications(self):
        # Telegram HTTP never blocks price observation or stop/target management.
        while not self.stop.is_set():
            delay=1
            if self.monitor_ready:
                try:
                    queue_delay=self.queue_notifier.pump() if self.queue_notifier is not None else 0
                    if queue_delay:
                        self.stop.wait(queue_delay);continue
                    result=self.notifier.pump()
                    if result['unconfirmed']:self.notice_state='DELIVERY_UNCONFIRMED'
                    elif result['accepted'] or self.notice_state=='WAITING':self.notice_state='READY'
                    delay=max(1,result['retry_after_seconds'])
                except Exception:
                    self.notice_state='NOTICE_BLOCKED';delay=15
            self.stop.wait(delay)

    def _entries(self):
        while not self.stop.is_set():
            worked=False
            try:worked=self.entry_queue.step() is True
            except Exception:
                try:self.entry_queue.store.heartbeat(self.service.workflow.clock(),'CHECK_REQUIRED')
                except Exception:pass
            self.stop.wait(0 if worked else ENTRY_POLL_SECONDS)

    def start(self):
        try:
            if self.notifier is not None:self.notifier.arm()
        except Exception:
            self.server.server_close();raise
        targets=(self.server.serve_forever,self._poll,self._monitor)
        if self.entry_queue is not None:targets+=(self._entries,)
        if self.notifier is not None:targets+= (self._notifications,)
        for target in targets:
            thread=threading.Thread(target=target,daemon=True);thread.start();self.threads.append(thread)
        return self

    def close(self):
        self.stop.set();self.monitor_wake.set();self.server.shutdown();self.server.server_close();_status('STOPPED')


def start_optional():
    """Invoked ONLY in the already-authorized radar identity, never at import."""
    try:
        profile=EncryptedSchwabStore().load()
        if profile.get('telegram_manual_enabled') is not True:
            return None
        from manual_trade_links import app_url
        from telegram_alerts import connection,_protect,call
        settings=connection()
        if not settings or not str(settings.get('chat_id','')).isdigit():raise ValueError
        token=(os.environ.get('TELEGRAM_BOT_TOKEN','') if settings.get('token_source')=='ENVIRONMENT'
               else _protect(base64.b64decode(settings['protected_token']),decrypt=True).decode())
        base=app_url()
        if not base:raise ValueError
        from urllib.parse import urlsplit,urlunsplit
        parsed=urlsplit(base);base=urlunsplit((parsed.scheme,parsed.netloc,'/telegram/','',''))
        service=create_service(profile,token=token,user_id=int(settings['chat_id']),base_url=base)
        api=lambda method,**payload:call(token,method,**payload)
        notifier=SaleNotifier(service.workflow.engine.ledger,SaleNoticeStore(service.store.path.with_name('sale_notices.db')),
            account_alias=service.workflow.engine.policy.account_alias,user_id=service.user_id,call=api)
        return Companion(service,api,notifier=notifier).start()
    except Exception:
        _status('DISABLED_OR_INCOMPLETE');return None
