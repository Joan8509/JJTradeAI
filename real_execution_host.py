"""Owner-only supervised REAL host. No selected account or armed queue: no orders.

Started by the existing Password-logon interface task, separate from Streamlit,
collector and radar. A cross-process singleton prevents a second real executor.
Private configuration/status/diagnostics use DPAPI; errors never print bodies.
"""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import os,time
from threading import Thread

from schwab_connection import aware,SchwabReadOnlyClient
from real_live_storage import RealEncryptedStore as EncryptedSchwabStore
from real_account_readonly import owner_account_client,account_rows,AccountPreviewContext
from real_live_control import RealControlStore,RealHostStatusStore,control_document,ROOT
from real_automatic_queue import RealAutomaticQueue
from real_order_ledger import RealOrderLedger
from real_execution_runtime import connect_live_execution,RealExecutionWorker
from real_live_capital import RealCapitalGuard
from real_live_opportunities import RealOpportunities
from schwab_preview_client import SchwabPreviewClient
from bollinger_expansion import MINIMUM_BAND_EXPANSION_PCT


class RealDiagnosticStore(EncryptedSchwabStore):
    def __init__(self,*,error=False):
        self.path=ROOT/'exports/private_runtime'/('real_preview_error.dpapi' if error else 'real_preview_diagnostic.dpapi')


def owner_real_market_data():
    from manual_trade_service import owner_market_data
    market=owner_market_data()
    # Same encrypted market vault; native SID and bounded locks only in REAL.
    market.client.oauth.store=EncryptedSchwabStore()
    return market


