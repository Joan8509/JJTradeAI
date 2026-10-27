"""Sanitized, authenticated preflight for the queue editor; no orders or alerts."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time


class BackgroundConnectionProbe:
    """One read-only probe in flight; UI polling never waits for provider I/O.

    Stores only the sanitized receipt, never a market client or credentials.
    The queue still performs its own synchronous fresh check before any write.
    """
    def __init__(self, probe=None, *, executor=None, monotonic=time.monotonic):
        self.probe = probe or probe_queue_connection
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='queue-preflight')
        self.monotonic = monotonic
        self.lock = Lock()
        self.future = None
        self.result = {'state': 'CHECKING', 'checked_at': None}
        self.expires = 0
        self.generation = 0

    def remember(self, result):
        with self.lock:
            self.generation += 1
            self.result = dict(result)
            self.expires = self.monotonic() + 30

    def poll(self, *, force=False):
        with self.lock:
            if self.future is not None and self.future.done():
                if self.future_generation == self.generation:
                    try:
                        self.result = self.future.result()
                    except Exception:
                        self.result = {'state': 'UNAVAILABLE', 'checked_at': None}
                    # A completed future may only be collected when a user
                    # returns to this tab. Do not cache an already old receipt
                    # for another 30 seconds from that return.
                    try:
                        age = (datetime.now(timezone.utc)-datetime.fromisoformat(
                            self.result['checked_at'])).total_seconds()
                        remaining = max(0, min(30, 30-age))
                    except (ValueError,TypeError,KeyError):
                        remaining = 30
                    self.expires = self.monotonic() + remaining
                self.future = None
            if force:
                self.expires = 0
            if self.future is None and self.monotonic() >= self.expires:
                self.future_generation = self.generation
                self.future = self.executor.submit(self.probe)
            return dict(self.result)


def probe_queue_connection(*, market_factory=None, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    if market_factory is None:
        from manual_trade_service import owner_market_data
        market_factory = owner_market_data
    result = {'state': 'UNAVAILABLE', 'checked_at': None}
    try:
        raw = market_factory().client.quotes(['AAPL', 'SPY'], clock())
        if all(isinstance(raw.get(s), dict) and raw[s] for s in ('AAPL', 'SPY')):
            result['state'] = 'CONNECTED'
    except Exception as error:
        code = getattr(error, 'code', None)
        if code is None and str(error) == 'PRIVATE_MARKET_CONFIG_UNAVAILABLE':
            code = 'PRIVATE_MARKET_CONFIG_UNAVAILABLE'
        result['state'] = 'AUTHORIZATION_REQUIRED' if code in {
            'AUTHORIZATION_REQUIRED', 'REAUTHORIZATION_REQUIRED'} else 'UNAVAILABLE'
        result['reason'] = code if code in {
            'AUTHORIZATION_REQUIRED','REAUTHORIZATION_REQUIRED',
            'PRIVATE_MARKET_CONFIG_UNAVAILABLE','TRANSPORT_FAILURE',
            'HTTP_FAILURE','RATE_LIMITED'} else 'CHECK_FAILED'
    result['checked_at'] = clock().isoformat()
    return result


def connection_is_recent(result, now, *, seconds=30):
    try:
        checked = datetime.fromisoformat(result['checked_at'])
        return (result['state'] == 'CONNECTED' and checked.tzinfo is not None and
                0 <= (now-checked).total_seconds() <= seconds)
    except (ValueError, TypeError, KeyError):
        return False
