#!/usr/bin/env python3
"""The dashboard page against the contract fixtures, with no engine: the frontend's dev server.

    python3 dev/dash_fixtures.py [--port 8766] [--state ok|empty|down|variants]

Serves static/index.html at /, components.html, /<asset> (as the dash serves them), the browser harness (check.html), and the
/api routes from tests/fixtures/dash/ (docs/contracts/dash-api.md). A POST body is decoded strictly with its WRITES
record, so a page that sends a wrong shape gets a 400 here before the backend sees it. --state empty serves a snapshot with
no beads (first run); --state down answers 503 to every API call (server unreachable); --state variants adds cases the
recorded fixture lacks (a shared goal child, a stale lane, an exited worker).
"""
import argparse
import contextlib
import json
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from taskloop.contracts import codec  # noqa: E402
from taskloop.contracts import dash as D  # noqa: E402

STATIC = ROOT / "src" / "taskloop_dash" / "static"
FIX = ROOT / "tests" / "fixtures" / "dash"
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml"}
PAGES = {"/": STATIC / "index.html", "/index.html": STATIC / "index.html", "/components.html": STATIC / "components.html",
         "/check.html": ROOT / "dev" / "dash_check.html"}


def snapshot(state: str) -> dict[str, Any]:
    snap = json.loads((FIX / "snapshot.json").read_text(encoding="utf-8"))
    if state == "empty":
        for k in ("beads", "pieces", "asks", "slots"):
            snap[k] = []
        snap["version"] += "-empty"
    if state == "variants":  # cases the recorded fixture lacks: a bead two goals need (⤴ stub), a lane status 2 h old
        next(b for b in snap["beads"] if b["id"] == "lifesim-q4")["needs"].append("lifesim-fld.27")
        next(lane for lane in snap["lanes"] if lane["id"] == "claude-2")["status_t"] = snap["t"] - 7200
        next(b for b in snap["beads"] if b["id"] == "lifesim-5ban.3")["marker"] = "exited"  # and its worker exited (bead_detail)
        snap["version"] += "-variants"
    return snap


def placeholder(name: str) -> str:
    """A stand-in screenshot for an artifact url: the fixtures name artifacts the dev server does not have."""
    hue = sum(name.encode()) * 37 % 360
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100"><rect width="160" height="62" fill="hsl({hue},45%,72%)"/>'
            f'<rect y="62" width="160" height="38" fill="hsl({hue},25%,52%)"/><rect x="58" y="30" width="34" height="46" rx="3" '
            f'fill="hsl({hue},20%,90%)"/><text x="6" y="14" font-size="10" font-family="sans-serif">{escape(name)}</text></svg>')


class Handler(BaseHTTPRequestHandler):
    state = "ok"
    writes: ClassVar[list] = []  # every accepted POST as [verb, body], for the browser harness (GET /dev/writes)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj: Any, code: int = 200) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in PAGES:
            return self.send(200, PAGES[u.path].read_bytes(), TYPES[".html"])
        if u.path.startswith("/api/") and self.state == "down":
            return self.json({"error": "down"}, 503)
        if u.path == "/dev/writes":
            return self.json(self.writes)
        if u.path in ("/api/artifact", "/api/look-shot"):
            return self.send(200, placeholder(q.get("name", "shot")).encode(), TYPES[".svg"])
        route = {"/api/snapshot": self.snap, "/api/bead": self.bead, "/api/live": self.live}.get(u.path)
        if route is None:  # the assets sit at the root, as the dash serves them: pages load them by relative url
            return self.asset(u.path.removeprefix("/"))
        route(q)

    def snap(self, q: dict[str, str]) -> None:
        body = snapshot(self.state)
        return self.send(304, b"") if q.get("since") == body["version"] else self.json(body)

    def bead(self, q: dict[str, str]) -> None:
        p = FIX / "bead" / f"{q.get('id', '')}.json"
        if self.state != "variants" or q.get("id") != "lifesim-5ban.3" or not p.is_file():
            return self.fixture(p)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["card"]["marker"] = "exited"
        d["live"].update(kind="exited", exit_code=137, why="the worker was killed (out of memory)")
        return self.json(d)

    def do_POST(self) -> None:
        verb = urlparse(self.path).path.removeprefix("/api/")
        if self.state == "down":
            return self.json({"error": "down"}, 503)
        if verb not in D.WRITES:
            return self.send(404, b"not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            codec.from_json(D.WRITES[verb], body)
        except Exception as e:  # the page sent a shape the contract refuses
            return self.json({"error": f"{type(e).__name__}: {e}"}, 400)
        self.writes.append([verb, body])
        self.fixture(FIX / "result.json")

    def asset(self, rel: str) -> None:
        p = (STATIC / rel).resolve()
        if not p.is_relative_to(STATIC) or p.suffix not in TYPES or not p.is_file():
            return self.send(404, b"not found", "text/plain")
        self.send(200, p.read_bytes(), TYPES[p.suffix])

    def live(self, q: dict[str, str]) -> None:
        """The fixture page; a poll from its own cursor gets no new lines at once (no long wait: headless Chrome's virtual
        time stops while a request is open, and the page throttles its own polls)."""
        p = FIX / "live" / f"{q.get('id', '')}.json"
        if not p.resolve().is_relative_to(FIX) or not p.is_file():
            return self.json({"error": "no live run"}, 404)
        page = json.loads(p.read_text(encoding="utf-8"))
        if self.state == "variants" and q.get("id") == "lifesim-5ban.3":  # the exited worker: a longer tail, then the end
            t = page["lines"][0]["t"]
            tail = [{"t": t - 60 * (24 - i), "text": f"  at PathGrid.Step() line {i}", "tone": ""} for i in range(18)]
            page["lines"] = tail + page["lines"]
            page |= {"state": "exited", "cursor": "lifesim-5ban.3:24"}
        if q.get("since") == page["cursor"]:
            page |= {"lines": [], "tools": []}
        self.json(page)

    def fixture(self, p: Path) -> None:
        if not p.resolve().is_relative_to(FIX) or not p.is_file():
            return self.json({"error": "unknown bead"}, 404)
        self.send(200, p.read_bytes())


def make_handler(state: str) -> type[BaseHTTPRequestHandler]:
    return type("Handler", (Handler,), {"state": state, "writes": []})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--state", choices=("ok", "empty", "down", "variants"), default="ok")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.state))
    print(f"http://127.0.0.1:{args.port}/  (state {args.state})", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
