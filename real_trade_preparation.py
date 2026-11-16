"""Encrypted real-mode drafts and read-only shadow tickets. NO execution adapter."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import json,re,secrets

from schwab_connection import EncryptedSchwabStore,SchwabError,aware

ROOT=Path(__file__).resolve().parent
TARGETS=('10','20','35','100','MANUAL')
PURPOSE='REAL_PREPARATION_ONLY_V1'


class PreparationError(ValueError):pass


class RealPreparationStore(EncryptedSchwabStore):
    def __init__(self):self.path=ROOT/'exports/private_runtime/real_preparation.dpapi'


def watched_symbols():
    return tuple(json.loads((ROOT/'config/watchlist.json').read_text(encoding='utf-8'))['symbols'])


def normalize_rows(rows,universe=None):
    universe=watched_symbols() if universe is None else universe
    if not isinstance(rows,list) or not rows or len(rows)>len(universe):raise PreparationError('INVALID_SELECTION')
    output=[];seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'symbol','quantity','target'}:raise PreparationError('INVALID_SELECTION')
        symbol=row['symbol'];quantity=row['quantity'];target=row['target']
        if symbol not in universe or symbol in seen:raise PreparationError('INVALID_SELECTION')
        if type(quantity) is not int or quantity<=0:raise PreparationError('QUANTITY_REQUIRED')
        if not isinstance(target,str) or target not in TARGETS:raise PreparationError('TARGET_REQUIRED')
        seen.add(symbol);output.append(dict(symbol=symbol,quantity=quantity,target=target))
    return output


def _binding(value):
    if not isinstance(value,str) or re.fullmatch(r'[a-f0-9]{64}',value) is None:
        raise PreparationError('ACCOUNT_SELECTION_REQUIRED')


class RealPreparationSession:
    """Lazy server session; encrypted I/O only on explicit load/save/preview."""
    def __init__(self,*,store_factory=RealPreparationStore,market_factory=None,read_state=None,broker_client_factory=None,
                 clock=lambda:datetime.now(timezone.utc)):
        self.store_factory=store_factory;self.market_factory=market_factory
        self.read_state=read_state;self.clock=clock;self._market=None
        self.preparation=None;self.last_result=None;self._next_preview=None
        self.account_binding=None
        self._broker_client_factory=broker_client_factory;self._broker_clients={}

    def __repr__(self):return '<RealPreparationSession: no execution, encrypted drafts>'

    @staticmethod
    def _document(store):
        if not store.path.exists():return dict(purpose=PURPOSE,real_orders_enabled=False,profiles={})
        doc=store.load()
        if doc.get('purpose')!=PURPOSE or doc.get('real_orders_enabled') is not False or not isinstance(doc.get('profiles'),dict):
            raise PreparationError('PREPARATION_STORE_INVALID')
        return doc

    def load(self,binding):
        self.preparation=None;self.last_result=None;self.account_binding=None
        _binding(binding);store=self.store_factory()
        with store.locked():doc=self._document(store)
        result=deepcopy(doc['profiles'].get(binding))
        if result is not None:
            normalize_rows(result['rows'])
            if result.get('real_orders_enabled') is not False:raise PreparationError('PREPARATION_STORE_INVALID')
        self.preparation=result;self.account_binding=binding
        return deepcopy(result)

    def save(self,binding,rows):
        _binding(binding);rows=normalize_rows(rows);now=aware(self.clock())
        store=self.store_factory()
        with store.locked():
            doc=self._document(store);old=doc['profiles'].get(binding,{})
            result=dict(revision=secrets.token_hex(16),saved_at=now.isoformat(),rows=rows,
                proposed_stop_pct='20',live_risk_authorized=False,real_orders_enabled=False,
                tickets=old.get('tickets',[])[-100:])
            doc['profiles'][binding]=result;store.save(doc)
        self.preparation=deepcopy(result);self.last_result=None;self.account_binding=binding
        return deepcopy(result)

    def _state(self,symbol):
        if self.read_state is not None:return self.read_state(symbol)
        from manual_trade_service import read_manual_state
        from market_store import DEFAULT_MARKET_DATABASE
        return read_manual_state(DEFAULT_MARKET_DATABASE,symbol,aware(self.clock()).astimezone(ZoneInfo('America/New_York')).date())

    def _signal(self,symbol):
        from manual_trade_service import current_manual_signal
        from bollinger_phone_worker import detect_values,canonical_candle
        from automatic_entry_execution import signal_entry_deadline
        state=self._state(symbol);now=aware(self.clock());tick=current_manual_signal(state,symbol,now)
        g=tick.get('geometry') or {}
        try:
            side=detect_values(g['price'],g['previous_upper'],g['previous_lower'],g['previous_mid'],
                g['price'],g['upper'],g['lower'],g['mid'],opening=tick['opening'],
                opening_upper=g.get('initial_opening_upper'),opening_lower=g.get('initial_opening_lower'))
            if side!=tick['signal']['side'] or float(tick['signal']['price'])!=float(g['price']):raise ValueError
        except (KeyError,TypeError,ValueError,OverflowError):raise PreparationError('SIGNAL_GEOMETRY_NOT_VALID') from None
        first=state.get('detector_first_at')
        if not first:raise PreparationError('SIGNAL_CLOCK_UNAVAILABLE')
        first=aware(datetime.fromisoformat(first));deadline=signal_entry_deadline(first,now)
        from bollinger_breakout_clock import breakout_deadline
        cross_deadline=breakout_deadline(tick['signal'],now)
        if cross_deadline is not None:deadline=min(deadline,cross_deadline)
        candle=aware(datetime.fromisoformat(canonical_candle(tick['signal']['candle'])))
        if not candle<=first<=aware(datetime.fromisoformat(tick['source_timestamp'])):
            raise PreparationError('SIGNAL_CLOCK_UNAVAILABLE')
        return state,tick,deadline

    def preview(self,reader,reference,symbol,*,consult_broker=False):
        """On-demand ticket for a saved row. No claims, fills, orders or notices."""
        self.last_result=None;now=aware(self.clock())
        try:
            binding=reader.preparation_binding(reference,require_recent=True)
            if reader.snapshot.get('closing_only_restricted') is True:raise PreparationError('ACCOUNT_CLOSING_ONLY')
            preparation=self.load(binding)
            if preparation is None:raise PreparationError('PREPARATION_REQUIRED')
            row=next((r for r in preparation['rows'] if r['symbol']==symbol),None)
            if row is None:raise PreparationError('SAVED_SELECTION_REQUIRED')
            state,tick,deadline=self._signal(symbol)
            original_candle=tick['signal']['candle']
            side='CALL' if tick['signal']['side']=='SUPERIOR' else 'PUT'
            if self._next_preview is not None and now<self._next_preview:raise PreparationError('PREVIEW_COOLDOWN')
            self._next_preview=now+timedelta(seconds=1)
            if self._market is None:
                if self.market_factory is None:
                    from manual_trade_service import owner_market_data
                    self._market=owner_market_data()
                else:self._market=self.market_factory()
            market=self._market.get_catalog_chain(symbol,side,aware(self.clock()))
            state,tick,deadline=self._signal(symbol)
            if tick['signal']['candle']!=original_candle:raise PreparationError('SIGNAL_CHANGED')
            if side!=('CALL' if tick['signal']['side']=='SUPERIOR' else 'PUT'):
                raise PreparationError('SIGNAL_DIRECTION_CHANGED')
            from manual_trade_service import manual_candidates
            from option_contract_selection import entry_candidates
            now=aware(self.clock());_,expiry,candidates=manual_candidates(state,market,symbol,side,now)
            quotes=entry_candidates([c.snapshot for c in candidates],symbol=symbol,side=side,
                underlying_price=market.chain.underlying_price,underlying_stamp=market.chain.underlying_timestamp,
                as_of=now,listed_expirations=market.expirations,strike_inventory=market.strike_inventory)
            if not quotes:raise PreparationError('NO_ELIGIBLE_CONTRACTS')
            q=quotes[0];contract=next(c for c in candidates if c.snapshot.symbol==q.symbol);contract.validate_identity()
            if reader.preparation_binding(reference,require_recent=True)!=binding:raise PreparationError('ACCOUNT_SELECTION_REQUIRED')
            blockers=['LIVE_EXECUTION_DISABLED','LIVE_EXECUTION_POLICY_NOT_CONFIGURED','COMMISSIONS_NOT_VERIFIED']
            for field,code in (('options_permissions_verified','OPTIONS_PERMISSION_NOT_API_VERIFIED'),
                ('option_buying_power_verified','OPTION_BUYING_POWER_NOT_VERIFIED'),('currency_verified','CURRENCY_NOT_VERIFIED')):
                if reader.snapshot.get(field) is not True:blockers.append(code)
            from schwab_contracts import price_on_tick
            try:increment_verified=price_on_tick(q.ask,contract.price_increment,up=True)==Decimal(str(q.ask))
            except (ValueError,TypeError,ArithmeticError):increment_verified=False
            if not increment_verified:blockers.append('PRICE_INCREMENT_NOT_VERIFIED')
            expires=min(deadline,aware(datetime.fromisoformat(tick['source_timestamp']))+timedelta(seconds=3),
                aware(q.quote_timestamp)+timedelta(seconds=30),aware(market.chain.underlying_timestamp)+timedelta(seconds=30),
                aware(datetime.fromisoformat(reader.snapshot['checked_at']))+timedelta(seconds=60),
                aware(datetime.fromisoformat(state['session'][1])))
            broker_report=None
            if consult_broker:
                from schwab_option_order_request import prepare_option_preview
                context=reader.preview_context(reference)
                if context.binding!=binding:raise PreparationError('ACCOUNT_SELECTION_REQUIRED')
                if binding not in self._broker_clients:
                    if self._broker_client_factory is None:
                        from schwab_preview_client import SchwabPreviewClient
                        from real_live_control import verified_preview_wire
                        self._broker_clients[binding]=SchwabPreviewClient(context,utcnow=self.clock,wire_format=verified_preview_wire(binding))
                    else:self._broker_clients[binding]=self._broker_client_factory(context)
                draft=prepare_option_preview(contract,instruction='BUY_TO_OPEN',quantity=row['quantity'],now=now,valid_until=expires)
                broker_report=self._broker_clients[binding].preview(draft)
                state,latest,_=self._signal(symbol);now=aware(self.clock())
                if latest['signal']['candle']!=original_candle or latest['signal']['side']!=tick['signal']['side']:
                    raise PreparationError('SIGNAL_CHANGED')
                _,_,eligible=manual_candidates(state,market,symbol,side,now)
                if not any(c.snapshot.symbol==q.symbol for c in eligible):raise PreparationError('SELECTED_CONTRACT_CHANGED')
                if reader.preparation_binding(reference,require_recent=True)!=binding:raise PreparationError('ACCOUNT_SELECTION_REQUIRED')
                if broker_report.get('state') not in ('PREVIEW_ACCEPT_REPORTED','PREVIEW_NO_REJECTION_REPORTED'):blockers.append('BROKER_PREVIEW_REQUIRES_REVIEW')
            if now>=expires:raise PreparationError('PROPOSAL_NOT_CURRENT')
            ticket=dict(id=secrets.token_hex(16),preparation_revision=preparation['revision'],created_at=now.isoformat(),
                expires_at=expires.isoformat(),mode='REAL_SHADOW_ONLY',sendable=False,real_orders_enabled=False,
                symbol=symbol,side=side,contract=q.symbol,strike=str(q.strike),expiration=expiry.isoformat(),
                bid=str(q.bid),ask=str(q.ask),quantity=row['quantity'],target=row['target'],proposed_stop_pct='20',
                premium_cost=str(Decimal(str(q.ask))*100*row['quantity']),commissions=None,total_cost=None,
                signal_at=tick['source_timestamp'],quote_at=aware(q.quote_timestamp).isoformat(),
                first_signal_at=state['detector_first_at'],blockers=blockers)
            if broker_report is not None:
                ticket['mode']='REAL_PREVIEW_ONLY';ticket['broker_preview']=broker_report
            store=self.store_factory()
            with store.locked():
                doc=self._document(store);current=doc['profiles'].get(binding)
                if current is None or current['revision']!=preparation['revision']:raise PreparationError('PREPARATION_CHANGED')
                if aware(self.clock())>=expires:raise PreparationError('PROPOSAL_NOT_CURRENT')
                current['tickets']=(current.get('tickets',[])+[ticket])[-100:];store.save(doc)
            self.preparation=deepcopy(current);self.last_result=dict(state='SHADOW_TICKET_PREPARED',ticket=ticket)
        except Exception as error:
            allowed={'ACCOUNT_SELECTION_REQUIRED','ACCOUNT_READ_UNAVAILABLE','ACCOUNT_READING_NOT_CURRENT','ACCOUNT_CLOSING_ONLY',
                'PREPARATION_REQUIRED','SAVED_SELECTION_REQUIRED','SIGNAL_GEOMETRY_NOT_VALID','SIGNAL_CLOCK_UNAVAILABLE',
                'SIGNAL_ENTRY_WINDOW_EXPIRED','OUTSIDE_OFFICIAL_SESSION','NO_CURRENT_SIGNAL','TRADE_NOT_CURRENT',
                'COLLECTOR_NOT_CURRENT','SIGNAL_DIRECTION_CHANGED','SIGNAL_CHANGED','NO_ELIGIBLE_CONTRACTS','NO_ELIGIBLE_EXPIRATION_OR_RANGE',
                'PREVIEW_COOLDOWN','MARKET_DATA_COOLDOWN','RATE_LIMITED','REAUTHORIZATION_REQUIRED','AUTHORIZATION_REQUIRED',
                'PREPARATION_CHANGED','PROPOSAL_NOT_CURRENT','MARKET_DATA_UNAVAILABLE','SELECTED_CONTRACT_CHANGED',
                'PREVIEW_REQUEST_IDENTITY_INVALID','PREVIEW_PRICE_PRECISION_UNSUPPORTED','PREVIEW_AUTHORIZATION_UNAVAILABLE',
                'PREVIEW_RESPONSE_NOT_VERIFIED','PREVIEW_VALIDATION_REJECTED','PREVIEW_ACCESS_FORBIDDEN','PREVIEW_UNAVAILABLE',
                'ORDER_REQUEST_NOT_CURRENT','OPTION_QUOTE_NOT_CURRENT','OPTION_CONTRACT_EXPIRED'}
            self.last_result=dict(state=str(error) if str(error) in allowed else 'SHADOW_PREPARATION_UNAVAILABLE')
        return deepcopy(self.last_result)
