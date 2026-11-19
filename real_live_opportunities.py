"""Use the existing detector/selection for REAL, without changing simulation."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json,re
import time
from threading import Lock

from real_trade_preparation import RealPreparationSession
from schwab_connection import aware
from schwab_contracts import decimal
from schwab_option_order_request import prepare_observed_limit

ENTRY_ERROR_CODES=frozenset({
    'NO_CURRENT_SIGNAL','COLLECTOR_NOT_CURRENT','TRADE_NOT_CURRENT','DETECTOR_STATE_INVALID',
    'SIGNAL_GEOMETRY_NOT_VALID','SIGNAL_CLOCK_UNAVAILABLE','SIGNAL_STATE_UNAVAILABLE',
    'SIGNAL_ENTRY_WINDOW_EXPIRED','SIGNAL_ENTRY_CLOCK_INVALID','OUTSIDE_OFFICIAL_SESSION',
    'SIGNAL_DIRECTION_CHANGED','NO_ELIGIBLE_EXPIRATION_OR_RANGE','OPTION_CHAIN_NOT_CURRENT',
    'OPTION_CHAIN_IDENTITY_CHANGED','OPTION_CHAIN_INVALID','MARKET_DATA_UNAVAILABLE','MARKET_DATA_COOLDOWN',
    'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED','TRANSPORT_FAILURE','HTTP_FAILURE',
    'LIVE_PREVIEW_NOT_ACCEPTED','LIVE_PREVIEW_COSTS_INCOMPLETE','LIVE_PREVIEW_FUNDS_INCOMPLETE',
    'LIVE_PREVIEW_IDENTITY_MISMATCH','LIVE_PREVIEW_FUNDS_INSUFFICIENT','PREVIEW_RESPONSE_NOT_VERIFIED',
    'LIVE_SETTLED_CASH_INSUFFICIENT','LIVE_COMPANY_ALREADY_HELD','LIVE_ACCOUNT_NOT_CURRENT',
    'LIVE_ENTRY_COST_NOT_CURRENT','OPTION_QUOTE_NOT_CURRENT','OPTION_IDENTITY_INVALID',
    'ENTRY_SPREAD_EXCEEDS_MAX','ENTRY_OUTSIDE_OPTIMAL_PREMIUM','OPTION_INCREMENT_NOT_VERIFIED'})


def signal_identity(tick,first):
    from bollinger_phone_worker import canonical_candle
    # Tightening opening membership must not create a second order identity
    # for a v7 signal already attempted in this candle. Keep its original clock.
    version = ('v7_ruptura_temprana_30s'
               if tick['version'] in ('v8_apertura_dentro_bandas_previas', 'v9_primera_estrategia_completa_30s')
               else tick['version'])
    value=[tick['provider'],tick['feed'],version,tick['symbol'],
           canonical_candle(tick['signal']['candle']),tick['signal']['side'],aware(first).isoformat()]
    return 'REAL:'+sha256(json.dumps(value,separators=(',',':')).encode()).hexdigest()


class RealOpportunities:
    selected_revalidation_revision=1

    def __init__(self,market,capital,*,clock=lambda:datetime.now(timezone.utc),signal_reader=None,monotonic=time.monotonic,evidence_recorder=None):
        self.market=market;self.capital=capital;self.clock=clock
        if signal_reader is None:
            from real_entry_state import RealEntryStateReader
            from market_store import DEFAULT_MARKET_DATABASE
            signal_reader=RealPreparationSession(clock=clock,
                read_state=RealEntryStateReader(DEFAULT_MARKET_DATABASE,clock=clock))
        self.reader=signal_reader
        self.evidence_recorder=evidence_recorder
        self._signals={};self._quotes={}
        self._funding_rejected=set()
        self._monotonic=monotonic;self._timing_lock=Lock();self._timings={}
        self._attempts={}

    def attempt_status(self):
        from copy import deepcopy
        with self._timing_lock:return deepcopy(self._attempts)

    def timing_status(self):
        with self._timing_lock:
            return {symbol:dict(value,seconds=dict(value['seconds'])) for symbol,value in self._timings.items()}

    def __call__(self,row):
        started=self._monotonic();mark=started;phase='detector';seconds={};outcome='NOT_PREPARED';details={};error_code=None
        def advance(next_phase,**fields):
            nonlocal mark,phase
            details.update(fields)
            now=self._monotonic();seconds[phase]=seconds.get(phase,0.)+max(0.,now-mark);mark=now;phase=next_phase
        try:
            result=self._prepare(row,advance)
            if result is not None:outcome='PREPARED_NOT_SENT'
            return result
        except Exception as error:
            raw=getattr(error,'code',None) or str(error)
            error_code=raw if isinstance(raw,str) and raw in ENTRY_ERROR_CODES else 'LIVE_OPPORTUNITY_UNAVAILABLE'
            outcome='UNAVAILABLE';raise
        finally:
            ended=self._monotonic();seconds[phase]=seconds.get(phase,0.)+max(0.,ended-mark)
            seconds['total']=max(0.,ended-started)
            value=dict(checked_at=aware(self.clock()).isoformat(),outcome=outcome,
                seconds={key:round(value,6) for key,value in seconds.items()})
            if error_code:value['error_code']=error_code
            with self._timing_lock:
                if row['symbol'] not in self._timings and len(self._timings)>=30:
                    self._timings.pop(next(iter(self._timings)))
                self._timings[row['symbol']]=value
                # In-memory only: no disk or notification I/O delays entry.
                # The host persists this with its existing encrypted heartbeat.
                if details.get('signal_key'):
                    key=details['signal_key']
                    attempt=dict(symbol=row['symbol'],phase=phase,**details,**value)
                    previous=self._attempts.get(key)
                    if previous:
                        attempt['first_attempt']=previous['first_attempt']
                        attempt['first_failure']=previous.get('first_failure')
                    else:
                        if len(self._attempts)>=128:self._attempts.pop(next(iter(self._attempts)))
                        attempt['first_attempt']=dict(value,phase=phase)
                        attempt['first_failure']=None
                    if error_code and attempt['first_failure'] is None:
                        attempt['first_failure']=dict(code=error_code,phase=phase,checked_at=value['checked_at'])
                    self._attempts[key]=attempt

    def _prepare(self,row,advance):
        from manual_trade_service import manual_candidates
        from option_contract_selection import entry_candidates
        state,tick,deadline=self.reader._signal(row['symbol'])
        side='CALL' if tick['signal']['side']=='SUPERIOR' else 'PUT'
        original=signal_identity(tick,datetime.fromisoformat(state['detector_first_at']))
        after=row.get('_signal_after')
        if ((after is not None and aware(datetime.fromisoformat(state['detector_first_at']))<=
                aware(datetime.fromisoformat(after)))) or original in row.get('used_signals',()):
            return None
        advance('funding',signal_key=original,first_signal_at=state['detector_first_at'])
        from price_ranges import optimal_option_premium
        # Impossible even before fees: avoid a slow chain request that can hold
        # up the other companies in this entry turn. Final admission is unchanged.
        minimum,_=optimal_option_premium(row['symbol'])
        if minimum*100*row['quantity']>self.capital.funding_capacity():
            raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        advance('contract_search')
        market=self.market.get_catalog_chain(row['symbol'],side,aware(self.clock()))
        advance('selection_and_revalidation')
        state,tick,deadline=self.reader._signal(row['symbol']);now=aware(self.clock())
        first=aware(datetime.fromisoformat(state['detector_first_at']))
        key=signal_identity(tick,first)
        if key!=original:return None
        _,_,candidates=manual_candidates(state,market,row['symbol'],side,now)
        quotes=entry_candidates([c.snapshot for c in candidates],symbol=row['symbol'],side=side,
            underlying_price=market.chain.underlying_price,underlying_stamp=market.chain.underlying_timestamp,
            as_of=now,listed_expirations=market.expirations,strike_inventory=market.strike_inventory)
        if not quotes:raise ValueError('NO_ELIGIBLE_EXPIRATION_OR_RANGE')
        if self.evidence_recorder is not None:
            try:
                quoted={q.symbol for q in quotes}
                self.evidence_recorder.publish(tuple(c for c in candidates if c.snapshot.symbol in quoted),
                    phase='ENTRY_CANDIDATE',symbol=row['symbol'],signal_key=key,spot=market.chain.underlying_price)
            except Exception:pass
        capacity=self.capital.funding_capacity()
        def funding_key(q):return (key,q.symbol,str(q.ask),row['quantity'],str(capacity))
        quotes=[q for q in quotes if decimal(q.ask)*100*row['quantity']<=capacity and funding_key(q) not in self._funding_rejected]
        if not quotes:raise ValueError('LIVE_SETTLED_CASH_INSUFFICIENT')
        # One immediate cheaper fallback only after an explicit funds failure.
        # No order has been sent here. Unknown/review/transport failures never
        # trigger another preview, and the original signal deadline is retained.
        preview_attempts=[]
        for attempt_index in range(2):
            q=quotes[0];contract=next(c for c in candidates if c.snapshot.symbol==q.symbol)
            now=aware(self.clock())
            end=aware(datetime.fromisoformat(state['session'][1]))
            draft=prepare_observed_limit(contract,instruction='BUY_TO_OPEN',quantity=row['quantity'],now=now,
                valid_until=min(deadline,end))
            advance('broker_preview',selected_contract=q.symbol,selected_ask=str(q.ask),
                funding_preview_attempts=preview_attempts)
            try:
                self.capital.authorize(draft,row['symbol'])  # preview only, never a buy
            except ValueError as error:
                if str(error)!='LIVE_SETTLED_CASH_INSUFFICIENT':raise
                if len(self._funding_rejected)>=1024:self._funding_rejected.clear()
                self._funding_rejected.add(funding_key(q))
                preview_attempts.append(dict(contract=q.symbol,ask=str(q.ask),result='INSUFFICIENT_FUNDS'))
                if attempt_index:raise
                # Re-read before any fallback HTTP. Retraction, changed side or
                # expiry stop here; neither cached geometry nor a new clock wins.
                state,latest,deadline=self.reader._signal(row['symbol'])
                if signal_identity(latest,datetime.fromisoformat(state['detector_first_at']))!=key:return None
                now=aware(self.clock())
                _,_,eligible=manual_candidates(state,market,row['symbol'],side,now)
                valid={c.snapshot.symbol for c in eligible}
                capacity=self.capital.funding_capacity()
                cheaper=[candidate for candidate in quotes[1:] if candidate.symbol in valid
                    and decimal(candidate.ask)<decimal(q.ask)
                    and decimal(candidate.ask)*100*row['quantity']<=capacity
                    and funding_key(candidate) not in self._funding_rejected]
                if not cheaper:raise
                # The lowest allowed Ask gives the best remaining headroom for
                # fees. The exact broker preview still decides affordability.
                quotes=sorted(cheaper,key=lambda candidate:decimal(candidate.ask))
                continue
            preview_attempts.append(dict(contract=q.symbol,ask=str(q.ask),result='AUTHORIZED_PREVIEW'))
            break
        advance('final_revalidation')
        state,latest,_=self.reader._signal(row['symbol'])
        if signal_identity(latest,datetime.fromisoformat(state['detector_first_at']))!=key:return None
        # Revalidate the same contract against detector and broker spots after HTTP.
        _,_,eligible=manual_candidates(state,market,row['symbol'],side,aware(self.clock()),contract_symbol=q.symbol)
        if not any(c.snapshot.symbol==q.symbol for c in eligible):return None
        if not self.capital.entry_ready():return None
        self._signals[key]=row['symbol'];self._quotes[q.symbol]=contract
        return dict(signal_key=key,draft=draft,first_signal_at=first,
            source_at=aware(datetime.fromisoformat(latest['source_timestamp'])),session_close=end,target=row['target'])

    def signal_current(self,key):
        symbol=self._signals.get(key)
        if symbol is None:return False
        try:
            state,tick,_=self.reader._signal(symbol)
            return signal_identity(tick,datetime.fromisoformat(state['detector_first_at']))==key
        except Exception:return False

    def quote_contract(self,symbol):
        now=aware(self.clock());cached=self._quotes.get(symbol)
        if cached and timedelta(0)<=now-aware(cached.snapshot.quote_timestamp)<timedelta(seconds=1):return cached
        match=re.fullmatch(r'([A-Z0-9.]{1,8}) *\d{6}([CP])\d{8}',symbol)
        if not match:raise ValueError('LIVE_OPTION_IDENTITY_INVALID')
        market=self.market.get_position_chain(match[1],'CALL' if match[2]=='C' else 'PUT',symbol,now,force=True)
        contract=next(c for c in market.chain.contracts if c.snapshot.symbol==symbol)
        contract.validate_identity();self._quotes[symbol]=contract
        if self.evidence_recorder is not None:
            try:self.evidence_recorder.publish((contract,),phase='POSITION_QUOTE',symbol=match[1],spot=market.chain.underlying_price)
            except Exception:pass
        return contract

    def entry_contract(self,symbol):
        # Same exact BBO already previewed, within the original quote lifetime.
        # No second REST quote/preview loop while a valid signal is waiting.
        contract=self._quotes[symbol]
        if not timedelta(0)<=aware(self.clock())-aware(contract.snapshot.quote_timestamp)<timedelta(seconds=30):
            raise ValueError('LIVE_ENTRY_QUOTE_NOT_CURRENT')
        return contract
