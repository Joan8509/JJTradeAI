"""Signal links open a review screen; GET requests never place orders."""
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

CONFIG = Path(__file__).resolve().parent/'exports/telegram/app_link.json'


def validate_app_url(value):
    parts=urlsplit(value.strip())
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Introduce la direccion http o https de JJTrade, sin claves.')
    host=parts.hostname.lower()
    if host in ('localhost','0.0.0.0','::'):
        raise ValueError('Esa direccion apunta a la PC; usa la direccion que abre desde tu telefono.')
    try:
        address=ipaddress.ip_address(host)
    except ValueError:
        address=None
    if address and (address.is_loopback or address.is_unspecified):
        raise ValueError('La direccion debe abrir desde tu telefono, no localhost.')
    _=parts.port
    if any(key.lower() in ('token','key','secret','password','access_token','api_key','apikey','client_secret') for key,_ in parse_qsl(parts.query)):
        raise ValueError('La direccion de la app no debe incluir claves ni tokens.')
    return urlunsplit((parts.scheme,parts.netloc,parts.path,parts.query,''))


def save_app_url(value):
    url=validate_app_url(value)
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    temporary=CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps({'url':url}),encoding='utf-8')
    temporary.replace(CONFIG)
    return url


def app_url():
    try:
        value=os.getenv('JJTRADE_APP_URL') or json.loads(CONFIG.read_text())['url']
        return validate_app_url(value)
    except (OSError,ValueError,KeyError):
        return None


def signal_link(symbol,signal,source_time,*,base_url=None):
    url=base_url or app_url()
    if not url:
        return None
    parts=urlsplit(validate_app_url(url))
    query={key:value for key,value in parse_qsl(parts.query) if key not in ('operar','lado','senal')}
    query.update(operar=symbol,lado='CALL' if signal['side']=='SUPERIOR' else 'PUT',senal=source_time.isoformat())
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),''))
