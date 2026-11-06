"""The HTTP face: the page and its modules from the static dir, the reads under /api/ (snapshot, bead, cost, live, artifact, look-shot,
version), and POST /api/<verb>, the only writes. A broken transcript or log answers 500 with the error, never takes the page down."""

import json
import os
from collections.abc import Sequence
from email.message import Message
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, override
from urllib.parse import parse_qs, urlparse, urlsplit

from taskloop.contracts import factorydb
from taskloop.contracts.dash import READ_PROTOCOL
from taskloop_dash.app import Dash
from taskloop_dash.assets import static_file
from taskloop_dash.bind import urls

Query = dict[str, str]
MAX_BODY = 65536
POST_PREFIX = "/api/"  # POST /api/<verb>: the records of contracts.dash.WRITES

Headers = Sequence[tuple[str, str]]


def authority(value: str) -> tuple[str, int] | None:
    """Parse only an HTTP authority, never credentials or URL components."""
    if not value or value.endswith(":") or any(c.isspace() or c in "/?#@\\" for c in value):
        return None
    try:
        parsed = urlsplit("http://" + value)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return None
    if not host:
        return None
    name = f"[{host}]" if ":" in host else host
    expected = f"{name}:{port}" if port is not None else name
    return (host, port if port is not None else 80) if value.lower() == expected.lower() else None


def write_refusal(headers: Message, hosts: set[tuple[str, int]]) -> int | None:
    """Browser writes need an allowed Host, same Origin and a non-simple header; CLI clients may omit Origin."""
    host_fields = headers.get_all("Host", None) or []
    host = authority(host_fields[0]) if len(host_fields) == 1 else None
    if host not in hosts or headers.get_all("X-Taskloop-Dash", []) != ["1"]:
        return 403
    origins = headers.get_all("Origin", None) or []
    if origins and (len(origins) != 1 or not origins[0].startswith("http://") or authority(origins[0][7:]) != host):
        return 403
    media = headers.get_all("Content-Type", None) or []
    if len(media) != 1 or media[0].split(";", 1)[0].strip().lower() != "application/json":
        return 415
    return None


def put_headers(h: BaseHTTPRequestHandler, headers: Headers) -> None:
    for k, v in headers:
        h.send_header(k, v)


def route(dash: Dash, static: Path, path: str, q: Query, held: str | None = None) -> tuple[int, bytes, str, Headers] | None:
    """(status, body, content type, extra headers) of a GET other than /api/version; None for an unknown path. `held`: the request's
    If-None-Match."""
    if path in ("/api/snapshot", "/api/bead", "/api/cost"):
        code, body, extra = dash.reads.get(path, q, held)
        return code, body, "application/json", list(extra.items())
    if path == "/api/live":
        code, page = dash.live.page(q.get("project", ""), q.get("id", ""), q.get("since", ""), q.get("wait", "0"))
        return code, json.dumps(page).encode(), "application/json", []
    if path == "/api/look-shot":
        got = dash.looks.look_shot(q.get("repo", ""), q.get("path", ""))
        return (200, got[0], got[1], []) if got else (404, b"not found", "text/plain", [])
    if path == "/api/artifact":
        got = dash.artifacts.file(*(q.get(k, "") for k in ("repo", "bead", "run", "stage", "attempt", "name")))
        if got is None:
            return 404, b"not found", "text/plain", []
        return 200, got[0], got[1], [] if got[2] else [("Content-Disposition", "attachment")]
    got = static_file(static, path)
    return (*got, []) if got[0] == 200 else None


def make_handler(
    dash: Dash, port: int, addrs: list[str], static: Path, script: str
) -> type[BaseHTTPRequestHandler]:
    # These are the names we already know; never resolve a request's Host through DNS.
    hosts = {(addr.lower(), port) for addr in [*addrs, "localhost", "127.0.0.1", "::1"]}

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
                            "script": script, "binds": list(addrs), "port": port,
                            "protocol": READ_PROTOCOL, "schema": factorydb.SCHEMA_VERSION,
                            "database_error": dash.reads.worlds.database_error()}
                    return self.send(200, json.dumps(body).encode(), "application/json")
                got = route(dash, static, u.path, q, self.headers.get("If-None-Match"))
            except Exception as e:  # a broken transcript must not take the page down
                return self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")
            self.send(*(got or (404, b"not found", "text/plain", [])))

        def do_POST(self) -> None:
            if refusal := write_refusal(self.headers, hosts):
                return self.send(refusal, b'{"error": "write policy"}', "application/json")
            u = urlparse(self.path)
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_BODY)) or b"{}")
            except ValueError:
                return self.send(400, b'{"error": "json"}', "application/json")
            if not u.path.startswith(POST_PREFIX):
                return self.send(404, b"not found", "text/plain")
            code, answer = dash.writes.post(u.path[len(POST_PREFIX):], body)
            self.send(code, json.dumps(answer).encode(), "application/json")
    return H
