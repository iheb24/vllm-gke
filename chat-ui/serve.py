#!/usr/bin/env python3
"""Serves the chat UI and proxies /v1/* to the gateway on localhost:8081.

Same-origin serving means the browser never sends a CORS preflight, which the
semantic router's ext_proc filter would otherwise reject.

Usage:
    kubectl port-forward -n envoy-gateway-system svc/<envoy-svc> 8081:80 &
    python3 serve.py            # then open http://localhost:8000
"""
import http.client
import http.server
import os

UI_DIR = os.path.dirname(os.path.abspath(__file__))
UPSTREAM_HOST = "localhost"
UPSTREAM_PORT = 8081
LISTEN_PORT = 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def do_GET(self):
        if self.path.startswith("/v1/"):
            self.proxy()
        else:
            super().do_GET()

    def do_POST(self):
        self.proxy()

    def proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {}
        for name in ("Content-Type", "Authorization", "Accept"):
            value = self.headers.get(name)
            if value:
                headers[name] = value

        upstream = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=900)
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            resp = upstream.getresponse()
        except OSError as exc:
            message = f"upstream unreachable on {UPSTREAM_HOST}:{UPSTREAM_PORT} ({exc}). Is kubectl port-forward running?"
            payload = message.encode()
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(resp.status)
        for name, value in resp.getheaders():
            if name.lower() in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(name, value)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
        upstream.close()

    def log_message(self, fmt, *args):
        print(f"[ui-proxy] {fmt % args}", flush=True)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    print(f"Serving UI at http://localhost:{LISTEN_PORT} (proxying /v1/* to {UPSTREAM_HOST}:{UPSTREAM_PORT})")
    server.serve_forever()
