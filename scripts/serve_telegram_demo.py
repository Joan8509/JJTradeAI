"""Static visual preview only. No broker, SQLite, credentials or trading API."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
PORT=8185


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def setup(self):
        super().setup();self.connection.settimeout(10)

    def respond(self,status,data,kind='application/json; charset=utf-8'):
        if not isinstance(data,bytes):data=json.dumps(data).encode()
        self.send_response(status)
        for key,value in {'Content-Type':kind,'Content-Length':str(len(data)),
            'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'; script-src 'self' https://telegram.org; "
                "style-src 'self'; connect-src 'none'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"}.items():
            self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(data)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path.startswith('/telegram-demo/'):path=path[len('/telegram-demo'):]
        if path=='/health':
            self.respond(200,dict(mode='DEMO_VISUAL_ONLY',real_orders_enabled=False,simulation_orders_enabled=False));return
        files={'/':('web/telegram_demo/index.html','text/html; charset=utf-8'),
               '/demo.js':('web/telegram_demo/demo.js','text/javascript; charset=utf-8'),
               '/demo.css':('web/telegram_demo/demo.css','text/css; charset=utf-8'),
               '/style.css':('web/telegram_manual/style.css','text/css; charset=utf-8')}
        if path not in files:self.respond(404,dict(error='NOT_FOUND'));return
        name,kind=files[path]
        try:self.respond(200,(ROOT/name).read_bytes(),kind)
        except OSError:self.respond(503,dict(error='STATIC_UNAVAILABLE'))

    def do_HEAD(self):self.do_GET()
    def do_POST(self):self.respond(405,dict(error='DEMO_HAS_NO_ACTIONS'))
    do_PUT=do_POST
    do_DELETE=do_POST
    do_PATCH=do_POST
    do_OPTIONS=do_POST


def main():
    server=ThreadingHTTPServer(('127.0.0.1',PORT),DemoHandler)
    server.daemon_threads=True
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
