"""HTTP service on port 8080: GET /health and GET /hello. One JSON log line per request."""

import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Set at image build time from `verify_deployment.py source-hash`; the verifier compares it with app/.
SOURCE_SHA256 = os.environ.get("SOURCE_SHA256", "unknown")
CORRELATION_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def secrets_loaded(env):
    """Names of the secrets ECS injected, never their values. SECRET_NAMES lists the expected ones."""
    names = [n for n in env.get("SECRET_NAMES", "").split(",") if n]
    return [n for n in names if env.get(n)]


def route(method, path, correlation_id, env=os.environ):
    if method != "GET":
        return 405, {"message": "method not allowed"}
    if path == "/health":
        return 200, {"status": "ok"}
    if path == "/hello":
        return 200, {"message": "hello", "correlation_id": correlation_id, "source_sha256": SOURCE_SHA256,
                     "secrets_loaded": secrets_loaded(env)}
    return 404, {"message": "not found"}


def correlation_id_from(headers):
    supplied = headers.get("x-correlation-id") or ""
    return supplied if CORRELATION_ID.match(supplied) else str(uuid.uuid4())


class Handler(BaseHTTPRequestHandler):
    server_version = "app"
    sys_version = ""

    def do_GET(self):
        self.respond("GET")

    def do_POST(self):
        self.respond("POST")

    def respond(self, method):
        correlation_id = correlation_id_from(self.headers)
        path = self.path.split("?", 1)[0]
        status, body = route(method, path, correlation_id)
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.send_header("x-correlation-id", correlation_id)
        self.end_headers()
        self.wfile.write(data)
        if path != "/health":
            print(json.dumps({"message": "request handled", "method": method, "path": path, "status": status,
                              "correlation_id": correlation_id,
                              "trace_id": self.headers.get("x-amzn-trace-id", "")}), flush=True)

    def log_message(self, format, *args):
        # The JSON line in respond() replaces the default access log on stderr.
        return


def serve(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(json.dumps({"message": "listening", "port": port, "source_sha256": SOURCE_SHA256}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    serve(int(os.environ.get("PORT", "8080")))
