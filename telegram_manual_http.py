"""Loopback-only Mini App HTTP bridge. GET/HEAD never place orders."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from telegram_manual import TelegramManualError

STATIC=Path(__file__).resolve().parent/'web/telegram_manual'


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,handler):
        if address[0]!='127.0.0.1':raise ValueError('LOOPBACK_BIND_REQUIRED')
        super().__init__(address,handler)
    def handle_error(self,*args):
        pass # Never log request bodies, initData, URLs or private operation IDs.


def handler_for(service):
    from fast_manual_entry import FastManualEntry
    entry=FastManualEntry(service)
    host=urlsplit(service.base_url).netloc
    prefix=urlsplit(service.base_url).path.rstrip('/')

    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def log_message(self,*args):pass
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def _response(self,status,body,kind='application/json; charset=utf-8'):
            data=body if isinstance(body,bytes) else json.dumps(body,default=str).encode()
            self.send_response(status)
            for k,v in {'Content-Type':kind,'Content-Length':str(len(data)),'Cache-Control':'no-store',
                'Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
                'Permissions-Policy':'camera=(), microphone=(), geolocation=()',
                'Content-Security-Policy':"default-src 'none'; script-src 'self' https://telegram.org; "
                    "style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                    "form-action 'none'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"}.items():
                self.send_header(k,v)
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(data)

        def _path(self):
            if self.client_address[0]!='127.0.0.1' or len(self.headers.get_all('Host',[]))!=1:
                raise TelegramManualError('ORIGIN_REQUIRED')
            if self.headers['Host'] not in (host,'127.0.0.1:'+str(self.server.server_port)):
                raise TelegramManualError('ORIGIN_REQUIRED')
            parsed=urlsplit(self.path)
            if len(self.path)>1024 or parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
                raise TelegramManualError('REQUEST_INVALID')
            path=parsed.path
            return path[len(prefix):] if prefix and path.startswith(prefix+'/') else path

        def do_HEAD(self):self.do_GET()

        def do_GET(self):
            try:
                path=self._path()
                if path=='/health':
                    self._response(200,{'status':'LOCAL_SIMULATION','real_orders_enabled':False});return
                files={'/':('index.html','text/html; charset=utf-8'),
                    '/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
                if path not in files:self._response(404,{'error':'NOT_FOUND'});return
                name,kind=files[path];self._response(200,(STATIC/name).read_bytes(),kind)
            except TelegramManualError:self._response(403,{'error':'REQUEST_INVALID'})
            except Exception:self._response(503,{'error':'SERVICE_UNAVAILABLE'})

        def do_POST(self):
            try:
                path=self._path()
                if (self.headers.get_all('Origin',[])!=[service.origin] or
                        self.headers.get('Content-Type')!='application/json' or
                        self.headers.get('Transfer-Encoding') is not None or
                        len(self.headers.get_all('Content-Length',[]))!=1):
                    raise TelegramManualError('ORIGIN_REQUIRED')
                length=self.headers.get('Content-Length','')
                if not length.isdigit() or not 0<int(length)<=32768:
                    raise TelegramManualError('REQUEST_INVALID')
                def unique(pairs):
                    result=dict(pairs)
                    if len(result)!=len(pairs):raise ValueError
                    return result
                body=json.loads(self.rfile.read(int(length)),object_pairs_hook=unique)
                expected={'/api/execute':{'init_data','intent'},'/api/state':{'init_data','intent'},
                    '/api/watch':{'init_data','symbol','side','candle'},
                    '/api/entry-catalog':{'init_data','symbol','side','candle'},
                    '/api/entry-refresh':{'init_data','symbol','side','candle','contract'},
                    '/api/entry-result':{'init_data'},
                    '/api/entry-buy':{'init_data','symbol','side','candle','contract','quantity','target','ask','total','stop','request_id'},
                    '/api/prepare':{'init_data','intent','action','order_key'},
                    '/api/confirm':{'init_data','intent','review_id'}}
                if path not in expected or not isinstance(body,dict) or set(body)!=expected[path]:
                    raise TelegramManualError('REQUEST_INVALID')
                if not isinstance(body['init_data'],str):
                    raise TelegramManualError('REQUEST_INVALID')
                if path.startswith('/api/entry-'):
                    if path=='/api/entry-catalog':
                        result=entry.catalog(body['init_data'],body['symbol'],body['side'],body['candle'])
                    elif path=='/api/entry-refresh':
                        result=entry.catalog(body['init_data'],body['symbol'],body['side'],body['candle'],selected_contract=body['contract'])
                    elif path=='/api/entry-result':result=entry.result(body['init_data'])
                    else:result=entry.buy(body['init_data'],**{k:v for k,v in body.items() if k!='init_data'})
                    self._response(200,result);return
                if path=='/api/watch':
                    if any(not isinstance(body[k],str) for k in ('symbol','side','candle')):
                        raise TelegramManualError('REQUEST_INVALID')
                    self._response(200,service.watch(body['init_data'],body['symbol'],body['side'],body['candle']));return
                if not isinstance(body['intent'],str):raise TelegramManualError('REQUEST_INVALID')
                if path=='/api/execute':result=service.execute(body['init_data'],body['intent'])
                elif path=='/api/state':result=service.state(body['init_data'],body['intent'])
                elif path=='/api/prepare':result=service.prepare_action(body['init_data'],body['intent'],body['action'],body['order_key'])
                else:result=service.confirm_action(body['init_data'],body['intent'],body['review_id'])
                self._response(200,result)
            except TelegramManualError as error:
                # Fixed codes are safe; no request data or broker exception is returned.
                self._response(403,{'error':str(error)})
            except (ValueError,TypeError):self._response(400,{'error':'REQUEST_INVALID'})
            except Exception:self._response(503,{'error':'SERVICE_UNAVAILABLE'})

        def do_OPTIONS(self):self._response(405,{'error':'METHOD_NOT_ALLOWED'})

    return Handler
