"""Independent owner-only OAuth maintenance; no execution or strategy access."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo('America/New_York')
SAFE_CODES = {'AUTHORIZATION_REQUIRED', 'REAUTHORIZATION_REQUIRED', 'RATE_LIMITED',
              'TRANSPORT_FAILURE', 'HTTP_FAILURE', 'INVALID_TOKEN_RESPONSE'}


def check_authorization(store, oauth_factory, client_factory, now, *, previous=None):
    """Refresh ahead of expiry and verify GET independently of a trading signal.

    Five days is a precautionary reminder, not an inferred provider expiry.
    Never reset the original authorization age to hide the need for consent.
    """
    now = now.astimezone(UTC)
    previous = previous or {}
    result = dict(checked_at=now.isoformat(), state='CHECK_FAILED',
                  real_orders_enabled=False, refreshed=False)
    try:
        profile = store.load()
        if (profile.get('real_orders_enabled') is not False or
                profile.get('api_product') != 'MARKET_DATA_ONLY'):
            raise ValueError('READ_ONLY_PROFILE_REQUIRED')
        tokens = profile.get('tokens') or {}
        if not tokens:
            result['state'] = 'AUTHORIZATION_REQUIRED'
            return result
        started = datetime.fromisoformat(tokens['authorization_started_at'])
        expires = datetime.fromisoformat(tokens['expires_at'])
        if started.tzinfo is None or expires.tzinfo is None or started > now:
            raise ValueError('INVALID_TOKEN_METADATA')
        result['authorization_started_at'] = started.isoformat()
        result['renewal_reminder'] = now-started >= timedelta(days=5)
        result['access_expires_at'] = expires.isoformat()
        retry = previous.get('retry_at')
        if retry and now < datetime.fromisoformat(retry):
            result.update(state='BACKOFF', retry_at=retry)
            return result
        oauth = oauth_factory(profile)
        if expires <= now+timedelta(minutes=5):
            oauth.refresh(now)
            result['refreshed'] = True
            result['access_expires_at'] = store.load()['tokens']['expires_at']
        local = now.astimezone(ET)
        # Includes 08:30, 09:00, 09:20 and 09:25 checks before the bell.
        verify = local.weekday() < 5 and (8, 30) <= (local.hour, local.minute) <= (16, 15)
        last = previous.get('last_verified_at')
        if result['refreshed'] or verify or not last:
            quotes = client_factory(oauth).quotes(['AAPL', 'SPY'], now)
            if not all(quotes.get(s) for s in ('AAPL', 'SPY')):
                raise ValueError('INCOMPLETE_QUOTE_RESPONSE')
            result['last_verified_at'] = now.isoformat()
        else:
            result['last_verified_at'] = last
        result['state'] = 'READY'
    except Exception as error:
        code = getattr(error, 'code', None)
        result['state'] = code if code in SAFE_CODES else 'CHECK_FAILED'
        delay = getattr(error, 'retry_after_seconds', None)
        if code == 'RATE_LIMITED':
            result['retry_at'] = (now+timedelta(seconds=max(300, delay or 60))).isoformat()
    return result


def notice_for(result, now):
    """Operational notices have a separate namespace from strategy dedup."""
    state = result['state']
    day = now.astimezone(ET).date().isoformat()
    authorization = result.get('authorization_started_at', 'missing')
    if state in {'AUTHORIZATION_REQUIRED', 'REAUTHORIZATION_REQUIRED'}:
        return f'authorization:{authorization}:{day}', (
            'JJTrade · Acción necesaria: Schwab requiere autorizar de nuevo la app. '
            'Las cotizaciones para operar no están disponibles. Entra al escritorio '
            'RDP de la VPS para renovar. Las órdenes reales siguen deshabilitadas.')
    if state == 'READY' and result.get('renewal_reminder'):
        return f'reminder:{authorization}:{day}', (
            'JJTrade · Mantenimiento preventivo de Schwab: la autorización tiene '
            'cinco días o más. Renueva desde la VPS antes de la próxima apertura. '
            'La conexión responde ahora; este aviso no indica una fecha de caducidad confirmada.')
    if state not in {'READY', 'BACKOFF'}:
        return f'connection:{day}', (
            'JJTrade · Comprobación de Schwab fallida. Revisa el estado de conexión '
            'antes de operar. La supervisión volverá a comprobarlo automáticamente. '
            'Las órdenes reales siguen deshabilitadas.')
    return None
