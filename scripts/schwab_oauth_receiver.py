"""Private HTTP backend for the Windows loopback TLS receiver; never auto-started.

No request logging, no tokens in responses, cookie-bound single-use state.
The registered callback and HTTPS routing must be confirmed before deployment.
"""
from datetime import datetime, timezone
import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schwab_connection import EncryptedSchwabStore, OAuthConfig, SchwabOAuth

LOCAL_CALLBACK = 'https://127.0.0.1:8182/schwab/callback'
BACKEND_PORT = 8183


def handler_for(oauth=None):
    callback = urlsplit(oauth.config.callback_url if oauth else LOCAL_CALLBACK)
    callback_path = callback.path or '/'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, body, **headers):
            self.send_response(code)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
            for key, value in headers.items():
                self.send_header(key.replace('_', '-'), value)
            payload = body.encode('utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload)

        def do_GET(self):
            if self.client_address[0] != '127.0.0.1' or self.headers.get('Host') != callback.netloc:
                self._reply(403, 'Acceso no permitido.'); return
            path = urlsplit(self.path)
            if len(self.path) > 8192:
                self._reply(400, 'Solicitud no válida.'); return
            try:
                if path.path == '/schwab/health' and not path.query:
                    self._reply(200, 'LOCAL_RECEIVER_READY; real_orders_enabled=false; authorization_enabled='
                                + ('true' if oauth else 'false'))
                elif oauth is None:
                    self._reply(503, 'Solo comprobacion local. Autorizacion deshabilitada.')
                elif path.path == '/schwab/start' and not path.query:
                    location, state = oauth.begin(datetime.now(timezone.utc))
                    self._reply(302, 'Continúa en Schwab.', Location=location,
                        Set_Cookie='jj_schwab_state='+state+'; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=300')
                elif path.path == callback_path:
                    cookies = SimpleCookie(self.headers.get('Cookie', ''))
                    cookie = cookies.get('jj_schwab_state')
                    oauth.complete(oauth.config.callback_url+('?' + path.query if path.query else ''),
                                   cookie.value if cookie else None, datetime.now(timezone.utc))
                    self._reply(200, 'Cuenta autorizada para comprobación. Órdenes reales deshabilitadas.',
                        Set_Cookie='jj_schwab_state=; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
                else:
                    self._reply(404, 'Ruta no disponible.')
            except Exception:
                self._reply(409, 'Autorización no completada. Inicia un flujo nuevo; no compartas la URL de retorno.')

    return Handler


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # Never emit callback URLs/code or handler tracebacks.


def main():
    parser = argparse.ArgumentParser(description='Local backend; no request logging.')
    parser.add_argument('--health-only', action='store_true')
    args = parser.parse_args()
    oauth = None
    if not args.health_only:
        store = EncryptedSchwabStore()
        profile = store.load()
        config = OAuthConfig(**profile['oauth_config'])
        if (config.callback_url != LOCAL_CALLBACK or profile.get('real_orders_enabled') is not False
                or profile.get('api_product') != 'MARKET_DATA_ONLY'):
            raise ValueError('Reviewed local market-data configuration required')
        oauth = SchwabOAuth(config, store)
    server = QuietServer(('127.0.0.1', BACKEND_PORT), handler_for(oauth))
    server.serve_forever(poll_interval=.5)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit(2)
