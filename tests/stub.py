from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.path == "/api/v1/alerts/expiry" and (self.command != "GET" or self.headers.get("Authorization") == "Bearer stub-forbidden"):
            status = 405 if self.command != "GET" else 403
            code = "METHOD_NOT_ALLOWED" if status == 405 else "FORBIDDEN"
            content = json.dumps({"error": code, "message": "Owner rejected request.", "traceId": self.headers.get("X-Correlation-Id")}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Correlation-Id", self.headers.get("X-Correlation-Id", "stub"))
            if status == 405: self.send_header("Allow", "GET, HEAD")
            self.end_headers(); self.wfile.write(content)
            return
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
