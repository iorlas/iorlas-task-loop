#!/usr/bin/env python3
"""Offline cockpit browser assertions; real page/handler, fake delegate, no tracker or vendor access."""
import argparse
import contextlib
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "taskloop_dash" / "static" / "index.html"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import glob  # noqa: E402
import subprocess  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from taskloop_dash.http import make_handler  # noqa: E402

ROUTE = "/fixture/iorlas-delegate/1.0/skills/delegate/route.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    evidence = Path(parser.parse_args().evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    tmp = evidence / "tmp"
    tmp.mkdir(exist_ok=True)
    results = {"assertions": [], "delegate_calls": [], "status_requests": []}
    until = time.time() + 12
    hostile = '<img src="https://vendor.invalid/quota" onerror="window.injected=true">'
    long_name = "UNKNOWN_" + "long_lane_" * 12
    fixture = {"v": 1, "lanes": {
        "OPENAI_SUBSCRIPTION": {"emoji": "🛰️", "model": "gpt-fixture", "out": False,
                                "reason": "ready", "out_until": until,
                                "usage": [{"window": "5h", "used_pct": 78, "resets_at": until},
                                          {"window": "week", "used_pct": 6},
                                          {"window": "month", "used_pct": None, "resets_at": until}]},
        "CLAUDE_SUBSCRIPTION": {"model": hostile, "out": True, "out_until": time.time() - 1,
                                "reason": hostile, "five": 100, "week": 21},
        long_name: {}}}
    state = {"mode": "initial", "error": False}
    lock = threading.Lock()

    def check(label, condition=True):
        assert condition, label
        results["assertions"].append(label)

    def fake_run(args, **kwargs):
        assert args == [sys.executable, ROUTE, "status", "--json"], args
        with lock:
            mode = state["mode"]
            results["delegate_calls"].append(args)
            results["status_requests"].append(mode)
            if state["error"]:
                return mock.Mock(returncode=1, stdout="", stderr="fixture unavailable")
            return mock.Mock(returncode=0, stdout=json.dumps(fixture), stderr="")

    def forbidden(*args, **kwargs):
        raise AssertionError("scenario attempted tracker, credentials or local state access")

    def fake_asks():
        return {"asks": [], "delegate": dash.lanes.delegate_status()}

    # Restrict the real handler to the three read-only routes exercised by this scenario.
    dash = make_dash(config=tmp / "state", home=tmp / "home")

    class Handler(make_handler(dash, 0, ["127.0.0.1"], PAGE, PAGE, forbidden, "")):
        def do_GET(self):
            if self.path.split("?", 1)[0] not in ("/", "/api/asks", "/api/tasks", "/favicon.ico"):
                return self.send(404, b"scenario route blocked", "text/plain")
            super().do_GET()

        def do_POST(self):
            self.send(405, b"scenario is read-only", "text/plain")

    errors, external, navigations = [], [], []
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(dash.asks, "asks", side_effect=fake_asks))
        stack.enter_context(mock.patch.object(dash.tasks, "api_tasks", return_value={"tasks": [], "host": "fixture"}))
        stack.enter_context(mock.patch.object(dash.beads, "bd_json", side_effect=forbidden))
        stack.enter_context(mock.patch.object(glob, "glob", return_value=[ROUTE]))
        stack.enter_context(mock.patch.object(subprocess, "run", side_effect=fake_run))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        stack.callback(httpd.server_close)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        stack.callback(httpd.shutdown)
        origin = "http://127.0.0.1:%d" % httpd.server_address[1]
        with sync_playwright() as pw, tempfile.TemporaryDirectory(dir=tmp, prefix="browser-") as profile:
            context = pw.chromium.launch_persistent_context(
                profile, headless=True, viewport={"width": 1280, "height": 1000},
                env={**os.environ, "TMPDIR": str(tmp)}, service_workers="block")
            try:
                def restrict(route):
                    if route.request.url.startswith(origin + "/"):
                        assert not route.request.headers.get("authorization")
                        return route.continue_()
                    external.append(route.request.url)
                    route.abort()

                context.route("**/*", restrict)
                page = context.pages[0]
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("framenavigated", lambda frame: navigations.append(frame.url)
                        if frame == page.main_frame else None)
                response = page.goto(origin + "/#tasks")
                check("page loads without authentication", response.status == 200)
                rows = page.locator("#lanes .lane")
                expect(rows).to_have_count(3)
                first = rows.nth(0)
                expect(first).to_have_attribute("data-lane", "OPENAI_SUBSCRIPTION")
                expect(first.locator(".lane-emoji")).to_have_text("🛰️")
                expect(first).to_contain_text("Model: gpt-fixture")
                expect(first).to_contain_text("Reason: ready")
                expect(first).to_have_attribute("data-state", "available")
                expect(first.locator(".lane-unlock time")).to_have_attribute(
                    "datetime", datetime.fromtimestamp(until, timezone.utc).isoformat(
                        timespec="milliseconds").replace("+00:00", "Z"))
                check("lane identity, emoji, model, reason, state and exact unlock time render")
                windows = first.locator(".usage-window")
                expect(windows).to_have_count(3)
                for i, (label, pct) in enumerate((("5h", "78"), ("week", "6"), ("month", None))):
                    expect(windows.nth(i)).to_contain_text(label)
                    progress = windows.nth(i).locator("progress")
                    if pct is None:
                        check("unknown usage is not zero", progress.get_attribute("value") is None)
                        expect(windows.nth(i)).to_contain_text("usage unknown")
                    else:
                        expect(progress).to_have_attribute("value", pct)
                        expect(windows.nth(i)).to_contain_text(pct + "% used")
                expect(windows.nth(2).locator("time")).to_have_count(1)
                expect(rows.nth(1).locator("progress").nth(0)).to_have_attribute("value", "100")
                check("every supplied window renders, including legacy windows and unknown usage with reset")
                expect(rows.nth(2)).to_contain_text("Model: unknown")
                expect(rows.nth(2)).to_contain_text("Reason: unknown")
                expect(rows.nth(2)).to_contain_text("Countdown unknown")
                expect(rows.nth(2)).to_contain_text("Usage unknown")
                expect(rows.nth(2)).to_have_attribute("data-state", "unknown")
                check("absent lane fields remain explicitly unknown")
                expect(rows.nth(1)).to_contain_text(hostile)
                expect(rows.nth(1).locator("img")).to_have_count(0)
                check("vendor text is escaped", page.evaluate("window.injected === undefined"))
                countdown = first.locator(".countdown").inner_text()
                page.wait_for_function("old => document.querySelector('#lanes .countdown').textContent !== old", arg=countdown)
                check("countdown ticks without a reload")
                expect(rows.nth(1)).to_have_attribute("data-state", "out")
                expect(rows.nth(1).locator(".countdown")).to_have_text("Time reached · awaiting delegate status")
                check("expired countdown never marks a lane available")
                page.screenshot(path=str(evidence / "cockpit-desktop.png"), full_page=True)

                # Change input only. The existing 2.5-second polling loop must do the rest.
                def transition(mode, out):
                    with lock:
                        state["mode"] = mode
                        fixture["lanes"]["OPENAI_SUBSCRIPTION"].update(out=out, reason=mode)
                        start = len(results["status_requests"])
                    with page.expect_response(lambda r: r.url == origin + "/api/asks", timeout=6000):
                        pass
                    expect(first).to_have_attribute("data-state", "out" if out else "available", timeout=1000)
                    expect(first.locator(".lane-reason")).to_contain_text(mode, timeout=1000)
                    with lock:
                        check(mode + " is rendered by the next automatic refresh",
                              results["status_requests"][start:] == [mode])

                transition("quota reached", True)
                transition("recovered", False)
                with lock:
                    state["error"] = True
                expect(page.locator("#lanes")).to_contain_text("fixture unavailable", timeout=6000)
                expect(rows).to_have_count(0)
                check("failed status is explicit and removes stale availability")
                with lock:
                    state["error"] = False
                expect(rows).to_have_count(3, timeout=6000)
                check("status display recovers automatically")
                page.set_viewport_size({"width": 375, "height": 812})
                measurements = page.locator("#lanes").evaluate("""el => ({
                    viewport: innerWidth, document: document.documentElement.scrollWidth,
                    fields: [...el.querySelectorAll('.lane, .lane b, .lane-reason, .lane-unlock, .usage-window')]
                      .map(e => {const r=e.getBoundingClientRect();const s=getComputedStyle(e);
                        return {left:r.left,right:r.right,width:r.width,clipped:e.scrollWidth>e.clientWidth+1,
                                visible:s.display!=='none'&&s.visibility!=='hidden'&&r.height>0}})})""")
                results["phone"] = measurements
                check("phone has no horizontal document overflow", measurements["document"] <= 375)
                check("phone fields wrap visibly within viewport", all(
                    m["visible"] and not m["clipped"] and m["left"] >= 0 and m["right"] <= 375
                    for m in measurements["fields"]))
                page.screenshot(path=str(evidence / "cockpit-phone.png"), full_page=True)
                check("polling did not navigate or reload the document", len(navigations) == 1)
                check("no external requests or injected markup", external == [])
                check("no browser script errors", errors == [])
                check("all status acquisitions invoke only route.py status --json",
                      len(results["delegate_calls"]) >= 5)
                results["passed"] = True
            finally:
                context.close()
                results.update(browser_errors=errors, blocked_external_requests=external)
                (evidence / "cockpit-assertions.json").write_text(json.dumps(results, indent=2) + "\n")
    print("cockpit scenario: %d assertions passed" % len(results["assertions"]))


if __name__ == "__main__":
    main()
