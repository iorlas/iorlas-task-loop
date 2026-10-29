"""The HTTP face: the page and its modules from the static dir, the reads under /api/ (snapshot, bead, live, artifact, look-shot,
version), and POST /api/<verb>, the only writes. A broken transcript or log answers 500 with the error, never takes the page down."""

import json
import os
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, override
from urllib.parse import parse_qs, urlparse

from taskloop_dash.app import Dash
from taskloop_dash.assets import static_file
from taskloop_dash.bind import post_allowed, urls

Query = dict[str, str]
MAX_BODY = 65536
POST_PREFIX = "/api/"  # POST /api/<verb>: the records of contracts.dash.WRITES

Headers = Sequence[tuple[str, str]]


def put_headers(h: BaseHTTPRequestHandler, headers: Headers) -> None:
    for k, v in headers:
        h.send_header(k, v)


def route(dash: Dash, static: Path, path: str, q: Query, held: str | None = None) -> tuple[int, bytes, str, Headers] | None:
    """(status, body, content type, extra headers) of a GET other than /api/version; None for an unknown path. `held`: the request's
    If-None-Match."""
    if path in ("/api/snapshot", "/api/bead"):
        code, body, extra = dash.reads.get(path, q, held)
        return code, body, "application/json", list(extra.items())
    if path == "/api/live":
        code, page = dash.live.page(q.get("id", ""), q.get("since", ""), q.get("wait", "0"))
        return code, json.dumps(page).encode(), "application/json", []
    if path == "/api/look-shot":
        got = dash.looks.look_shot(q.get("repo", ""), q.get("path", ""))
        return (200, got[0], got[1], []) if got else (404, b"not found", "text/plain", [])
    if path == "/api/artifact":
        got = dash.artifacts.file(q.get("bead", ""), q.get("name", ""))
        return (200, got[0], got[1], []) if got else (404, b"not found", "text/plain", [])
    got = static_file(static, path)
    return (*got, []) if got[0] == 200 else None


def make_handler(
    dash: Dash, port: int, addrs: list[str], static: Path, secret: Callable[[], str], script: str
) -> type[BaseHTTPRequestHandler]:
    class H(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send(self, code: int, body: bytes, ctype: str, headers: Headers = ()) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            put_headers(self, headers)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/version":
                    body = {"version": dash.env.version, "pid": os.getpid(), "urls": urls(addrs, port), "started": dash.env.started,
                            "script": script, "binds": list(addrs), "port": port}
                    return self.send(200, json.dumps(body).encode(), "application/json")
                got = route(dash, static, u.path, q, self.headers.get("If-None-Match"))
            except Exception as e:  # a broken transcript must not take the page down
                return self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")
            self.send(*(got or (404, b"not found", "text/plain", [])))

        def do_POST(self) -> None:
            u = urlparse(self.path)
            if not post_allowed(self.client_address[0], self.headers.get("Authorization"), secret):
                return self.send(401, b'{"error": "token"}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_BODY)) or b"{}")
            except ValueError:
                return self.send(400, b'{"error": "json"}', "application/json")
            if not u.path.startswith(POST_PREFIX):
                return self.send(404, b"not found", "text/plain")
            code, answer = dash.writes.post(u.path[len(POST_PREFIX):], body)
            self.send(code, json.dumps(answer).encode(), "application/json")
    return H
