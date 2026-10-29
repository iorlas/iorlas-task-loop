"""The HTTP face: a routes table from path to a function of (dash, query), the handler that serves it, and the three POSTs (the only
writes). A broken transcript or log answers 500 with the error, never takes the page down."""

import json
import os
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Final, override
from urllib.parse import parse_qs, urlparse

from taskloop_dash.app import Dash
from taskloop_dash.assets import static_file
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
READS_V2: Final[dict[str, Callable[[Dash, Query], Reply]]] = {
    "/api/v2/live": lambda d, q: d.live.api_v2_live(q.get("id", ""), q.get("since", ""), q.get("wait", "0")),
}
V2_POSTS: Final = "/api/v2/"  # POST /api/v2/<verb>: the records of contracts.dash.WRITES
POSTS: Final[dict[str, Callable[[Dash, Any], Reply]]] = {
    "/api/answer": lambda d, body: d.asks.answer(body),
    "/api/withdraw": lambda d, body: d.asks.withdraw(body),
    "/api/look": lambda d, body: d.looks.answer_look(body),
}


def json_reply(dash: Dash, path: str, q: Query) -> Reply | None:
    """(status, body) of a JSON GET, None when the path is not one."""
    if path in READS_V2:
        return READS_V2[path](dash, q)
    return (200, JSON_ROUTES[path](dash, q)) if path in JSON_ROUTES else None


def post_reply(dash: Dash, path: str, body: Any) -> Reply | None:
    """(status, answer) of a POST, None when the path is not one."""
    if path.startswith(V2_POSTS):
        return dash.writes.post(path[len(V2_POSTS):], body)
    return POSTS[path](dash, body) if path in POSTS else None


Headers = Sequence[tuple[str, str]]


def put_headers(h: BaseHTTPRequestHandler, headers: Headers) -> None:
    for k, v in headers:
        h.send_header(k, v)


def raw_route(
    dash: Dash, page: Path, live_page: Path, path: str, q: Query, held: str | None = None
) -> tuple[int, bytes, str, Headers] | None:
    """The routes that answer bytes, not JSON: (status, body, content type, extra headers). `held`: the request's If-None-Match."""
    if path.startswith("/api/v2/"):
        code, body, extra = dash.v2.get(path, q, held)
        return code, body, "application/json", list(extra.items())
    got = plain_route(dash, page, live_page, path, q)
    return (*got, []) if got else None


def plain_route(dash: Dash, page: Path, live_page: Path, path: str, q: Query) -> tuple[int, bytes, str] | None:
    if path == "/api/look-shot":
        got = dash.looks.look_shot(q.get("repo", ""), q.get("path", ""))
        return (200, got[0], got[1]) if got else (404, b"not found", "text/plain")
    if path == "/api/artifact":
        got = dash.artifacts.file(q.get("bead", ""), q.get("name", ""))
        return (200, got[0], got[1]) if got else (404, b"not found", "text/plain")
    if path == "/api/file":
        data = dash.runs.run_file(q.get("run", ""), q.get("path", ""))
        return (200, data, "text/plain; charset=utf-8") if data is not None else (404, b"not found", "text/plain")
    if path == "/live":
        return 200, live_page.read_bytes(), "text/html; charset=utf-8"
    if path in ("/", "/index.html"):
        return 200, page.read_bytes(), "text/html; charset=utf-8"
    got = static_file(page.parent, path)
    return got if got[0] == 200 or path in ("/v2", "/v2.html") else None


def make_handler(
    dash: Dash, port: int, addrs: list[str], page: Path, live_page: Path, secret: Callable[[], str], script: str
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

        def raw(self, path: str, q: Query) -> tuple[int, bytes, str, Headers] | None:
            return raw_route(dash, page, live_page, path, q, self.headers.get("If-None-Match"))

        def do_GET(self) -> None:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            code = 200
            try:
                if u.path == "/api/version":
                    body: Any = {"version": dash.env.version, "pid": os.getpid(), "urls": urls(addrs, port), "started": dash.env.started,
                                 "script": script, "binds": list(addrs), "port": port}
                elif (hit := json_reply(dash, u.path, q)) is not None:
                    code, body = hit
                else:
                    got = self.raw(u.path, q)
                    return self.send(*(got or (404, b"not found", "text/plain", [])))
            except Exception as e:  # a broken transcript must not take the page down
                return self.send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(), "application/json")
            self.send(code, json.dumps(body, default=str).encode(), "application/json")

        def do_POST(self) -> None:
            u = urlparse(self.path)
            if not post_allowed(self.client_address[0], self.headers.get("Authorization"), secret):
                return self.send(401, b'{"error": "token"}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), MAX_BODY)) or b"{}")
            except ValueError:
                return self.send(400, b'{"error": "json"}', "application/json")
            got = post_reply(dash, u.path, body)
            if got is None:
                return self.send(404, b"not found", "text/plain")
            self.send(got[0], json.dumps(got[1]).encode(), "application/json")
    return H
