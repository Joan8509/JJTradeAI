"""Vista local de lectura para revisar la web antes de conectarla a Vercel."""
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cloud_snapshot_api import snapshot


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web_vercel" / "public"), **kwargs)

    def do_GET(self):
        if self.headers.get("Host", "").split(":")[0] not in {"127.0.0.1", "localhost"}:
            self.send_error(403)
            return
        if self.path == "/api/dashboard":
            data = json.dumps({**snapshot(), "local_preview": True}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            super().do_GET()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8510), Handler).serve_forever()
