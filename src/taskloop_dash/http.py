"""The HTTP face: a routes table from path to a function of (dash, query), the handler that serves it, and the three POSTs (the only
writes). A broken transcript or log answers 500 with the error, never takes the page down."""

import json
import os
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Final, override
from urllib.parse import parse_qs, urlparse

from taskloop_dash.app import Dash
from taskloop_dash.bind import post_allowed, urls

Query = dict[str, str]
Reply = tuple[int, Any]
MAX_BODY = 65536


def as_int(text: str, default: int = 0) -> int:
    try:
        return int(text)
    except ValueError:
        return default


JSON_ROUTES: Final[dict[str, Callable[[Dash, Query], Any]]] = {
    "/api/events": lambda d, q: d.runs.run_events(q.get("id", "")),
    "/api/asks": lambda d, q: d.asks.asks(),
    "/api/tasks": lambda d, q: d.tasks.api_tasks(),
    "/api/graph": lambda d, q: d.graph.api_graph(q.get("repo", "")),
    "/api/bead": lambda d, q: d.bead.api_bead(q.get("repo", ""), q.get("id", "")),
    "/api/reflections": lambda d, q: d.reflections(q.get("hours", "24")),
    "/api/looks": lambda d, q: d.looks.api_looks(q.get("repo", "")),
    "/api/roadmap": lambda d, q: d.roadmap.api_roadmap(q.get("repo", "")),
    "/api/task-timeline": lambda d, q: d.tasks.api_task_timeline(q.get("repo", ""), q.get("id", "")),
    "/api/live": lambda d, q: d.live.api_live(q.get("bead", ""), q.get("run", ""), q.get("since", ""), q.get("before", ""),
                                              q.get("wait", "0"), q.get("limit", "300")),
    "/api/live/overview": lambda d, q: d.live.api_live_overview(q.get("wait", "0")),
    "/api/block": lambda d, q: d.runs.api_block(q.get("run", ""), q.get("node", ""), as_int(q.get("k", "0"))),
}
POSTS: Final[dict[str, Callable[[Dash, Any], Reply]]] = {
    "/api/answer": lambda d, body: d.asks.answer(body),
    "/api/withdraw": lambda d, body: d.asks.withdraw(body),
    "/api/look": lambda d, body: d.looks.answer_look(body),
}


def make_handler(dash: Dash, port: int, addrs: list[str], page: Path, live_page: Path, secret: Callable[[], str], script: str) -> type[BaseHTTPRequestHandler]:
    class H(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def raw(self, path: str, q: Query) -> tuple[int, bytes, str] | None:
            """The routes that answer bytes, not JSON."""
            if path == "/api/look-shot":
                got = dash.looks.look_shot(q.get("repo", ""), q.get("path", ""))
                return (200, got[0], got[1]) if got else (404, b"not found", "text/plain")
            if path == "/api/file":
                data = dash.runs.run_file(q.get("run", ""), q.get("path", ""))
                return (200, data, "text/plain; charset=utf-8") if data is not None else (404, b"not found", "text/plain")
            if path == "/live":
                return 200, live_page.read_bytes(), "text/html; charset=utf-8"
            if path in ("/", "/index.html"):
                return 200, page.read_bytes(), "text/html; charset=utf-8"
            return None

        def do_GET(self) -> None:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/version":
                    body: Any = {"version": dash.env.version, "pid": os.getpid(), "urls": urls(addrs, port), "started": dash.env.started,
                                 "script": script, "binds": list(addrs), "port": port}
                elif u.path in JSON_ROUTES:
                    body = JSON_ROUTES[u.path](dash, q)
                else:
                    got = self.raw(u.path, q)
                    return self.send(*(got or (404, b"not found", "text/plain")))
            except Exception as e:  # a broken transcript must not take the page down
                return self.send(500, json.dumps({"error": "%s: %s" % (type(e).__name__, e)}).encode(), "application/json")
            self.send(200, json.dumps(body, default=str).encode(), "application/json")

        def do_POST(self) -> None:
            u = urlparse(self.path)
            if not post_allowed(self.client_address[0], self.headers.get("Authorization"), secret):
                return self.send(401, b'{"error": "token"}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_BODY)) or b"{}")
            except ValueError:
                return self.send(400, b'{"error": "json"}', "application/json")
            if u.path not in POSTS:
                return self.send(404, b"not found", "text/plain")
            code, out = POSTS[u.path](dash, body)
            self.send(code, json.dumps(out).encode(), "application/json")
    return H
