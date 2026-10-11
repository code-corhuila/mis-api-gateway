from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.query == "delay=12":
            time.sleep(12)
        content = json.dumps({"path": uri.path, "query": uri.query,
            "method": self.command, "idempotencyKey": self.headers.get("Idempotency-Key"),
            "ifMatch": self.headers.get("If-Match"),
            "correlation": self.headers.get("X-Correlation-Id"),
            "roleHeader": self.headers.get("X-User-Role"),
            "authorizationPresent": bool(self.headers.get("Authorization"))}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Correlation-Id", self.headers.get("X-Correlation-Id", "stub"))
        self.send_header("ETag", '"3"')
        self.end_headers()
        try:
            self.wfile.write(content)
        except BrokenPipeError:
            pass

    do_POST = do_GET
    do_PUT = do_GET

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
