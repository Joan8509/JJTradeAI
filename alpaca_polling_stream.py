"""Batched REST minute bars for watchlists beyond Basic websocket capacity."""
from datetime import datetime, timedelta, timezone
from threading import Event
from urllib.parse import urlencode
from urllib.request import Request

from alpaca_market_data import _default_transport
from live_market import MarketBar, normalize_minute_bars
import pandas as pd


class AlpacaPollingBarStream:
    def __init__(self, config, *, transport=_default_transport, now=None, interval=30, continuity=None):
        self.config = config
        self.transport = transport
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.interval = interval
        self.continuity = continuity
        self.finished = Event()
        self.seen = {}

    def poll(self, symbols, on_bar):
        symbols = sorted(set(symbols))
        params = urlencode({'symbols': ','.join(symbols), 'feed': self.config.feed})
        payload = self.transport(Request(self.config.base_url+'/v2/stocks/bars/latest?'+params,
            headers={'APCA-API-KEY-ID':self.config.api_key,
                     'APCA-API-SECRET-KEY':self.config.api_secret}))
        now = self.now()
        delivered = 0
        for symbol, row in (payload.get('bars') or {}).items():
            if symbol not in symbols:
                continue
            stamp = datetime.fromisoformat(row['t'].replace('Z', '+00:00'))
            # Never turn an old or still open minute into a fresh alert.
            if not timedelta(minutes=1) <= now-stamp <= timedelta(minutes=3):
                continue
            if stamp <= self.seen.get(symbol, datetime.min.replace(tzinfo=timezone.utc)):
                continue
            frame = normalize_minute_bars(pd.DataFrame([dict(date=stamp, open=row['o'],
                high=row['h'], low=row['l'], close=row['c'], volume=row['v'])]))
            if self.continuity:
                latest = self.continuity.store.latest_timestamp(symbol=symbol,
                    provider=self.continuity.provider_name, feed=self.continuity.feed)
                if latest and stamp-latest > timedelta(minutes=1):
                    # Recover skipped minute bars before evaluating the latest partial candle.
                    self.continuity.recover(symbol, end=stamp-timedelta(microseconds=1))
            validated = frame.iloc[0]
            on_bar(MarketBar(symbol=symbol, timestamp=stamp, open=float(validated.open),
                high=float(validated.high), low=float(validated.low), close=float(validated.close),
                volume=float(validated.volume)))
            self.seen[symbol] = stamp
            delivered += 1
        return delivered

    def run(self, symbols, on_bar, *, on_error=None, on_status=None):
        if on_status:
            on_status('CONECTADO')
        while not self.finished.is_set():
            self.poll(symbols, on_bar)
            self.finished.wait(self.interval)

    def stop(self):
        self.finished.set()
