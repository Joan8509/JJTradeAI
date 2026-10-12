"""Gateway Vercel: sesión privada y consulta al radar remoto; sin trading."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError

COOKIE = "__Host-jjtrade"


def settings():
    password = os.environ.get("JJTRADE_APP_PASSWORD", "")
    secret = os.environ.get("JJTRADE_SESSION_SECRET", "")
    if len(password) < 16 or len(secret) < 32:
        raise ValueError("Configura el acceso privado en Vercel antes de usar la web.")
    return password, secret.encode()


def create_session(secret, now=None):
    body = f"{int(time.time() if now is None else now)+28800}:{secrets.token_hex(16)}"
    signature = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{signature}".encode()).decode()


def valid_session(cookie, secret, now=None):
    try:
        jar = SimpleCookie()
        jar.load(cookie or "")
        decoded = base64.urlsafe_b64decode(jar[COOKIE].value).decode()
        expiry, nonce, signature = decoded.split(":")
        body = f"{expiry}:{nonce}"
        return int(time.time() if now is None else now) < int(expiry) and hmac.compare_digest(
            signature, hmac.new(secret, body.encode(), hashlib.sha256).hexdigest())
    except (ValueError, KeyError, UnicodeError, TypeError):
        return False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise URLError("Redirect disabled")


def fetch_snapshot():
    url = os.environ.get("JJTRADE_BACKEND_URL", "")
    key = os.environ.get("JJTRADE_BACKEND_KEY", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or len(key) < 32:
        raise ValueError("Falta conectar el servidor continuo del radar. Vercel por sí solo no mantiene el buscador activo.")
    request = Request(url, headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=8) as response:
            payload = json.loads(response.read(3_000_001))
        if not isinstance(payload, dict) or payload.get("schema") != "jjtrade-bollinger-v1":
            raise ValueError()
        return payload
    except (OSError, ValueError):
        raise ValueError("El servidor del radar no responde. Las señales no pueden considerarse vigentes.") from None


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload, cookie=None):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            _, secret = settings()
            if not valid_session(self.headers.get("Cookie"), secret):
                self.reply(401, {"error": "Inicia sesión para ver tu radar."})
                return
            self.reply(200, fetch_snapshot())
        except ValueError as error:
            self.reply(503, {"error": str(error)})

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and origin != "https://" + self.headers.get("Host", ""):
                self.reply(403, {"error": "Origen no permitido."})
                return
            password, secret = settings()
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                self.reply(400, {"error": "Solicitud inválida."})
                return
            supplied = json.loads(self.rfile.read(length)).get("password", "")
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), password.encode()):
                self.reply(401, {"error": "La contraseña no es correcta."})
                return
            self.reply(200, {"ok": True}, f"{COOKIE}={create_session(secret)}; Path=/; Max-Age=28800; HttpOnly; Secure; SameSite=Strict")
        except (ValueError, AttributeError):
            self.reply(400, {"error": "Revisa la configuración del acceso y la solicitud."})

    def do_DELETE(self):
        self.reply(200, {"ok": True}, f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict")
