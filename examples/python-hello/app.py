#!/usr/bin/env python3
"""Minimal Python web app (stdlib only) for testing Runway (Plesk extension).

Listens on RUNWAY_SOCKET (Unix socket mode) when it is set, else on HOST:PORT.
Build: uv venv .venv (or nothing)    Start: .venv/bin/python app.py (or python3 app.py)
"""
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/healthz":
            text = "ok\n"
        else:
            text = "Hello from Python %s (pid %d)\n" % (sys.version.split()[0], os.getpid())
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def address_string(self):
        # client_address is '' on unix sockets; the default implementation would raise IndexError
        addr = self.client_address
        return addr[0] if isinstance(addr, tuple) else "unix"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


class UnixHTTPServer(ThreadingHTTPServer):
    address_family = getattr(socket, "AF_UNIX", None)  # None on Windows (local tests use TCP)

    def server_bind(self):
        path = self.server_address
        try:
            os.unlink(path)  # stale socket from a crash
        except FileNotFoundError:
            pass
        self.socket.bind(path)
        os.chmod(path, 0o660)  # nginx connects through the psaserv group
        self.server_name = "localhost"
        self.server_port = 0


def main():
    sock = os.environ.get("RUNWAY_SOCKET")
    if sock:
        httpd = UnixHTTPServer(sock, Handler)
        where = sock
    else:
        host = os.environ.get("HOST", "127.0.0.1")
        port = int(os.environ.get("PORT", "8080"))
        httpd = ThreadingHTTPServer((host, port), Handler)
        where = "%s:%d" % (host, port)
    sys.stderr.write("listening on %s\n" % where)
    sys.stderr.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    main()
