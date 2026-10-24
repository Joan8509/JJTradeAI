"""Schwab OAuth and allowlisted read-only resources. No order mutations exist.

Wire formats are covered by local fixtures; verify the authorized Schwab API
specification and real read-only responses before claiming account integration.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import base64
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import ssl
from threading import Lock
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

UTC = timezone.utc
API = 'https://api.schwabapi.com'


class SchwabError(RuntimeError):
    def __init__(self, code, *, http_status=None, retry_after_seconds=None):
        self.code = code
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)  # Never interpolate bodies, URLs, headers or tokens.


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('Timezone-aware datetime required')
    return value.astimezone(UTC)


class SchwabTransport:
    """TLS-verified, no redirects, no automatic retries; shared rate spacing."""
    def __init__(self, *, interval_seconds=1.0, opener=None, clock=time.monotonic,
                 sleeper=time.sleep):
        if interval_seconds < 1:
            raise ValueError('Minimum request spacing is one second')
        self.interval = interval_seconds
        self.clock, self.sleeper = clock, sleeper
        self.lock = Lock()
        self.next_request = 0.0
        if opener is None:
            context = ssl.create_default_context()
            import certifi
            context.load_verify_locations(cafile=certifi.where())
            opener = build_opener(_NoRedirect(), HTTPSHandler(context=context))
        self.opener = opener

    def request(self, method, path, *, headers=None, params=None, form=None):
        if not isinstance(path, str) or any(c in path for c in ('?', '#', '\\', '..', '\r', '\n')):
            raise SchwabError('RESOURCE_NOT_ALLOWED')
        allowed = (method == 'POST' and path == '/v1/oauth/token') or (
            method == 'GET' and (path in ('/trader/v1/accounts/accountNumbers',
                '/marketdata/v1/chains', '/marketdata/v1/quotes') or re.fullmatch(
                r'/trader/v1/accounts/[A-Za-z0-9_-]+(?:/orders(?:/[0-9]+)?)?', path)))
        if not allowed or (method == 'GET' and form is not None):
            raise SchwabError('RESOURCE_NOT_ALLOWED')
        with self.lock:
            self.sleeper(max(0.0, self.next_request-self.clock()))
            self.next_request = self.clock()+self.interval
            request = Request(API+path+('?' + urlencode(params) if params else ''),
                data=urlencode(form).encode() if form is not None else None,
                headers=headers or {}, method=method)
            failure = None
            try:
                with self.opener.open(request, timeout=15) as response:
                    return json.load(response)
            except HTTPError as error:
                delay = None
                if error.code == 429:
                    try:
                        delay = max(1, int(error.headers.get('Retry-After', '60')))
                    except ValueError:
                        try:
                            delay = max(1, int((parsedate_to_datetime(error.headers['Retry-After'])-
                                datetime.now(UTC)).total_seconds())+1)
                        except (ValueError, TypeError, KeyError):
                            delay = 60
                    self.next_request = max(self.next_request, self.clock()+delay)
                failure = SchwabError('REAUTHORIZATION_REQUIRED' if error.code == 401 or
                    (path == '/v1/oauth/token' and error.code == 400) else
                    'RATE_LIMITED' if error.code == 429 else 'HTTP_FAILURE',
                    http_status=error.code, retry_after_seconds=delay)
                error.close()
            except Exception:
                failure = SchwabError('TRANSPORT_FAILURE')
            # Raise outside except: secret-bearing HTTP exceptions are not chained.
            raise failure from None


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    callback_url: str

    def __post_init__(self):
        url = urlsplit(self.callback_url)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c in self.callback_url for c in '\r\n')):
            raise ValueError('Exact registered HTTPS callback without query required')
        if not self.client_id or not self.client_secret or any(
                c in self.client_id+self.client_secret for c in '\r\n'):
            raise ValueError('OAuth configuration incomplete')


class EncryptedSchwabStore:
    """Use only inside the existing Administrator-only DPAPI directory."""
    def __init__(self, path=None):
        root = Path(__file__).resolve().parent/'exports/private_runtime'
        self.path = Path(path).resolve() if path is not None else root/'schwab.dpapi'
        if self.path.parent != root.resolve() or self.path.name != 'schwab.dpapi':
            raise ValueError('Schwab vault must use the protected private directory')

    @staticmethod
    def _owner():
        import vps_private_runtime as runtime
        sid = runtime.current_sid()
        if not sid.endswith('-500'):
            raise SchwabError('DPAPI_OWNER_REQUIRED')
        return sid

    def load(self):
        from telegram_alerts import _protect
        sid = self._owner()
        data = json.loads(_protect(self.path.read_bytes(), decrypt=True).decode())
        if data.get('owner_sid') != sid or data.get('format') != 1:
            raise SchwabError('VAULT_IDENTITY_MISMATCH')
        return data

    def save(self, value):
        from telegram_alerts import _protect
        sid = self._owner()
        if not self.path.parent.is_dir():
            raise SchwabError('PROTECTED_DIRECTORY_REQUIRED')
        value = dict(value, owner_sid=sid, format=1)
        ciphertext = _protect(json.dumps(value).encode(), decrypt=False)
        temporary = self.path.with_name(self.path.name+'.tmp')
        with temporary.open('wb') as output:
            output.write(ciphertext)
            output.flush()
            import os
            os.fsync(output.fileno())
        temporary.replace(self.path)

    def locked(self):
        """Serialize state/code consumption and refresh across processes."""
        from contextlib import contextmanager
        @contextmanager
        def guard():
            import msvcrt
            with self.path.with_suffix('.lock').open('a+b') as lock:
                lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                yield
        return guard()


class SchwabOAuth:
    def __init__(self, config, store, *, transport=None):
        self.config, self.store = config, store
        self.transport = transport or SchwabTransport()

    def begin(self, now):
        now = aware(now)
        state = secrets.token_urlsafe(32)
        with self.store.locked():
            value = self.store.load()
            value['authorization'] = {'state_digest': hashlib.sha256(state.encode()).hexdigest(),
                                      'expires_at': (now+timedelta(minutes=5)).isoformat()}
            self.store.save(value)
        return API+'/v1/oauth/authorize?'+urlencode({'client_id': self.config.client_id,
            'redirect_uri': self.config.callback_url, 'response_type': 'code', 'state': state}), state

    def complete(self, callback_url, browser_state, now):
        now = aware(now)
        received, expected = urlsplit(callback_url), urlsplit(self.config.callback_url)
        if (received.scheme, received.netloc, received.path) != (expected.scheme, expected.netloc, expected.path):
            raise SchwabError('CALLBACK_MISMATCH')
        if received.fragment:
            raise SchwabError('CALLBACK_MISMATCH')
        query = parse_qs(received.query, keep_blank_values=True)
        if any(len(query.get(key, [])) != 1 for key in ('code', 'state')) or query.get('error'):
            raise SchwabError('AUTHORIZATION_DENIED')
        state, code = query['state'][0], query['code'][0]
        if not code or not browser_state or not hmac.compare_digest(state, browser_state):
            raise SchwabError('OAUTH_STATE_MISMATCH')
        with self.store.locked():
            value = self.store.load()
            authorization = value.get('authorization', {})
            if (not authorization or now >= datetime.fromisoformat(authorization['expires_at']) or
                    not hmac.compare_digest(hashlib.sha256(state.encode()).hexdigest(),
                                            authorization['state_digest'])):
                raise SchwabError('OAUTH_STATE_EXPIRED_OR_USED')
            del value['authorization']
            self.store.save(value)  # Consume BEFORE network; no replay on timeout.
            tokens = self._exchange({'grant_type': 'authorization_code', 'code': code,
                                     'redirect_uri': self.config.callback_url})
            value['tokens'] = self._bundle(tokens, now, previous=None)
            self.store.save(value)

    def _exchange(self, form):
        basic = base64.b64encode((self.config.client_id+':'+self.config.client_secret).encode()).decode()
        return self.transport.request('POST', '/v1/oauth/token', headers={
            'Authorization': 'Basic '+basic, 'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'}, form=form)

    @staticmethod
    def _bundle(payload, now, previous):
        lifetime = payload.get('expires_in')
        if (payload.get('token_type', '').lower() != 'bearer' or
                type(lifetime) is not int or lifetime <= 0 or not payload.get('access_token')):
            raise SchwabError('INVALID_TOKEN_RESPONSE')
        refresh = payload.get('refresh_token') or (previous or {}).get('refresh_token')
        if not isinstance(refresh, str) or not refresh:
            raise SchwabError('INVALID_TOKEN_RESPONSE')
        return {'access_token': payload['access_token'], 'refresh_token': refresh,
                'expires_at': (now+timedelta(seconds=lifetime)).isoformat(),
                'authorization_started_at': (previous or {}).get('authorization_started_at', now.isoformat())}

    def access(self, now):
        now = aware(now)
        with self.store.locked():
            value = self.store.load()
            tokens = value.get('tokens')
            if not tokens:
                raise SchwabError('AUTHORIZATION_REQUIRED')
            if now+timedelta(seconds=60) < datetime.fromisoformat(tokens['expires_at']):
                return tokens['access_token']
            return self._refresh_value(value,now)

    def _refresh_value(self,value,now):
        # Caller holds the owner-store lock. No invented clock or expiry rewrite.
        tokens=value.get('tokens')
        if not tokens:raise SchwabError('AUTHORIZATION_REQUIRED')
        updated=self._exchange({'grant_type':'refresh_token','refresh_token':tokens['refresh_token']})
        value['tokens']=self._bundle(updated,now,previous=tokens)
        self.store.save(value) # Persist rotation before returning the new access token.
        return value['tokens']['access_token']

    def refresh(self,now):
        """Explicit owner verification, using the same path as automatic refresh."""
        with self.store.locked():return self._refresh_value(self.store.load(),aware(now))


class SchwabReadOnlyClient:
    def __init__(self, oauth, *, transport=None):
        self.oauth = oauth
        self.transport = transport or oauth.transport

    def _get(self, path, now, **params):
        return self.transport.request('GET', path, headers={
            'Authorization': 'Bearer '+self.oauth.access(now), 'Accept': 'application/json'}, params=params)

    def accounts(self, now):
        return self._get('/trader/v1/accounts/accountNumbers', now)

    @staticmethod
    def _account(account_hash):
        if not isinstance(account_hash, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', account_hash):
            raise ValueError('Explicit account selection required')
        return '/trader/v1/accounts/'+account_hash

    def positions(self, account_hash, now):
        return self._get(self._account(account_hash), now, fields='positions')

    def orders(self, account_hash, start, end, now):
        if aware(end) < aware(start):
            raise ValueError('Invalid order observation window')
        return self._get(self._account(account_hash)+'/orders', now,
                         fromEnteredTime=aware(start).isoformat(), toEnteredTime=aware(end).isoformat())

    def order(self, account_hash, order_id, now):
        if not re.fullmatch(r'[0-9]+', str(order_id)):
            raise ValueError('Invalid order identity')
        return self._get(self._account(account_hash)+'/orders/'+str(order_id), now)

    def chain(self, symbol, side, expiration_from, expiration_to, now):
        if side not in ('CALL', 'PUT') or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,7}', symbol):
            raise ValueError('Invalid contract search')
        if expiration_to < expiration_from:
            raise ValueError('Invalid expiration range')
        return self._get('/marketdata/v1/chains', now, symbol=symbol, contractType=side,
            strategy='SINGLE', range='ALL', includeUnderlyingQuote='true',
            fromDate=expiration_from.isoformat(), toDate=expiration_to.isoformat())

    def quotes(self, symbols, now):
        if not symbols or len(symbols) > 50 or any(not isinstance(s, str) or not s or '\n' in s for s in symbols):
            raise ValueError('Invalid quote request')
        return self._get('/marketdata/v1/quotes', now, symbols=','.join(symbols))

    def full_chain(self, symbol, side, now):
        """Unbounded listed expirations for selection; never infer from a short window."""
        if side not in ('CALL', 'PUT') or not re.fullmatch(r'[A-Z][A-Z0-9.]{0,7}', symbol):
            raise ValueError('Invalid contract search')
        return self._get('/marketdata/v1/chains', now, symbol=symbol, contractType=side,
            strategy='SINGLE', range='ALL', includeUnderlyingQuote='true')


class DisabledLiveExecution:
    """A code-level stop, unaffected by environment flags or service gates."""
    def dispatch(self, *args, **kwargs):
        raise SchwabError('REAL_ORDERS_DISABLED')
