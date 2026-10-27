"""Bounded private exit diagnostics. Trading only enqueues; disk I/O is separate."""
from collections import deque
from datetime import datetime
from decimal import Decimal
import json,re
from pathlib import Path
from threading import Lock

class ObservationJournal:
    EVENTS={'LOOKUP_STARTED','LOOKUP_FINISHED','LOOKUP_FAILED','POST_ORDER_QUOTE_REQUIRED',
            'BID_BELOW_LIMIT','NO_AVAILABLE_LIQUIDITY','MATCH_APPLIED','EXIT_ORDER_REGISTERED'}
    def __init__(self,path,*,capacity=256,max_bytes=2_000_000):
        self.path=Path(path);self.capacity=capacity;self.max_bytes=max_bytes
        self.pending=deque();self.lock=Lock();self.dropped=0

    def record(self,event,**fields):
        if event not in self.EVENTS:return
        row={'event':event}
        for key,value in fields.items():
            if key in ('at','quote_at') and isinstance(value,datetime):row[key]=value.isoformat()
            elif key=='client_key' and re.fullmatch('[a-f0-9]{64}',str(value)):row[key]=value
            elif key=='contract' and re.fullmatch(r'[A-Z0-9. ]{1,32}',str(value)):row[key]=value
            elif key=='reason' and value in ('TARGET','LOSS_LIMIT','MANUAL_CLOSE','TIME_LIMIT'):row[key]=value
            elif key in ('bid','ask','limit','lookup_ms','filled','quote_age_ms','order_age_ms'):
                try:
                    number=Decimal(str(value))
                    if number.is_finite():row[key]=str(number)
                except Exception:pass
        if not self.lock.acquire(blocking=False):self.dropped+=1;return
        try:
            if len(self.pending)>=self.capacity:self.dropped+=1;return
            self.pending.append(row)
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
