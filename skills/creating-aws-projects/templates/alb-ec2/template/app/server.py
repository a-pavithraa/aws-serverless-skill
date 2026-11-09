"""HTTP service on port 8080: GET /health and GET /hello. One JSON log line per request."""

import hashlib
import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SKIP = {"tests", "__pycache__"}


def source_hash(app):
    """Same algorithm as `verify_deployment.py source-hash`: the verifier compares the two."""
    digest = hashlib.sha256()
    files = {p.relative_to(app).as_posix(): p for p in app.rglob("*")
             if p.is_file() and not SKIP & set(p.relative_to(app).parts)}
    for name, path in sorted(files.items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


SOURCE_SHA256 = source_hash(Path(__file__).resolve().parent)
CORRELATION_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def route(method, path, correlation_id):
    if method != "GET":
        return 405, {"message": "method not allowed"}
    if path == "/health":
        return 200, {"status": "ok"}
    if path == "/hello":
        return 200, {"message": "hello", "correlation_id": correlation_id, "source_sha256": SOURCE_SHA256}
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
