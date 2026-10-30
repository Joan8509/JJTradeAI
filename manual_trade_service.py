"""Shared read-only manual proposals; no broker orders, account calls or DB writes."""
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import Lock
from collections import OrderedDict
import time
from zoneinfo import ZoneInfo

from bollinger_phone_worker import STRATEGY_VERSION, canonical_candle
from option_contract_selection import entry_candidates, select_entry_expiration
from schwab_connection import (EncryptedSchwabStore, OAuthConfig, SchwabOAuth,
    SchwabReadOnlyClient, SchwabError, aware)
from schwab_contracts import normalize_chain

UTC=timezone.utc
NY=ZoneInfo('America/New_York')
_detector_first_cache=OrderedDict()


def detector_first_source(db,database,tick,*,cache=None):
    """Bounded indexed evidence lookup once per candle/side, never an API call.

    Do not renew a signal merely because the queue was not ready to see it.
    Refuse incomplete/pruned evidence rather than starting a new clock.
    """
    if cache is None:cache=_detector_first_cache
    if not tick or not tick.get('signal'):return None
    # Production candles inherit ET from the official calendar, while the
    # audit index stores UTC ISO text. SQLite compares TEXT lexically, not
    # instants: normalize bounds AND cache identity before the indexed query.
    signal=tick['signal'];candle=aware(datetime.fromisoformat(signal['candle']))
    key=(str(database),tick['symbol'],candle.isoformat(),signal['side'],tick.get('version'))
    if key in cache:return cache[key]
    oldest=db.execute('SELECT received_at FROM bollinger_tick_audit ORDER BY received_at LIMIT 1').fetchone()
    if not oldest or datetime.fromisoformat(oldest[0])>candle:return None
    row=db.execute("SELECT source_timestamp FROM bollinger_tick_audit WHERE received_at>=? AND received_at<? "
        "AND symbol=? AND reason='EXIT' AND json_extract(message_json,'$._jjtrade.geometry.side')=? "
        "ORDER BY received_at LIMIT 1",(candle.isoformat(),(candle+timedelta(minutes=15)).isoformat(),
            tick['symbol'],signal['side'])).fetchone()
    if row is None:return None
    first=datetime.fromisoformat(row[0].replace('Z','+00:00'))
    if not candle<=first<candle+timedelta(minutes=15):return None
    if len(cache)>=512:cache.popitem(last=False)
    cache[key]=first.isoformat()
    return first.isoformat()


class ManualDataError(RuntimeError):
    """Fixed codes only; never interpolate API responses, paths or private objects."""


