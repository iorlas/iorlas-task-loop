#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.15"
# dependencies = ["msgspec==0.22.0"]
# ///
"""The dashboard page against the contract fixtures, with no engine: the frontend's dev server.

    uv run --script dev/dash_fixtures.py [--port 8766] [--state ok|empty|down|variants]

Serves static/index.html at /, components.html, /<asset> (as the dash serves them), the browser harness (check.html), and the
/api routes from tests/fixtures/dash/ (docs/contracts/dash-api.md). A POST body is decoded strictly with its WRITES
record, so a page that sends a wrong shape gets a 400 here before the backend sees it. --state empty serves a snapshot with
no beads (first run); --state down answers 503 to every API call (server unreachable); --state variants adds cases the
recorded fixture lacks (a shared goal child, a stale account, an exited worker).
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
from tldash.views.snapshot import version_of  # noqa: E402
from tlkernel import dash as D  # noqa: E402
from tlkernel import wire  # noqa: E402
from tlkernel.dashcost import CostPage  # noqa: E402

STATIC = ROOT / "packages" / "dash" / "src" / "tldash" / "static"
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
    if state == "variants":  # cases the recorded fixture lacks: a bead two goals need (⤴ stub), an account status 2 h old
        next(b for b in snap["beads"] if b["id"] == "lifesim-q4")["needs"].append("lifesim-fld.27")
        next(account for account in snap["accounts"] if account["id"] == "claude-2")["status_t"] = snap["t"] - 7200
        next(b for b in snap["beads"] if b["id"] == "lifesim-5ban.3")["marker"] = "exited"  # and its worker exited (bead_detail)
        snap["version"] += "-variants"
        snap["adrs"].append(dict(snap["adrs"][0], project=snap["projects"][1]["id"], id="ADR-OTHER"))
    if state == "bd-error":
        snap["projects"][0].update(bd_ok_at=snap["t"] - 120, bd_error="database locked\ninternal detail")
        snap["projects"].append({"id": "unreadable", "name": "unreadable", "bd_ok_at": None, "bd_error": "bd unavailable"})
        snap["version"] += "-bd-error"
    if state == "identity":
        original = next(b for b in snap["beads"] if b["id"] == "lifesim-6dq0")
        snap["beads"] = [dict(original, project=p["id"], title=f"Repo {n}: duplicate bead", run=f"observed-{n}")
                         for n, p in enumerate(snap["projects"])]
        for n, p in enumerate(snap["projects"]):
            p["name"] = f"demo (repo {n})"
        for field in ("pieces", "asks", "epics", "needs", "slots"):
            snap[field] = []
        snap["version"] += "-identity"
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
    details: ClassVar[dict[str, str]] = {}  # isolated in-memory mutations for resource polling checks

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send(self, code: int, body: bytes, ctype: str = "application/json", etag: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if etag:
            self.send_header("ETag", f'"{etag}"')
        self.end_headers()
        self.wfile.write(body)

    def resource(self, body: dict[str, Any], q: dict[str, str]) -> None:
        token = body["version"]
        held = q.get("since") or (self.headers.get("If-None-Match") or "").strip('"')
        self.send(304 if held == token else 200, b"" if held == token else json.dumps(body).encode(), etag=token)

    def cost(self, q: dict[str, str]) -> None:
        page = wire.load(CostPage, json.loads((FIX / "cost.json").read_text(encoding="utf-8")))
        self.resource(wire.dump(page.replace(version=version_of(page))), q)

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
        route = {"/api/snapshot": self.snap, "/api/bead": self.bead, "/api/live": self.live,
                 "/api/cost": self.cost}.get(u.path)
        if route is None:  # the assets sit at the root, as the dash serves them: pages load them by relative url
            return self.asset(u.path.removeprefix("/"))
        route(q)

    def snap(self, q: dict[str, str]) -> None:
        body = snapshot(self.state)
        self.resource(body, q)

    def bead(self, q: dict[str, str]) -> None:
        p = FIX / "bead" / f"{q.get('id', '')}.json"
        if not p.resolve().is_relative_to(FIX) or not p.is_file():
            return self.json({"error": "unknown bead"}, 404)
        d = json.loads(p.read_text(encoding="utf-8"))
        if self.state == "identity":
            card = next((b for b in snapshot("identity")["beads"] if b["project"] == q.get("project")), None)
            if card is None:
                return self.json({"error": "unknown project"}, 404)
            d["card"] = card
        if self.state == "variants" and q.get("id") == "lifesim-5ban.3":
            d["card"]["marker"] = "exited"
            d["live"].update(kind="exited", exit_code=137, why="the worker was killed (out of memory)")
        d["description"] += self.details.get(q.get("id", ""), "")
        if extra := self.details.get(q.get("id", "")):
            for p in d["passes"]:
                for stage in p.get("logs", []):
                    for role in stage["roles"]:
                        if not role["attempts"][-1].get("live"):
                            role["attempts"][-1]["lines"].append({"t": d["t"], "text": extra, "tone": ""})
        if self.state == "bd-error":
            d.update(bd_error="comments locked\ninternal detail", bd_ok_at=d["t"] - 120 if q.get("id") == "lifesim-6dq0" else None)
        detail = wire.load(D.BeadDetail, d)
        self.resource(wire.dump(detail.replace(version=version_of(detail))), q)

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/dev/detail":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            self.details[str(body["id"])] = str(body["text"])
            return self.json({"ok": True})
        verb = urlparse(self.path).path.removeprefix("/api/")
        if self.state == "down":
            return self.json({"error": "down"}, 503)
        if verb not in D.WRITES:
            return self.send(404, b"not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            wire.load(D.WRITES[verb], body)
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
    return type("Handler", (Handler,), {"state": state, "writes": [], "details": {}})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--state", choices=("ok", "empty", "down", "variants", "bd-error", "identity"), default="ok")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.state))
    print(f"http://127.0.0.1:{args.port}/  (state {args.state})", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
