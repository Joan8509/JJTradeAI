"""Conexión privada de Telegram. Nunca incluye el token en diagnósticos."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
import re
import ssl
from functools import lru_cache
import certifi
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CONFIG_PATH = Path(__file__).resolve().parent / "exports" / "telegram" / "connection.json"


class TelegramError(ValueError):
    def __init__(self,message,*,retry_after_seconds=None,code='TELEGRAM_ERROR',operation=None):
        super().__init__(message)
        self.retry_after_seconds=retry_after_seconds
        self.code=code
        self.operation=operation


@lru_cache(maxsize=1)
def _tls_context():
    # Keep system trust and strict hostname/certificate checks, supplementing
    # missing roots with the installed Mozilla CA bundle. Never trust a peer's
    # self-signed certificate or disable verification to make a request work.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data, *, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    method = library.CryptUnprotectData if decrypt else library.CryptProtectData
    method.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    method.restype = wintypes.BOOL
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise TelegramError("Windows no pudo proteger o leer la clave. Vuelve a conectar el bot.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(target.data, ctypes.c_void_p))


def call(token, method, **payload):
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise TelegramError("La clave no tiene el formato de BotFather. Copia la clave completa.")
    request = Request(f"https://api.telegram.org/bot{token}/{method}",
                      data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    operation=method if method in {'getUpdates','getWebhookInfo','getMe','getChat','sendMessage',
        'answerCallbackQuery','editMessageText','editMessageReplyMarkup'} else 'TELEGRAM_API'
    try:
        with urlopen(request, timeout=10, context=_tls_context()) as response:
            result = json.load(response)
    except HTTPError as error:
        messages = {401: "La clave del bot no es válida.", 403: "Abre el bot y pulsa Start; comprueba que no está bloqueado.",
                    409: "Otra aplicación está leyendo este bot. Utiliza un bot exclusivo para JJTrade.",
                    429: "Telegram pide esperar. Inténtalo más tarde."}
        delay=None
        if error.code==429:
            delay=60
            try:
                value=json.load(error).get('parameters',{}).get('retry_after')
                if type(value) is int and value>0:delay=value
            except (ValueError,OSError,AttributeError,TypeError):pass
        code='HTTP_'+str(error.code) if error.code in (400,401,403,409,429) else 'HTTP_FAILURE'
        raise TelegramError(messages.get(error.code, "Telegram rechazó la petición. Revisa la conexión."),retry_after_seconds=delay,code=code,operation=operation) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise TelegramError("No se pudo conectar con Telegram. Revisa Internet e inténtalo de nuevo.",code='TRANSPORT_FAILURE',operation=operation) from None
    if not result.get("ok"):
        raise TelegramError("Telegram no pudo completar la petición.",code='API_REJECTED',operation=operation)
    return result["result"]


def discover(token):
    # Hold the same exclusive reader lock throughout discovery; never race the
    # operational callback poller or consume its queue from this settings screen.
    from telegram_manual_controls import poller_lock
    try:
        with poller_lock():
            return _discover(token)
    except RuntimeError:
        raise TelegramError('El bot está atendiendo operaciones. No se iniciará otro lector de Telegram.') from None


def _discover(token):
    bot = call(token, "getMe")
    updates = call(token, "getUpdates", timeout=0, limit=100)
    chats = {}
    for update in updates:
        message = update.get("message", {})
        chat = message.get("chat", {})
        if chat.get("type") == "private" and not message.get("from", {}).get("is_bot"):
            chats[str(chat["id"])] = {"id": str(chat["id"]), "name": chat.get("first_name", "Mi chat"),
                                      "username": chat.get("username", "")}
    if not chats:
        raise TelegramError("Envía «hola» al chat de tu bot en Telegram y vuelve a buscar tu chat.")
    return bot["username"], list(chats.values())


def save_connection(token, bot_name, chat, path=CONFIG_PATH):
    path = Path(path)
    data = {"protected_token": base64.b64encode(_protect(token.encode())).decode(),
            "bot_name": bot_name, "chat_id": chat["id"], "chat_name": chat["name"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def connection(path=CONFIG_PATH):
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        return {"token_source": "ENVIRONMENT", "bot_name": os.environ.get("TELEGRAM_BOT_NAME", "JJTrade"),
                "chat_id": os.environ["TELEGRAM_CHAT_ID"], "chat_name": "Chat del servidor"}
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise TelegramError("La conexión guardada no se puede leer. Conecta el bot de nuevo.") from None


def send_test(path=CONFIG_PATH):
    settings = connection(path)
    if not settings:
        raise TelegramError("Primero vincula tu chat.")
    return send_message("🔔 JJTrade · Prueba de conexión\nTu teléfono recibe mensajes de la app.\nEste es un mensaje de prueba, no una señal de mercado.", path)


def local_readiness(path=CONFIG_PATH):
    """Validate local access without sending messages or exposing credentials."""
    try:
        settings = connection(path)
        if not settings or not settings.get('chat_id'):
            return 'SIN_CONEXION'
        token = (os.environ.get('TELEGRAM_BOT_TOKEN', '') if settings.get('token_source') == 'ENVIRONMENT'
                 else _protect(base64.b64decode(settings['protected_token']), decrypt=True).decode())
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
            return 'CLAVE_INVALIDA'
        return 'LISTO_LOCAL'
    except (TelegramError, KeyError, ValueError, OSError, UnicodeError):
        return 'CLAVE_NO_DISPONIBLE'


def send_message(text, path=CONFIG_PATH, *, reply_markup=None):
    settings = connection(path)
    if not settings:
        raise TelegramError("Primero vincula tu chat.")
    token = os.environ["TELEGRAM_BOT_TOKEN"] if settings.get("token_source") == "ENVIRONMENT" else _protect(base64.b64decode(settings["protected_token"]), decrypt=True).decode()
    payload={"chat_id":settings["chat_id"],"text":text}
    if reply_markup is not None:
        payload['reply_markup']=reply_markup
    return call(token, "sendMessage", **payload)
