#!/usr/bin/env python3
"""Browser checks and screenshots of the dashboard page against the fixtures, in headless Chrome, no third-party package.

    python3 dev/dash_check.py [--out DIR] [--shots] [--only NAME]

Runs dev/dash_fixtures.py in a thread and opens dev/dash_check.html, which holds the page in an iframe of the asked size
(headless Chrome sizes no window below 500 px, so the phone runs at 390x844 inside it). Each case prints PASS or its
failures; --shots also saves desktop and phone screenshots, light and dark, to --out. Chrome is $TL_CHROME, else the
first of chromium, google-chrome, chrome on PATH; it runs with --headless=new.
"""
import argparse
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
PHONE, DESKTOP = (390, 844), (1440, 900)

# (name, query): scenarios live in dash_check.html
CASES = [
    ("desktop-walk", {"scn": "walk", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-walk", {"scn": "walk", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-persist", {"scn": "persist", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-persist", {"scn": "persist", "w": PHONE[0], "h": PHONE[1]}),
    ("components-phone", {"scn": "view", "page": "/components.html?solo=phone", "w": PHONE[0], "h": PHONE[1]}),
    ("components-desktop", {"scn": "view", "page": "/components.html?solo=desktop", "w": 1280, "h": 2400}),
    ("desktop-drawer", {"scn": "drawer", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-drawer", {"scn": "drawer", "w": PHONE[0], "h": PHONE[1]}),
    ("mid-walk", {"scn": "walk", "w": 760, "h": 900}),
    ("desktop-asks", {"scn": "asks", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-asks", {"scn": "asks", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-draft", {"scn": "draft", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-draft", {"scn": "draft", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-floor", {"scn": "floor", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-floor", {"scn": "floor", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-ledger", {"scn": "ledger", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-ledger", {"scn": "ledger", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-controls", {"scn": "controls", "w": DESKTOP[0], "h": DESKTOP[1]}),
    ("phone-controls", {"scn": "controls", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-goals", {"scn": "goals", "w": DESKTOP[0], "h": DESKTOP[1], "state": "variants"}),
    ("phone-goals", {"scn": "goals", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-lanes", {"scn": "lanes", "w": DESKTOP[0], "h": DESKTOP[1], "state": "variants"}),
    ("phone-lanes", {"scn": "lanes", "w": PHONE[0], "h": PHONE[1], "state": "variants"}),
    ("phone-back", {"scn": "back", "w": PHONE[0], "h": PHONE[1]}),
    ("desktop-exited", {"scn": "exited", "w": DESKTOP[0], "h": DESKTOP[1], "state": "variants"}),
    ("phone-exited", {"scn": "exited", "w": PHONE[0], "h": PHONE[1], "state": "variants"}),
    ("phone-empty", {"scn": "empty", "w": PHONE[0], "h": PHONE[1], "state": "empty"}),
    ("desktop-down", {"scn": "down", "w": DESKTOP[0], "h": DESKTOP[1], "state": "down"}),
]

# against a live server (--base): read-only, writes refused in the page; part 0 is every view, parts 1.. are slices of beads
LIVE_CASES = [(f"{dev}-survey-{part}", {"scn": "survey", "part": part, "ro": 1, "w": size[0], "h": size[1]})
              for dev, size in (("desktop", DESKTOP), ("phone", PHONE)) for part in range(6)]
LIVE_CASES += [(n, {**c, "ro": 1}) for n, c in CASES if c["scn"] == "walk"]

# (file stem, page, hash, size): screenshots, each in light and dark
SHOTS = [
    ("board", "/", "#board", DESKTOP), ("board", "/", "#board", PHONE),
    ("drawer", "/", "#board~~lifesim-6dq0", DESKTOP), ("drawer", "/", "#board~~lifesim-6dq0", PHONE),
    ("drawer4", "/", "#board~~lifesim-d5f.48~p2", DESKTOP), ("drawer4", "/", "#board~~lifesim-d5f.48~p2", PHONE),
    ("mid", "/", "#board", (760, 900)),
    ("floor", "/", "#floor", DESKTOP), ("floor", "/", "#floor", PHONE),
    ("decisions", "/", "#decisions", DESKTOP), ("decisions", "/", "#decisions", PHONE),
    ("ledger", "/", "#decisions~led", DESKTOP), ("ledger", "/", "#decisions~led", PHONE),
    ("inforce", "/", "#decisions~adr", DESKTOP), ("inforce", "/", "#decisions~adr", PHONE),
    ("lanes", "/", "#lanes", DESKTOP), ("lanes", "/", "#lanes", PHONE),
    ("goals", "/", "#board~tree", DESKTOP), ("goals", "/", "#board~tree", PHONE),
    ("components", "/components.html?solo=desktop", "", (640, 4200)), ("components", "/components.html?solo=phone", "", (390, 4200)),
]


def chrome() -> str:
    for c in (os.environ.get("TL_CHROME"), "chromium", "google-chrome", "chrome"):
        if c and shutil.which(c):
            return shutil.which(c) or c
    sys.exit("no Chrome: set TL_CHROME to a chrome binary")


def serve(state: str) -> tuple[ThreadingHTTPServer, int]:
    spec = importlib.util.spec_from_file_location("dash_fixtures", ROOT / "dev" / "dash_fixtures.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def run(exe: str, profile: str, url: str, size: tuple[int, int], extra: list[str]) -> tuple[str, list[str]]:
    """(stdout, page errors): Chrome logs the page console to stderr with --enable-logging=stderr."""
    argv = [exe, "--headless=new", "--enable-logging=stderr", "--v=0", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
            "--force-prefers-reduced-motion", f"--user-data-dir={profile}",
            f"--window-size={max(500, size[0])},{size[1]}", "--virtual-time-budget=20000", *extra, url]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)  # run kills Chrome on the timeout
        out, err = r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        out, err = str(e.stdout or ""), f'{e.stderr or ""}\nCONSOLE "Error: chrome timed out after 60 s"'
    errs = [m.group(1) for m in re.finditer(r'CONSOLE.*?"((?:Uncaught|Error|TypeError|ReferenceError|SyntaxError)[^"]*)"', err)]
    return out, errs


def check(exe: str, base: str, query: dict) -> dict:
    """{ok, fails} of one harness case."""
    with tempfile.TemporaryDirectory() as prof:
        dom, errs = run(exe, prof, f"{base}/check.html?{urlencode(query)}", (int(query["w"]), int(query["h"])), ["--dump-dom"])
    m = re.search(r'<pre id="out"[^>]*>(.*?)</pre>', dom, re.S)
    res: dict = json.loads(html.unescape(m.group(1))) if m and m.group(1).strip() else {"ok": False, "fails": ["harness gave no result"]}
    fails: list[str] = [f"page error: {e}" for e in errs] + list(res["fails"])
    return {"ok": bool(res["ok"]) and not errs, "fails": fails, "notes": list(res.get("notes", []))}


MIN_FREE = 5 << 30  # a Chrome run that goes wrong can fill the disk; stop before that


def disk_ok() -> bool:
    return shutil.disk_usage(tempfile.gettempdir()).free > MIN_FREE


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / ".task" / "dash-shots"))
    ap.add_argument("--shots", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--state", choices=("ok", "empty", "down", "variants"), default="ok", help="the server state the screenshots use")
    ap.add_argument("--base", default="", help="a running dash (it must serve check.html): read-only survey cases only")
    args = ap.parse_args(argv)
    exe = chrome()
    servers = {} if args.base else {st: serve(st) for st in ("ok", "empty", "down", "variants")}
    base = args.base.rstrip("/") or f"http://127.0.0.1:{servers[args.state][1]}"
    bad = 0
    for name, case in LIVE_CASES if args.base else CASES:
        if args.only and args.only not in name:
            continue
        query = {k: v for k, v in case.items() if k != "state"}
        state = str(case.get("state", "ok"))
        if not disk_ok():
            sys.exit("less than 5 GB free: stopping")
        res = check(exe, base if args.base else f"http://127.0.0.1:{servers[state][1]}", query)
        bad += 0 if res["ok"] else 1
        print(f"{'PASS' if res['ok'] else 'FAIL'} {name}" + "".join(f"\n  - {f}" for f in res["fails"][:40])
              + ("".join(f"\n  · {n}" for n in res["notes"]) if args.base else ""))
    if args.shots:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for stem, page, h, size in SHOTS:
            if args.only and args.only not in stem:
                continue
            for theme in ("light", "dark"):
                if not disk_ok():
                    sys.exit("less than 5 GB free: stopping")
                q = {"scn": "view", "page": page, "hash": h, "w": size[0], "h": size[1], "theme": theme}
                path = out / f"{stem}-{'phone' if size[0] <= 600 else 'mid' if size[0] < 1000 else 'desktop'}-{theme}.png"
                with tempfile.TemporaryDirectory() as prof:
                    _, errs = run(exe, prof, f"{base}/check.html?{urlencode(q)}", (size[0], size[1] + 88), [f"--screenshot={path}"])
                print(f"shot {path}" + "".join(f"\n  - page error: {e}" for e in errs))
    for srv, _ in servers.values():  # none with --base
        srv.shutdown()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
