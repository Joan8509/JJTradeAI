"""Lightweight notification controls; never loads a broker, vault or data client."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit,urlunsplit,urlencode

ROOT=Path(__file__).resolve().parent
STATUS=ROOT/'exports/private_runtime/telegram_manual.status.json'
LOCK=ROOT/'exports/private_runtime/telegram_manual.poller.lock'


def _read_status(path):
    # Windows may briefly deny opening a receipt while its writer replaces it.
    # Retry only file access, at most 20ms; freshness is still checked afterward.
    for attempt in range(3):
        try:return json.loads(Path(path).read_text(encoding='utf-8'))
        except PermissionError:
            if attempt==2:raise
            time.sleep(.01)


def preparation_callback(symbol,side,candle):
    if not re.fullmatch('[A-Z][A-Z0-9.]{0,7}',symbol) or side not in ('CALL','PUT'):
        raise ValueError('SIGNAL_INVALID')
    stamp=datetime.fromisoformat(candle)
    if stamp.tzinfo is None:raise ValueError('SIGNAL_CLOCK_INVALID')
    return f"jj:b:{symbol}:{side}:{stamp.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"


def companion_ready(*,path=STATUS,now=None):
    try:
        status=_read_status(path)
        age=(now or datetime.now(timezone.utc))-datetime.fromisoformat(status['heartbeat'])
        return (status.get('state')=='READY' and status.get('real_orders_enabled') is False
                and timedelta(0)<=age<=timedelta(seconds=10))
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return False


def entry_monitor_ready(*,path=STATUS,now=None):
    """Direct authenticated UI entries need the exit monitor, not getUpdates."""
    try:
        status=_read_status(path)
        age=(now or datetime.now(timezone.utc))-datetime.fromisoformat(status['heartbeat'])
        return (status.get('state') in ('READY','BOT_NOT_READY') and status.get('monitor_ready') is True
                and status.get('real_orders_enabled') is False and timedelta(0)<=age<=timedelta(seconds=10))
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return False


def preparation_button(symbol,side,candle,*,path=STATUS,now=None,base_url=None):
    try:
        # This callback is navigation/preparation, never an order. Keep it
        # available through temporary monitor/poller/staleness blocks. A blocked
        # poller cannot answer callbacks, so use a read-only Web App then.
        # Actual preparations and buys still require the unchanged fresh gate.
        status=_read_status(path)
        if (status.get('real_orders_enabled') is not False or
                status.get('state') not in ('READY','BOT_NOT_READY','MONITOR_BLOCKED')):return None
        callback=preparation_callback(symbol,side,candle)
        from manual_trade_links import app_url,validate_app_url
        parts=urlsplit(validate_app_url(base_url or app_url()))
        if parts.scheme!='https':return None
        ready=entry_monitor_ready(path=path,now=now)
        reference={'entry' if ready else 'watch':symbol,'side':side,
            'candle':datetime.fromisoformat(candle).astimezone(timezone.utc).isoformat()}
        return {'text':'Simulación · elegir compra' if ready else 'Ver simulación · solo consulta','web_app':{'url':
            urlunsplit((parts.scheme,parts.netloc,'/telegram/','',''))+'#'+urlencode(reference)}}
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return None


@contextmanager
def poller_lock(path=LOCK):
    import msvcrt
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('BOT_READER_ALREADY_RUNNING') from None
        try:yield
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
