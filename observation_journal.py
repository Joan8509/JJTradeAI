"""Bounded private exit diagnostics. Trading only enqueues; disk I/O is separate."""
from collections import deque
from datetime import datetime
from decimal import Decimal
import json,re
from pathlib import Path
from threading import Lock

ERROR_CODES=frozenset({
    'OPTION_RESPONSE_INVALID',
    'MARKET_DATA_COOLDOWN','MARKET_DATA_UNAVAILABLE','EXIT_QUOTE_UNUSABLE',
    'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED','RATE_LIMITED',
    'TRANSPORT_FAILURE','HTTP_FAILURE','POSITION_RECONCILIATION_REQUIRED',
    'ENTRY_CANCELLATION_AND_RECONCILIATION_REQUIRED','CONTRACT_NO_LONGER_ELIGIBLE',
    'OBSERVATION_FAILED',
})

def observation_error_code(error):
    """Fixed codes only: no exception body, URL, account or credentials."""
    code=getattr(error,'cause_code',None) or str(error)
    return code if code in ERROR_CODES else 'OBSERVATION_FAILED'


def market_failure_counts(data):
    """Optional counters must never interrupt the position monitor."""
    try:
        values=getattr(data,'error_counts',None)
        if type(values) is not dict:return {}
        return {key:value for key,value in values.copy().items()
                if key in ERROR_CODES and type(value) is int and value>=0}
    except Exception:return {}

class ObservationJournal:
    EVENTS={'LOOKUP_STARTED','LOOKUP_FINISHED','LOOKUP_FAILED','POST_ORDER_QUOTE_REQUIRED',
            'BID_BELOW_LIMIT','NO_AVAILABLE_LIQUIDITY','MATCH_APPLIED','EXIT_ORDER_REGISTERED',
            'POSITION_MARK','POSITION_LOOKUP_FAILED'}
    def __init__(self,path,*,capacity=256,max_bytes=16_000_000):
        self.path=Path(path);self.capacity=capacity;self.max_bytes=max_bytes
        self.pending=deque();self.lock=Lock();self.dropped=0
        self.last_marks={}

    def record(self,event,**fields):
        if event not in self.EVENTS:return
        row={'event':event}
        for key,value in fields.items():
            if key in ('at','quote_at') and isinstance(value,datetime):row[key]=value.isoformat()
            elif key=='client_key' and re.fullmatch('[a-f0-9]{64}',str(value)):row[key]=value
            elif key=='contract' and re.fullmatch(r'[A-Z0-9. ]{1,32}',str(value)):row[key]=value
            elif key=='reason' and value in ('TARGET','LOSS_LIMIT','MANUAL_CLOSE','TIME_LIMIT'):row[key]=value
            elif key=='error_code' and value in ERROR_CODES:row[key]=value
            elif key in ('bid','ask','limit','lookup_ms','filled','quote_age_ms','order_age_ms',
                         'bid_size','ask_size','entry_average','quantity','target','stop'):
                try:
                    number=Decimal(str(value))
                    if number.is_finite():row[key]=str(number)
                except Exception:pass
        if not self.lock.acquire(blocking=False):self.dropped+=1;return
        try:
            if event=='POSITION_MARK':
                key=row.get('client_key')
                if not key or 'quote_at' not in row:return
                quote=tuple(row.get(k) for k in ('quote_at','bid','ask','bid_size','ask_size','quantity'))
                if self.last_marks.get(key)==quote:return
            else:key=None
            if len(self.pending)>=self.capacity:self.dropped+=1;return
            self.pending.append(row)
            if key:
                if key not in self.last_marks and len(self.last_marks)>=256:
                    self.last_marks.pop(next(iter(self.last_marks)))
                self.last_marks[key]=quote
        finally:self.lock.release()

    def flush(self):
        """Only a diagnostics worker calls this; never while trading holds a lock."""
        with self.lock:
            rows=list(self.pending);self.pending.clear()
        if not rows:return
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            if self.path.exists() and self.path.stat().st_size>=self.max_bytes:
                self.path.replace(self.path.with_suffix('.previous.jsonl'))
            with self.path.open('a',encoding='utf-8') as stream:
                for row in rows:stream.write(json.dumps(row,separators=(',',':'))+'\n')
        except OSError:self.dropped+=len(rows)