class RealExecutionHost:
    def __init__(self,*,clock=lambda:datetime.now(timezone.utc),diagnostic_only=False):
        self.clock=clock;self.binding=None;self.capital=None;self.worker=None;self.context=None
        self.market=None;self.queue=RealAutomaticQueue();self.ledger=RealOrderLedger()
        self.last_refresh=0.;self.last_protocol=0.;self.protocol=None
        self._refresh_thread=None
        self._protocol_thread=None
        self._market_auth_thread=None;self._last_market_auth=0.;self._market_auth=None
        self.diagnostic_only=diagnostic_only;self.opportunities={}
        self.entry_failures={}
        self.entry_provider=None
        self.protocol_error=None
        self.deployment_hold=True
        self.diagnostic_shape=None

    def _status(self,blockers):
        worker=self.worker.status() if self.worker else dict(started=False,exits_current=False,entries_current=False)
        account_ready=self.capital.account_ready() if self.capital else False
        if not worker['exits_current']:blockers=list(blockers)+['LIVE_EXIT_MONITOR_NOT_CURRENT']
        if worker.get('orders_current') is False:blockers=list(blockers)+['LIVE_ORDER_MONITOR_NOT_CURRENT']
        if worker.get('external_closes_current') is False:blockers=list(blockers)+['LIVE_EXTERNAL_CLOSE_MONITOR_NOT_CURRENT']
        if self.deployment_hold:blockers=list(blockers)+['LIVE_DEPLOYMENT_VALIDATION_IN_PROGRESS']
        market_current=self._market_authorization_current()
        if not market_current:blockers=list(blockers)+[self._market_authorization_blocker()]
        external_hold=False
        if self.worker:
            rows=self.worker.execution.ledger.requests(self.binding)
            external_hold=isinstance(rows,list) and any(r.get('external_close_hold') for r in rows)
        if external_hold:blockers=list(blockers)+['LIVE_EXTERNAL_CLOSE_REQUIRES_RECONCILIATION']
        ready=bool(not self.diagnostic_only and not self.deployment_hold and self.protocol and account_ready and
            market_current and worker['exits_current'] and worker['entries_current'] and worker.get('orders_current',True)
            and worker.get('external_closes_current',True) and not external_hold)
        value=dict(purpose='REAL_HOST_STATUS_V1',checked_at=aware(self.clock()).isoformat(),pid=os.getpid(),
            binding=self.binding,ready_to_arm=ready,account_current=account_ready,protocol_verified=bool(self.protocol),
            blockers=sorted(set(blockers)),worker=worker,orders_enabled_for_armed_queue_only=True)
        value['opportunities']=dict(self.opportunities)
        value['option_market_authorization_current']=market_current
        value['entry_failures']=dict(self.entry_failures)
        if self.entry_provider is not None:
            value['entry_preparation_timing']=self.entry_provider.timing_status()
            value['entry_attempts']=self.entry_provider.attempt_status()
        value['entry_attempt_diagnostics_revision']=1
        if self.worker:
            observations=getattr(self.worker.execution,'exit_observations',None)
            if isinstance(observations,dict):value['exit_observations']=dict(observations)
            if self.worker.notices is not None:value['execution_notices']=self.worker.notices.status()
            if self.worker.targets is not None:
                value['broker_target_orders']=self.worker.targets.status()
                value['broker_profit_targets_enabled']=True
            external=getattr(self.worker,'external_closes',None)
            if external is not None:
                value['external_manual_closes']=external.status()
                value['external_manual_close_detection_enabled']=True
        value['minimum_band_expansion_pct']=MINIMUM_BAND_EXPANSION_PCT
        value['connection_continuity_revision']=1
        if self.capital:
            try:value['budget']=self.capital.budget_snapshot()
            except Exception:value['budget']=None
        if self.worker and self.worker.preparation is not None:
            value['entry_preparation']=self.worker.preparation.status()
        value['protocol_error']=self.protocol_error
        value['diagnostic_shape']=self.diagnostic_shape
        if self.capital and self.capital.account:
            value['positions_reported']=isinstance(self.capital.account.get('positions'),list)
        store=RealHostStatusStore()
        with store.locked():store.save(value)

    def _market_authorization_current(self):
        value=self._market_auth
        return bool(value and value['state']=='CURRENT' and 0<=time.monotonic()-value['checked']<45)

    def _market_authorization_blocker(self):
        value=self._market_auth
        return 'LIVE_OPTION_DATA_REAUTHORIZE' if value and value['state']=='REAUTHORIZE' else 'LIVE_OPTION_DATA_AUTH_NOT_CURRENT'

    def _refresh_market_authorization(self):
        # OAuth access normally reads the persisted token; refresh happens ahead
        # of expiry on this background thread, never while holding the host loop.
        # No quotes, preview or order is requested, and no token is published.
        try:
            self.market.client.oauth.access(aware(self.clock()))
            state='CURRENT'
        except Exception as error:
            state='REAUTHORIZE' if getattr(error,'code',None) in (
                'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED') else 'UNAVAILABLE'
        self._market_auth=dict(state=state,checked=time.monotonic())

    def _connect(self,config):
        selected=config['account'];client=owner_account_client()
        from hashlib import sha256
        fingerprint=sha256(('JJTRADE_ACCOUNT_PREPARATION_V1\0'+selected['account_number']+'\0'+selected['account_hash']).encode()).hexdigest()
        if fingerprint!=selected['binding']:raise ValueError('LIVE_ACCOUNT_BINDING_INVALID')
        pairs=account_rows(client.accounts(aware(self.clock())))
        if (selected['account_number'],selected['account_hash']) not in pairs:raise ValueError('LIVE_SELECTED_ACCOUNT_NOT_LINKED')
        context=AccountPreviewContext(selected['binding'],selected['account_number'],selected['account_hash'],client.oauth)
        market=owner_real_market_data()
        proof=config.get('protocol') or {}
        wire=proof.get('wire','PREVIEW_ORDER_STRATEGY_V1')
        guard=RealCapitalGuard(context,client,SchwabPreviewClient(context,wire_format=wire),self.ledger,clock=self.clock)
        guard.preview.prepare_transport()
        provider=RealOpportunities(market,guard,clock=self.clock)
        self.entry_provider=provider
        execution=connect_live_execution(context,quote_contract=provider.quote_contract,
            entry_ready=lambda:not self.deployment_hold and self._market_authorization_current() and guard.entry_ready(),
            signal_current=provider.signal_current,entry_admission=guard.permits,ledger=self.ledger,clock=self.clock,
            exit_session_provider=__import__('real_live_control').next_official_session,entry_quote_provider=provider.entry_contract,
            entry_cost=guard.estimated_cost)
        execution.exit_admission=guard.exit_permitted
        execution.coordinator.gateway.prepare_transport()
        self.binding=context.binding;self.context=context;self.capital=guard;self.market=market
        self.protocol=(proof.get('binding')==self.binding and proof.get('source')=='SCHWAB_PREVIEW_ENDPOINT'
            and proof.get('wire') in ('PREVIEW_ORDER_STRATEGY_V1','ORDER_REQUEST_V1'))
        def entry(row):
            if (self.diagnostic_only or self.deployment_hold or not self.protocol or
                not self._market_authorization_current() or not guard.account_ready()):return None
            try:
                result=provider(row)
                self.opportunities[row['symbol']]='SIGNAL_AND_CONTRACT_PREPARED' if result else 'WAITING_FOR_VALID_SIGNAL'
                return result
            except Exception as error:
                safe={'NO_CURRENT_SIGNAL','SIGNAL_ENTRY_WINDOW_EXPIRED','NO_ELIGIBLE_EXPIRATION_OR_RANGE',
                    'LIVE_PREVIEW_NOT_ACCEPTED','LIVE_PREVIEW_COSTS_INCOMPLETE','LIVE_SETTLED_CASH_INSUFFICIENT',
                    'LIVE_COMPANY_ALREADY_HELD','COLLECTOR_NOT_CURRENT','TRADE_NOT_CURRENT','RATE_LIMITED'}
                safe.add('PREVIEW_RESPONSE_NOT_VERIFIED')
                self.opportunities[row['symbol']]=str(error) if str(error) in safe else 'LIVE_OPPORTUNITY_UNAVAILABLE'
                if self.opportunities[row['symbol']] not in ('NO_CURRENT_SIGNAL','TRADE_NOT_CURRENT','SIGNAL_ENTRY_WINDOW_EXPIRED'):
                    self.entry_failures[row['symbol']]=dict(code=self.opportunities[row['symbol']],
                        checked_at=aware(self.clock()).isoformat())
                raise
        from real_live_commands import CommandExecution
        from real_entry_preparation import RealEntryPreparation
        preparation=RealEntryPreparation(self.queue,self.binding,market,clock=self.clock)
        from real_trade_notices import RealTradeNotices
        notices=RealTradeNotices(self.binding,self.ledger,clock=self.clock)
        notices.initialize()
        self.worker=RealExecutionWorker(self.queue,CommandExecution(execution),entry,preparation=preparation,
            separate_observation=True,notices=notices)
        from real_broker_target import BrokerProfitTargets
        target_preview=SchwabPreviewClient(context,wire_format=wire)
        target_preview.prepare_transport()
        self.worker.targets=BrokerProfitTargets(execution,target_preview,clock=self.clock)
        notices.target_status_provider=self.worker.targets.status
        from real_external_closes import ExternalManualCloses
        external_reader=SchwabReadOnlyClient(context.oauth)
        self.worker.external_closes=ExternalManualCloses(execution,self.queue,
            lambda start,end:external_reader.orders(context.account_hash,start,end,aware(self.clock())),clock=self.clock)
        notices.external_status_provider=self.worker.external_closes.status
        # Monitoring starts even when entry funding/protocol checks are blocked.
        self.worker.start();self.last_refresh=0.;self.last_protocol=0.

    def _verify_protocol(self):
        """Diagnostic preview of an observed historical price; never a live draft.

        Does not require/fabricate a current strategy signal or change original
        quote timestamps. May be rejected for funds/session; a normalized broker
        response still proves the input/output wire format, not a buy permission.
        """
        market=self.market.get_catalog_chain('AAPL','CALL',aware(self.clock()))
        now=aware(self.clock())
        from zoneinfo import ZoneInfo
        today=now.astimezone(ZoneInfo('America/New_York')).date()
        candidates=[c for c in market.chain.contracts if c.snapshot.expiration>=today]
        if not candidates:raise ValueError('LIVE_DIAGNOSTIC_CONTRACT_UNAVAILABLE')
        contract=min(candidates,key=lambda c:(c.snapshot.expiration,abs(c.snapshot.strike-market.chain.underlying_price)))
        contract.validate_identity();q=contract.snapshot
        # This is a diagnostic request lifetime, not a quote freshness claim.
        from schwab_option_order_request import OptionLimitRequest
        draft=OptionLimitRequest(q.symbol,'BUY_TO_OPEN',1,Decimal(str(q.ask)),now,now+timedelta(seconds=60),
            'DIAGNOSTIC_PREVIEW_ONLY')
        def observe(payload):
            strategy=payload.get('orderStrategy') or {};legs=strategy.get('orderLegs') or [{}]
            self.diagnostic_shape=dict(top_keys=sorted(payload),strategy_keys=sorted(strategy),
                leg_keys=sorted(legs[0]),account_matches=str(strategy.get('accountNumber',''))==self.context.account_number,
                validation_counts={k:len(v) if isinstance(v,list) else type(v).__name__ for k,v in (payload.get('orderValidationResult') or {}).items()},
                enums={k:strategy.get(k) for k in ('session','duration','orderType','orderStrategyType','strategy','advancedOrderType')},
                cost_categories=sorted(payload.get('commissionAndFee') or {}))
            store=RealDiagnosticStore()
            with store.locked():store.save(dict(purpose='REAL_DIAGNOSTIC_PREVIEW_V1',binding=self.binding,
                checked_at=aware(self.clock()).isoformat(),observed_quote_at=aware(q.quote_timestamp).isoformat(),
                diagnostic_only=True,response=payload))
        def observe_error(status,payload):
            store=RealDiagnosticStore(error=True)
            with store.locked():store.save(dict(purpose='REAL_DIAGNOSTIC_PREVIEW_V1',binding=self.binding,
                checked_at=aware(self.clock()).isoformat(),diagnostic_only=True,http_status=status,response=payload))
        chosen='PREVIEW_ORDER_STRATEGY_V1'
        try:report=SchwabPreviewClient(self.context,response_observer=observe,error_observer=observe_error).preview(draft)
        except Exception as error:
            if getattr(error,'http_status',None)!=400:raise
            # Diagnostic preview endpoint ONLY. Verify the documented order
            # request variant against the broker; never try an order endpoint.
            chosen='ORDER_REQUEST_V1'
            report=SchwabPreviewClient(self.context,response_observer=observe,error_observer=observe_error,
                wire_format=chosen).preview(draft)
        store=RealControlStore()
        with store.locked():
            value=control_document(store)
            if (value.get('account') or {}).get('binding')!=self.binding:raise ValueError('LIVE_ACCOUNT_CHANGED')
            value['protocol']=dict(binding=self.binding,verified_at=aware(self.clock()).isoformat(),
                source=report['source'],wire=chosen,diagnostic_state=report['state'])
            store.save(value)
        self.capital.preview.wire_format=chosen
        if self.worker and self.worker.targets is not None:
            self.worker.targets.preview.wire_format=chosen
        self.protocol=True

    def _refresh_protocol(self):
        try:
            self._verify_protocol();self.protocol_error=None
        except Exception as error:
            self.protocol_error=dict(code=getattr(error,'code','PREVIEW_VERIFICATION_UNAVAILABLE'),
                http_status=getattr(error,'http_status',None))

    def tick(self):
        blockers=[];store=RealControlStore()
        with store.locked():config=control_document(store)
        selected=config.get('account')
        self.deployment_hold=(config.get('deployment_hold',True) is not False or config.get('execution_authorized') is not True or
            bool(self.binding and (selected or {}).get('binding')!=self.binding))
        if not selected or config.get('execution_authorized') is not True:
            self._status(['LIVE_EXPLICIT_ACCOUNT_SELECTION_REQUIRED']);return
        if self.binding and self.binding!=selected['binding']:
            # Registration refuses account changes with exposure. The host also
            # refuses to abandon an existing execution instance in this process.
            self._status(['LIVE_HOST_ACCOUNT_RESTART_REQUIRED']);return
        if self.worker is None:self._connect(config)
        if (time.monotonic()-self._last_market_auth>=15 and
            (self._market_auth_thread is None or not self._market_auth_thread.is_alive())):
            self._last_market_auth=time.monotonic()
            self._market_auth_thread=Thread(target=self._refresh_market_authorization,
                name='JJTrade-real-option-authorization',daemon=True)
            self._market_auth_thread.start()
        if (time.monotonic()-self.last_refresh>=15 and
            (self._refresh_thread is None or not self._refresh_thread.is_alive())):
            # Balance/order GETs may each wait for a broker timeout. They must
            # not prevent fresh worker/status publication. One refresh at most;
            # admission still requires the guard's actual current evidence.
            self.last_refresh=time.monotonic()
            self._refresh_thread=Thread(target=self.capital.refresh,name='JJTrade-real-account',daemon=True)
            self._refresh_thread.start()
        if not self.capital.account_ready():blockers.append(self.capital.blocker or 'LIVE_ACCOUNT_NOT_CURRENT')
        if (not self.protocol and time.monotonic()-self.last_protocol>=60 and
                (self._protocol_thread is None or not self._protocol_thread.is_alive())):
            self.last_protocol=time.monotonic()
            self._protocol_thread=Thread(target=self._refresh_protocol,name='JJTrade-real-protocol',daemon=True)
            self._protocol_thread.start()
        if not self.protocol:blockers.append('LIVE_PREVIEW_PROTOCOL_NOT_VERIFIED')
        self._status(blockers)


def main():
    import msvcrt
    private=ROOT/'exports/private_runtime'
    # Same DPAPI identity required by the credentials and journals.
    RealControlStore._owner()
    with (private/'real_host.singleton.lock').open('a+b') as handle:
        handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
        try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return 0
        host=RealExecutionHost()
        while True:
            try:host.tick()
            except Exception:
                try:host._status(['LIVE_HOST_REQUIRES_REVIEW'])
                except Exception:pass
            time.sleep(1)


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit(2) from None