def read_manual_state(database, symbol, session_date):
    """Four indexed rows; bounded reader, JSON decoded after releasing SQLite."""
    started=time.monotonic()
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',
                                     uri=True,timeout=2)) as db:
            db.set_progress_handler(lambda:time.monotonic()-started>2,1000)
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            session=db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',
                (session_date.isoformat(),)).fetchone()
            runtime=db.execute('SELECT state,heartbeat,feed,symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()
            tick=db.execute('SELECT payload_json FROM bollinger_tick_latest WHERE symbol=?',(symbol,)).fetchone()
            radar=db.execute('SELECT payload_json FROM bollinger_radar_state WHERE symbol=?',(symbol,)).fetchone()
            decoded_tick=json.loads(tick[0]) if tick else None
            try:first_source=detector_first_source(db,database,decoded_tick)
            except (sqlite3.Error,ValueError,TypeError,KeyError):first_source=None
        return {'session':session,'runtime':None if runtime is None else dict(
            state=runtime[0],heartbeat=runtime[1],feed=runtime[2],symbols=json.loads(runtime[3])),
            'tick':decoded_tick,'radar':json.loads(radar[0]) if radar else None,
            'detector_first_at':first_source}
    except (sqlite3.Error,OSError,ValueError,TypeError):
        raise ManualDataError('SIGNAL_STATE_UNAVAILABLE') from None


def _current(stamp, now, seconds):
    try:return timedelta(0)<=aware(now)-aware(datetime.fromisoformat(stamp))<=timedelta(seconds=seconds)
    except (TypeError,ValueError):return False


def current_manual_signal(state,symbol,now):
    """Preview market evidence, not account/risk authorization. No recomputation."""
    try:
        session=state['session']
        if not session or not aware(datetime.fromisoformat(session[0]))<=aware(now)<aware(datetime.fromisoformat(session[1])):
            raise ManualDataError('OUTSIDE_OFFICIAL_SESSION')
        runtime=state.get('runtime') or {}
        if (runtime.get('state')!='CONECTADO' or runtime.get('feed')!='iex'
                or symbol not in runtime.get('symbols',[]) or not _current(runtime.get('heartbeat'),now,3)):
            raise ManualDataError('COLLECTOR_NOT_CURRENT')
        tick=state.get('tick') or {}
        # The fast detector is the execution source. The asynchronous dashboard
        # projection can lag or disagree until its next cycle; it is not another
        # strategy approval. The engine validates the same current tick again.
        if (tick.get('symbol')!=symbol or tick.get('provider')!='ALPACA'
                or tick.get('feed')!='iex' or tick.get('source_kind')!='TRADE'
                or tick.get('version')!=STRATEGY_VERSION):
            raise ManualDataError('DETECTOR_STATE_INVALID')
        if (not _current(tick.get('source_timestamp'),now,3)
                or not _current(tick.get('checked_at'),now,3)):
            raise ManualDataError('TRADE_NOT_CURRENT')
        if not _current(tick.get('received_at'),now,3):
            raise ManualDataError('TRADE_NOT_CURRENT')
        source=aware(datetime.fromisoformat(tick['source_timestamp']))
        received=aware(datetime.fromisoformat(tick['received_at']))
        checked=aware(datetime.fromisoformat(tick['checked_at']))
        if not timedelta(0)<=received-source<=timedelta(seconds=3) or not timedelta(0)<=checked-source<=timedelta(seconds=3):
            raise ManualDataError('TRADE_NOT_CURRENT')
        if tick.get('reason')!='EXIT' or not tick.get('signal'):
            raise ManualDataError('NO_CURRENT_SIGNAL')
        signal=tick['signal']
        candle=canonical_candle(signal['candle'])
        opened=aware(datetime.fromisoformat(session[0]));closed=aware(datetime.fromisoformat(session[1]))
        candle_stamp=aware(datetime.fromisoformat(candle))
        expected=opened+timedelta(minutes=15*int((source-opened).total_seconds()//900))
        if candle_stamp!=expected or not candle_stamp<=source<min(candle_stamp+timedelta(minutes=15),closed):
            raise ManualDataError('NO_CURRENT_SIGNAL')
        if signal.get('side') not in ('SUPERIOR','INFERIOR'):
            raise ManualDataError('NO_CURRENT_SIGNAL')
        if not all(math.isfinite(float(v)) and float(v)>0 for v in (signal['price'],tick['opening'])):
            raise ManualDataError('NO_CURRENT_SIGNAL')
        return tick
    except ManualDataError:raise
    except (KeyError,TypeError,ValueError,OverflowError):
        raise ManualDataError('NO_CURRENT_SIGNAL') from None


@dataclass(frozen=True)
class ManualChain:
    symbol: str
    side: str
    expirations: tuple[date,...]
    chain: object
    fetched_at: datetime
    strike_inventory: tuple = ()


def decode_manual_chain(payload,symbol,side,now,*,verified_increments=None):
    try:
        mapping=payload['callExpDateMap' if side=='CALL' else 'putExpDateMap']
        if side not in ('CALL','PUT') or not isinstance(mapping,dict):raise ValueError
        #Calendar from the unfiltered provider map, including unusable/zero quotes.
        dates=tuple(sorted({date.fromisoformat(key.split(':')[0]) for key in mapping}))
        chain=normalize_chain(payload,symbol,verified_increments=verified_increments)
        # Preserve the unfiltered provider ladder, including zero/stale quotes.
        inventory=tuple(sorted({(date.fromisoformat(key.split(':')[0]),float(strike))
            for key,strikes in mapping.items() for strike in strikes}))
        if any(not math.isfinite(strike) or strike<=0 for _,strike in inventory):raise ValueError
        return ManualChain(symbol,side,dates,chain,aware(now),inventory)
    except (KeyError,TypeError,ValueError,OverflowError):
        raise ManualDataError('OPTION_CHAIN_INVALID') from None


def manual_candidates(state,market,symbol,side,now):
    tick=current_manual_signal(state,symbol,now)
    actual='CALL' if tick['signal']['side']=='SUPERIOR' else 'PUT'
    if side!=actual:raise ManualDataError('SIGNAL_DIRECTION_CHANGED')
    if (market.symbol,market.side)!=(symbol,side):raise ManualDataError('OPTION_CHAIN_IDENTITY_CHANGED')
    if not timedelta(0)<=aware(now)-market.fetched_at<=timedelta(seconds=30):
        raise ManualDataError('OPTION_CHAIN_NOT_CURRENT')
    try:
        expiry=select_entry_expiration(market.expirations,now)
        quotes=entry_candidates([c.snapshot for c in market.chain.contracts],symbol=symbol,
            side=side,underlying_price=float(tick['signal']['price']),
            underlying_stamp=datetime.fromisoformat(tick['source_timestamp']),as_of=now,
            listed_expirations=market.expirations, strike_inventory=market.strike_inventory)
    except ValueError:
        raise ManualDataError('NO_ELIGIBLE_EXPIRATION_OR_RANGE') from None
    by_symbol={c.snapshot.symbol:c for c in market.chain.contracts}
    return tick,expiry,tuple(by_symbol[q.symbol] for q in quotes)


MARKET_CACHE_REVISION='nonblocking_market_cache_v1'
POSITION_QUOTE_REVISION='owned_contract_quote_v1'


class ManualMarketData:
    """One shared REST client/cache. No accounts/positions/orders calls here."""
    def __init__(self,client,*,verified_increments=None,fee_per_contract=None,direct_quotes=False):
        self.client=client;self.increments=verified_increments or {};self.fee_per_contract=fee_per_contract
        self.lock=Lock();self.cache={};self.retry_at=None;self.catalog_cache={};self.direct_quotes=direct_quotes;self.selected_cache={}
        self.position_cache={}
        self.scoped_retries={};self.error_counts={}

    @staticmethod
    def _response_error(error):
        return (not isinstance(error,SchwabError) and
            (isinstance(error,(ValueError,TypeError,KeyError,OverflowError)) or
             isinstance(error,ManualDataError) and str(error)=='OPTION_CHAIN_INVALID'))

    def _record_retry(self, now, error, scope=None):
        local=scope is not None and self._response_error(error)
        seconds=1 if local and scope[0]=='position' else 15
        retry=aware(now)+timedelta(seconds=max(seconds,getattr(error,'retry_after_seconds',None) or 0))
        with self.lock:
            # A malformed response/identity for one instrument is not evidence
            # of a provider-wide outage. HTTP/auth/transport/unknown failures
            # remain shared and retain the full provider Retry-After.
            if local:
                if scope not in self.scoped_retries and len(self.scoped_retries)>=512:
                    self.scoped_retries.pop(next(iter(self.scoped_retries)))
                self.scoped_retries[scope]=max(self.scoped_retries.get(scope,retry),retry)
            elif self.retry_at is None or retry>self.retry_at:self.retry_at=retry

    def _retry_locked(self,now,scope):
        if ((self.retry_at is not None and aware(now)<self.retry_at)
                or aware(now)<self.scoped_retries.get(scope,aware(now))):
            raise ManualDataError('MARKET_DATA_COOLDOWN')

    def _failure(self,now,error,scope):
        self._record_retry(now,error,scope)
        allowed={'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED',
                 'TRANSPORT_FAILURE','HTTP_FAILURE'}
        code=error.code if isinstance(error,SchwabError) and error.code in allowed else 'MARKET_DATA_UNAVAILABLE'
        cause=code if code!='MARKET_DATA_UNAVAILABLE' else (
            'OPTION_RESPONSE_INVALID' if self._response_error(error) else
            'TRANSPORT_FAILURE' if isinstance(error,(TimeoutError,ConnectionError)) else 'MARKET_DATA_UNAVAILABLE')
        with self.lock:self.error_counts[cause]=self.error_counts.get(cause,0)+1
        failure=ManualDataError(code);failure.cause_code=cause
        return failure

    @staticmethod
    def _publish(cache, key, result):
        """Under cache lock; an older in-flight response cannot roll back data."""
        current=cache.get(key)
        if current is None or current.fetched_at<=result.fetched_at:cache[key]=result

    def _recent_entry_catalog(self, symbol, side, contract_symbol, now):
        """Called under lock; reuse only sub-second option AND spot evidence.

        This is not a longer quote tolerance: a slower/stale response still
        takes the existing selected-contract GET and the caller revalidates.
        """
        complete=self.cache.get((symbol,side))
        if complete is None or not timedelta(0)<=aware(now)-complete.fetched_at<=timedelta(minutes=5):
            return None
        catalogs=[complete]+[value for (root,option,_),value in self.catalog_cache.items()
                             if (root,option)==(symbol,side)]
        for market in sorted(catalogs,key=lambda value:value.fetched_at,reverse=True):
            if not timedelta(0)<=aware(now)-market.fetched_at<timedelta(seconds=1):continue
            contract=next((c for c in market.chain.contracts if c.snapshot.symbol==contract_symbol),None)
            if contract is None:continue
            try:
                if contract.snapshot.expiration!=select_entry_expiration(complete.expirations,now):continue
                stamps=(contract.snapshot.quote_timestamp,market.chain.underlying_timestamp)
                if all(stamp is not None and timedelta(0)<=aware(now)-aware(stamp)<timedelta(seconds=1) for stamp in stamps):
                    return market
            except (ValueError,TypeError):continue
        return None

    def get_catalog_chain(self,symbol,side,now):
        """Fast selected-expiry view with the same complete-calendar requirement.

        A partial response never replaces the complete chain/calendar cache.
        Quote age, ITM, premium and spread are still validated by the callers.
        """
        if side not in ('CALL','PUT') or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,7}',symbol):
            raise ManualDataError('OPTION_SEARCH_INVALID')
        with self.lock:
            self._retry_locked(now,('catalog',symbol,side))
            complete=self.cache.get((symbol,side))
            calendar_age=timedelta(minutes=5) if self.direct_quotes else timedelta(seconds=30)
            use_full=complete is None or not timedelta(0)<=aware(now)-complete.fetched_at<=calendar_age
            if not use_full:
                expiry=select_entry_expiration(complete.expirations,now)
                old=self.catalog_cache.get((symbol,side,expiry))
                if old and timedelta(0)<=aware(now)-old.fetched_at<timedelta(seconds=5):return old
                if timedelta(0)<=aware(now)-complete.fetched_at<timedelta(seconds=5):return complete
        if use_full:return self.get_chain(symbol,side,now,force=True)
        try:
            raw=self.client.chain(symbol,side,expiry,expiry,now)
            partial=decode_manual_chain(raw,symbol,side,now,verified_increments=self.increments)
        except Exception as error:
            raise self._failure(now,error,('catalog',symbol,side)) from None
        result=ManualChain(symbol,side,complete.expirations,partial.chain,partial.fetched_at,partial.strike_inventory)
        with self.lock:self._publish(self.catalog_cache,(symbol,side,expiry),result)
        return result

    def prepare_calendar(self,symbol,side,now):
        """Background metadata lookup; network never holds the trading cache lock.

        Complete calendars keep their existing five-minute lifetime. Publication
        never overwrites a newer foreground response. Quotes retain their real
        provider timestamps and still require the normal entry validation.
        """
        if side not in ('CALL','PUT') or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,7}',symbol):
            raise ManualDataError('OPTION_SEARCH_INVALID')
        if self.direct_quotes is not True:raise ManualDataError('OPTION_SEARCH_INVALID')
        now=aware(now)
        with self.lock:
            self._retry_locked(now,('catalog',symbol,side))
            old=self.cache.get((symbol,side))
            if old and timedelta(0)<=now-old.fetched_at<timedelta(minutes=4):return old
        try:
            raw=self.client.full_chain(symbol,side,now)
            result=decode_manual_chain(raw,symbol,side,now,verified_increments=self.increments)
            select_entry_expiration(result.expirations,now)
        except Exception as error:
            raise self._failure(now,error,('catalog',symbol,side)) from None
        with self.lock:
            current=self.cache.get((symbol,side))
            if current is None or current.fetched_at<result.fetched_at:
                self.cache[(symbol,side)]=result
                return result
            return current

    def get_chain(self,symbol,side,now,*,force=False):
        if side not in ('CALL','PUT') or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,7}',symbol):
            raise ManualDataError('OPTION_SEARCH_INVALID')
        with self.lock:
            self._retry_locked(now,('catalog',symbol,side))
            old=self.cache.get((symbol,side))
            if not force and old and timedelta(0)<=aware(now)-old.fetched_at<timedelta(seconds=5):return old
        try:
            raw=self.client.full_chain(symbol,side,now)
            result=decode_manual_chain(raw,symbol,side,now,verified_increments=self.increments)
        except Exception as error:
            raise self._failure(now,error,('catalog',symbol,side)) from None
        with self.lock:self._publish(self.cache,(symbol,side),result)
        return result

    def get_position_chain(self,symbol,side,contract_symbol,now,*,force=True):
        """Refresh an owned contract without requiring a new entry calendar.

        Only immutable, provider-verified identity is reused. Prices, reference,
        real-time flag and trading status come from a new batched quote. Never
        publish this result into entry caches or extend entry-calendar validity.
        The workflow calls this only for filled exposure / pending sells.
        """
        if not self.direct_quotes:
            return self.get_entry_chain(symbol,side,contract_symbol,now,force=force)
        if side not in ('CALL','PUT') or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,7}',symbol):
            raise ManualDataError('OPTION_SEARCH_INVALID')
        with self.lock:
            self._retry_locked(now,('position',symbol,side,contract_symbol))
            cached=self.position_cache.get((symbol,side,contract_symbol))
            if not force and cached and timedelta(0)<=aware(now)-cached.fetched_at<timedelta(seconds=1):
                return cached
            known=[cached,self.cache.get((symbol,side)),self.selected_cache.get((symbol,side,contract_symbol))]
            known += [value for (root,option,_),value in self.catalog_cache.items() if (root,option)==(symbol,side)]
            identity=next((m for m in known if m is not None and
                (m.symbol,m.side)==(symbol,side) and any(c.snapshot.symbol==contract_symbol for c in m.chain.contracts)),None)
        if identity is None:
            # Cold recovery still obtains verified metadata; never synthesize
            # a contract from an order string or silently reuse unknown identity.
            identity=self.get_chain(symbol,side,now,force=True)
        try:
            from selected_option_quotes import refresh_selected
            payload=self.client.quotes([symbol,contract_symbol],now)
            result=refresh_selected(identity,contract_symbol,payload,aware(now))
        except Exception as error:
            raise self._failure(now,error,('position',symbol,side,contract_symbol)) from None
        with self.lock:self._publish(self.position_cache,(symbol,side,contract_symbol),result)
        return result

    def get_entry_chain(self,symbol,side,contract_symbol,now,*,force=True):
        """Refresh the selected expiry, retaining a recently complete calendar.

        Never put a partial chain into the full-chain cache. If no recent full
        calendar exists, perform the existing complete lookup instead.
        """
        waiting_started=time.monotonic()
        with self.lock:
            cached=self.selected_cache.get((symbol,side,contract_symbol))
            if self.direct_quotes and not force and cached and timedelta(0)<=aware(now)-cached.fetched_at<timedelta(seconds=1):
                return cached
            if self.direct_quotes and not force:
                # Time waiting behind another REST lookup counts against the
                # sub-second optimization; never evaluate it on an earlier clock.
                effective_now=aware(now)+timedelta(seconds=time.monotonic()-waiting_started)
                recent=self._recent_entry_catalog(symbol,side,contract_symbol,effective_now)
                if recent is not None:return recent
            old=self.cache.get((symbol,side))
            # Calendar/identity cache is distinct from the unchanged 30s quote
            # gate. Production refreshes the chosen option/spot in one GET.
            calendar_age=timedelta(minutes=5) if self.direct_quotes else timedelta(seconds=30)
            if old is None or not timedelta(0)<=aware(now)-old.fetched_at<=calendar_age:
                use_full=True
            else:
                use_full=False
                selected=next((c for c in old.chain.contracts if c.snapshot.symbol==contract_symbol),None)
                if selected is None:
                    # A quote rejected in the earlier complete response may
                    # become valid in a later catalog response. Use that already
                    # normalized identity solely to choose the refresh date;
                    # eligibility is still checked on the fresh response.
                    for (root,option,expiry),catalog in self.catalog_cache.items():
                        if (root,option)!=(symbol,side) or expiry not in old.expirations:
                            continue
                        if not timedelta(0)<=aware(now)-catalog.fetched_at<=timedelta(seconds=30):
                            continue
                        selected=next((c for c in catalog.chain.contracts if c.snapshot.symbol==contract_symbol),None)
                        if selected is not None:break
                if selected is None:raise ManualDataError('CONTRACT_NO_LONGER_ELIGIBLE')
                self._retry_locked(now,('entry',symbol,side,contract_symbol))
        if use_full:return self.get_chain(symbol,side,now,force=True)
        try:
            expiry=selected.snapshot.expiration
            if self.direct_quotes:
                from selected_option_quotes import refresh_selected
                payload=self.client.quotes([symbol,contract_symbol],now)
                result=refresh_selected(old,contract_symbol,payload,aware(now))
                with self.lock:
                    self._publish(self.catalog_cache,(symbol,side,expiry),result)
                    self._publish(self.selected_cache,(symbol,side,contract_symbol),result)
                return result
            raw=self.client.chain(symbol,side,expiry,expiry,now)
            partial=decode_manual_chain(raw,symbol,side,now,verified_increments=self.increments)
        except Exception as error:
            raise self._failure(now,error,('entry',symbol,side,contract_symbol)) from None
        return ManualChain(symbol,side,old.expirations,partial.chain,partial.fetched_at,partial.strike_inventory)


def owner_market_data():
    """Call under Administrator only; encrypted config stays in memory, never UI."""
    try:
        store=EncryptedSchwabStore();profile=store.load()
        if profile.get('api_product')!='MARKET_DATA_ONLY' or profile.get('real_orders_enabled') is not False:
            raise ValueError
        oauth=SchwabOAuth(OAuthConfig(**profile['oauth_config']),store)
        return ManualMarketData(SchwabReadOnlyClient(oauth),
            direct_quotes=True,
            verified_increments=profile.get('verified_contract_price_increments'),
            fee_per_contract=profile.get('fee_per_contract'))
    except Exception:
        raise ManualDataError('PRIVATE_MARKET_CONFIG_UNAVAILABLE') from None
