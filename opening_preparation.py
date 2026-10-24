"""Warm complete option calendars before the official open; never authorize buys."""
from datetime import datetime,timedelta
import time

from option_contract_selection import select_entry_expiration
from schwab_connection import aware

START_BEFORE_OPEN=timedelta(minutes=4)
STOP_BEFORE_OPEN=timedelta(minutes=2)
REQUEST_SPACING=timedelta(seconds=5)
CALENDAR_AGE=timedelta(minutes=5)  # Same metadata TTL as ManualMarketData.


class OpeningPreparation:
    def __init__(self,workflow,store):
        self.workflow=workflow;self.store=store
        self.prepared={};self.retry_at={};self.next_at=None

    def step(self,plans,*,ready):
        w=self.workflow;now=aware(w.clock())
        if not ready or getattr(w.market_data,'direct_quotes',False) is not True:return
        if self.next_at is not None and now<self.next_at:return
        provider_retry=getattr(w.market_data,'retry_at',None)
        if provider_retry is not None and now<provider_retry:return
        candidates=[]
        for plan in plans:
            opening=aware(datetime.fromisoformat(plan['opens_at']))
            if plan['state']=='ARMED' and opening-START_BEFORE_OPEN<=now<opening-STOP_BEFORE_OPEN:
                for side in ('CALL','PUT'):
                    key=(plan['id'],side)
                    if now<self.prepared.get(key,now) or now<self.retry_at.get(key,now):continue
                    candidates.append((plan,side,key))
        if not candidates:return
        # An existing position or pending order always gets priority over warmup.
        try:
            if w.pending_orders() or w.positions():return
        except Exception:return
        plan,side,key=candidates[0]
        now=aware(w.clock())
        if now>=aware(datetime.fromisoformat(plan['opens_at']))-STOP_BEFORE_OPEN:return
        self.next_at=now+REQUEST_SPACING
        started=time.monotonic()
        try:
            market=w.market_data.get_chain(plan['symbol'],side,now,force=False)
            if (market.symbol,market.side)!=(plan['symbol'],side):raise ValueError
            select_entry_expiration(market.expirations,now)
            expiry=market.fetched_at+CALENDAR_AGE
            if not market.fetched_at<=aware(w.clock())<expiry:raise ValueError
            self.prepared[key]=expiry
            self.store.decision(plan['id'],'PREOPEN_CATALOG_READY',w.clock(),details=dict(
                side=side,calendar_expires_at=expiry.isoformat(),
                preparation_ms=round((time.monotonic()-started)*1000,3)))
        except Exception as error:
            self.retry_at[key]=aware(w.clock())+timedelta(seconds=15)
            allowed={'MARKET_DATA_COOLDOWN','MARKET_DATA_UNAVAILABLE','AUTHORIZATION_REQUIRED',
                     'REAUTHORIZATION_REQUIRED','RATE_LIMITED','TRANSPORT_FAILURE','HTTP_FAILURE','OPTION_CHAIN_INVALID'}
            code=str(error) if str(error) in allowed else 'CHECK_REQUIRED'
            self.store.decision(plan['id'],'PREOPEN_CATALOG_FAILED',w.clock(),reason=code,details=dict(side=side))
