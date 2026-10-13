"""Conexión privada de Telegram. Nunca incluye el token en diagnósticos."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CONFIG_PATH = Path(__file__).resolve().parent / "exports" / "telegram" / "connection.json"


class TelegramError(ValueError):
    pass


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
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except HTTPError as error:
        messages = {401: "La clave del bot no es válida.", 403: "Abre el bot y pulsa Start; comprueba que no está bloqueado.",
                    409: "Otra aplicación está leyendo este bot. Utiliza un bot exclusivo para JJTrade.",
                    429: "Telegram pide esperar. Inténtalo más tarde."}
        raise TelegramError(messages.get(error.code, "Telegram rechazó la petición. Revisa la conexión.")) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise TelegramError("No se pudo conectar con Telegram. Revisa Internet e inténtalo de nuevo.") from None
    if not result.get("ok"):
        raise TelegramError("Telegram no pudo completar la petición.")
    return result["result"]


def discover(token):
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


def send_message(text, path=CONFIG_PATH, *, reply_markup=None):
    settings = connection(path)
    if not settings:
        raise TelegramError("Primero vincula tu chat.")
    token = os.environ["TELEGRAM_BOT_TOKEN"] if settings.get("token_source") == "ENVIRONMENT" else _protect(base64.b64decode(settings["protected_token"]), decrypt=True).decode()
    payload={"chat_id":settings["chat_id"],"text":text}
    if reply_markup is not None:
        payload['reply_markup']=reply_markup
    return call(token, "sendMessage", **payload)
