"""Explicit paper entry by a delivered alert, independent of a later pullback.

Never manufacture a detector EXIT. Real orders and generic automation cannot
use this authorization; current Schwab prices and all contract rules still apply.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
import time

from bollinger_phone_worker import STRATEGY_VERSION,EVENT_KEY_VERSION,canonical_candle,candle_keys
from option_contract_selection import entry_candidates,select_entry_expiration
from schwab_contracts import decimal

@dataclass(frozen=True)
class AlertReference:
    symbol:str
    side:str
    candle:str
    source_timestamp:str
    attempted_at:str
    version:str
    provider:str
    feed:str
    opening:float
    detection_price:float
    delivery_state:str

@dataclass(frozen=True)
class ManualAlertEntry:
    reference:AlertReference
    underlying_price:float
    underlying_timestamp:datetime
    fetched_at:datetime

def read_alert_reference(database,symbol,side,candle,owner):
    """Two exact PK lookups/aliases, RO and bounded; caller supplies private owner."""
    from manual_trade_service import ManualDataError
    try:
        actual='SUPERIOR' if side=='CALL' else 'INFERIOR' if side=='PUT' else None
        if actual is None:raise ValueError
        candle=canonical_candle(candle)
        notice_keys=candle_keys(f'v1|{owner}|ALPACA|iex|{symbol}',candle,actual)
        event_keys=candle_keys(f'{EVENT_KEY_VERSION}|ALPACA|iex|{symbol}',candle,actual)
        event_keys=tuple(dict.fromkeys(event_keys+candle_keys(f'{STRATEGY_VERSION}|ALPACA|iex|{symbol}',candle,actual)))
        started=time.monotonic()
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda:time.monotonic()-started>2,1000)
            db.execute('BEGIN')
            notice=db.execute('SELECT state,attempted_at FROM bollinger_phone_notifications WHERE event_key IN (?,?)',
                (notice_keys[0],notice_keys[-1])).fetchone()
            events=dict(db.execute('SELECT event_key,payload_json FROM bollinger_live_events WHERE event_key IN ('+
                ','.join('?' for _ in event_keys)+')',event_keys).fetchall())
            event=next((events[k] for k in event_keys if k in events),None)
        if not notice or not event:raise ValueError
        e=json.loads(event)
        if (e['symbol'],e['side'],canonical_candle(e['candle']))!=(symbol,actual,candle):raise ValueError
        return AlertReference(symbol,side,candle,e['source_timestamp'],notice[1],e['version'],
            e['provider'],e['feed'],e['opening'],e['price'],notice[0])
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError):
        raise ManualDataError('DELIVERED_ALERT_REQUIRED') from None

def validate_reference(reference,controls,now):
    from schwab_simulation import ExecutionBlocked
    controls.require_session(now)
    if type(reference) is not AlertReference:raise ExecutionBlocked('DELIVERED_ALERT_REQUIRED')
    r=reference
    if ((r.provider,r.feed,r.delivery_state)!=('ALPACA','iex','ENVIADO') or
            r.version not in (STRATEGY_VERSION,EVENT_KEY_VERSION)):
        raise ExecutionBlocked('DELIVERED_ALERT_REQUIRED')
    if r.side not in ('CALL','PUT') or decimal(r.opening)<=0 or decimal(r.detection_price)<=0:
        raise ExecutionBlocked('DELIVERED_ALERT_REQUIRED')
    candle=datetime.fromisoformat(canonical_candle(r.candle))
    source=datetime.fromisoformat(r.source_timestamp);attempted=datetime.fromisoformat(r.attempted_at)
    opened=controls.session_opens;closed=controls.session_closes
    official=opened+timedelta(minutes=15*int((candle-opened).total_seconds()//900))
    # Manual practice may finish preparation later in the SAME official session.
    # Preserve the original candle/key, never relabel or replay its notification.
    # The source must still belong to that candle; fresh option/spot checks below
    # remain mandatory at each entry. Generic/real execution cannot use this basis.
    if (candle!=official or not opened<=candle<=source<candle+timedelta(minutes=15)
            or not source<=attempted<=now<closed):
        raise ExecutionBlocked('ALERT_WINDOW_ENDED')
    return r

def validated_alert_entry(entry,controls,now,*,snapshot=None):
    from schwab_simulation import ExecutionBlocked,digest
    if type(entry) is not ManualAlertEntry:raise ExecutionBlocked('DELIVERED_ALERT_REQUIRED')
    r=validate_reference(entry.reference,controls,now)
    if not all((controls.history_ready,controls.operational_ready,controls.account_reconciled)):
        raise ExecutionBlocked('DATA_OR_OPERATIONAL_CONTROLS')
    if snapshot and snapshot.get('reason') in ('CORRECTION_QUARANTINE','OPENING_OUT_OF_ORDER'):
        raise ExecutionBlocked('ALERT_REFERENCE_QUARANTINED')
    if (decimal(entry.underlying_price)<=0 or
        not timedelta(0)<=now-entry.underlying_timestamp<=timedelta(seconds=30) or
        not timedelta(0)<=now-entry.fetched_at<=timedelta(seconds=30)):
        raise ExecutionBlocked('UNDERLYING_QUOTE_NOT_CURRENT')
    return dict(symbol=r.symbol,side='SUPERIOR' if r.side=='CALL' else 'INFERIOR',
        option_type=r.side,candle=canonical_candle(r.candle),source_timestamp=r.source_timestamp,
        key=digest(['ALPACA','iex',r.symbol,canonical_candle(r.candle),'SUPERIOR' if r.side=='CALL' else 'INFERIOR']),
        underlying_price=entry.underlying_price,underlying_timestamp=entry.underlying_timestamp,
        entry_basis='DELIVERED_ALERT_MANUAL_V1',manual_alert=entry)

def alert_candidates(reference,state,market,now,controls):
    from schwab_simulation import ExecutionBlocked
    if (market.symbol,market.side)!=(reference.symbol,reference.side):raise ExecutionBlocked('SIGNAL_CONTRACT_MISMATCH')
    entry=ManualAlertEntry(reference,market.chain.underlying_price,market.chain.underlying_timestamp,market.fetched_at)
    signal=validated_alert_entry(entry,controls,now,snapshot=state.get('tick'))
    expiry=select_entry_expiration(market.expirations,now)
    quotes=entry_candidates([c.snapshot for c in market.chain.contracts],symbol=reference.symbol,
        side=reference.side,underlying_price=float(entry.underlying_price),
        underlying_stamp=entry.underlying_timestamp,as_of=now,listed_expirations=market.expirations, strike_inventory=market.strike_inventory)
    selected={q.symbol for q in quotes}
    return signal,expiry,tuple(c for c in market.chain.contracts if c.snapshot.symbol in selected)
