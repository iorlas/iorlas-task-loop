"""The Live view: /api/live merges the engine log with the worker's live files, the engine hands delegate the file, the page loads."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "task-loop"
for sub in ("dash", "", "tests"):
    sys.path.insert(0, str(SKILL / sub) if sub != "tests" else str(ROOT / "tests"))
import live  # noqa: E402
from lanes import call  # noqa: E402

BEAD, STAMP = "tl-live.1", "20261026-100000"
T = 1793000000.0


def put(path, rows, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def make_run(root):
    """An engine log with a command and a write step, and the live file of its write call."""
    eng = os.path.join(root, "task-loop", "engine")
    log = os.path.join(eng, "%s-%s.jsonl" % (BEAD, STAMP))
    put(log, [{"t": T, "kind": "run", "text": "run: fresh", "run": "%s-%s" % (BEAD, STAMP), "bead": BEAD, "worktree": ""},
              {"t": T + 1, "kind": "cmd", "text": "git fetch -q origin"},
              {"t": T + 3, "kind": "note", "text": "exit 0", "exit": 0},
              {"t": T + 4, "kind": "node", "text": "write: x", "id": 1, "step": "write"},
              {"t": T + 5, "kind": "note", "text": "live: f", "live": "f"}])
    lf = os.path.join(eng, "%s-%s.live" % (BEAD, STAMP), "01-write.jsonl")
    put(lf, [{"t": T + 6, "k": "start", "harness": "codex", "lane": "CODEX", "model": "gpt-x", "effort": "high", "role": "worker", "pid": 1},
             {"t": T + 2, "k": "msg", "text": "earlier than the engine rows' end"},
             {"t": T + 7, "k": "cmd", "id": "1", "text": "pytest -q", "cwd": "/w"}])
    return log, lf


class Feed(unittest.TestCase):
    def test_merge_sort_and_cursor(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf = make_run(d)
            a = live.feed(log)
            self.assertEqual([e["t"] for e in a["events"]], sorted(e["t"] for e in a["events"]))
            kinds = [(e["src"], e["k"]) for e in a["events"]]
            self.assertIn(("engine", "cmd_end"), kinds)       # the engine's "exit 0" row closes its command
            self.assertIn(("01-write", "cmd"), kinds)
            self.assertNotIn("live: f", [e.get("text") for e in a["events"]])  # the live note is bookkeeping
            self.assertEqual((a["step"], a["meta"]["lane"], a["worker_detail"]), ("write", "CODEX", True))
            end = [e for e in a["events"] if e["k"] == "cmd_end"][0]
            self.assertEqual(end["id"], [e for e in a["events"] if e["src"] == "engine" and e["k"] == "cmd"][0]["id"])
            # nothing new: the cursor yields nothing, and reads no file again
            b = live.feed(log, a["cursor"])
            self.assertEqual(b["events"], [])
            # a command closes in a later call, and a half-written line waits
            put(lf, [{"t": T + 9, "k": "cmd_end", "id": "1", "exit": 1, "out": "boom", "secs": 2.0}])
            with open(lf, "a") as f:
                f.write('{"t": %s, "k": "msg", "te' % (T + 10))
            c = live.feed(log, b["cursor"])
            self.assertEqual([(e["k"], e["id"]) for e in c["events"]], [("cmd_end", "01-write:1")])
            with open(lf, "a") as f:
                f.write('xt": "hi"}\n')
            put(log, [{"t": T + 11, "kind": "warn", "text": "slow"}])
            e = live.feed(log, c["cursor"])
            self.assertEqual([(x["k"], x["t"]) for x in e["events"]], [("msg", T + 10), ("warn", T + 11)])
            self.assertEqual(len(live.feed(log, "garbage!")["events"]), len(a["events"]) + 3)  # a bad cursor starts over, with what grew since

    def test_every_engine_kind_passes_through(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf = make_run(d)
            put(log, [{"t": T + 12, "kind": "wait", "text": "a lane", "what": "lane", "secs": 60, "in_budget": False},
                      {"t": T + 13, "kind": "vendor_error", "text": "write: hung", "reason": "hung", "items": [1]},
                      {"t": T + 14, "kind": "kill", "text": "k"}])
            got = {e["k"]: e for e in live.feed(log)["events"]}
            for k in ("wait", "vendor_error", "kill"):
                self.assertIn(k, got)
            self.assertEqual((got["wait"]["secs"], got["vendor_error"]["reason"]), (60, "hung"))
            self.assertNotIn("items", got["vendor_error"])

    def test_run_without_worker_files(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf = make_run(d)
            os.remove(lf)
            self.assertFalse(live.feed(log)["worker_detail"])


class CallSite(unittest.TestCase):
    def test_file_name(self):
        p = call.live_file("/e/tl-1-20261026-100000.jsonl", 3, "write")
        self.assertEqual(p, "/e/tl-1-20261026-100000.live/03-write.jsonl")
        self.assertTrue(call.live_file("/e/x.jsonl", 12, "re view/2").endswith(".live/12-re-view-2.jsonl"))

    def test_the_call_sets_the_env(self):
        import delegate_link as dl
        from support import fake_route
        seen = []

        def runner(cmd, **kw):
            seen.append(kw.get("env"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        res = dl.Resolved(Path("/fake"), "/fake/route.py", fake_route.CONTRACT, "explicit")
        dl.call(res, dl.CallRequest("worker", "p", {}, ".", live="/x/y.live/01-write.jsonl"), runner=runner)
        self.assertEqual(seen[0]["DELEGATE_LIVE_FILE"], "/x/y.live/01-write.jsonl")
        dl.call(res, dl.CallRequest("worker", "p", {}, "."), runner=runner)
        self.assertIsNone(seen[1])

    def test_engine_numbers_its_calls_and_logs_a_note(self):
        import engine
        with tempfile.TemporaryDirectory() as d:
            e = object.__new__(engine.Engine)
            e.log_path = Path(d) / ("%s-%s.jsonl" % (BEAD, STAMP))
            notes = []
            e.log = lambda kind, text, **kw: notes.append((kind, text, kw))
            p1, p2 = e.live("plan"), e.live("write")
            self.assertTrue(p1.endswith(".live/01-plan.jsonl") and p2.endswith(".live/02-write.jsonl"))
            self.assertTrue(os.path.isdir(os.path.dirname(p1)))
            self.assertEqual([(k, kw["live"]) for k, _, kw in notes], [("note", p1), ("note", p2)])
            with open(engine.__file__, encoding="utf-8") as f:
                src = f.read()
            self.assertEqual(src.count("live=self.live("), 2)  # both delegate call sites pass it


class Served(unittest.TestCase):
    def test_endpoint_and_page(self):
        from test_dash import free_port
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            log, lf = make_run(d)
            port = free_port()
            env = dict(os.environ, XDG_CONFIG_HOME=d, APPDATA=d, TASK_LOOP_DASH_BIND="127.0.0.1", HOME=d, USERPROFILE=d)
            p = subprocess.Popen([sys.executable, str(SKILL / "dash" / "server.py"), "--port", str(port)], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = "http://127.0.0.1:%d" % port
                end = time.monotonic() + 90
                while True:
                    try:
                        urllib.request.urlopen(base + "/api/version", timeout=5)
                        break
                    except OSError:
                        self.assertLess(time.monotonic(), end, "the server never answered")
                        time.sleep(0.1)

                def get(u):
                    return json.loads(urllib.request.urlopen(base + u, timeout=60).read())
                a = get("/api/live?bead=" + BEAD)
                self.assertEqual((a["bead"], a["run"], a["step"], a["lane"], a["model"]), (BEAD, "%s-%s" % (BEAD, STAMP), "write", "CODEX", "gpt-x"))
                self.assertEqual([e["t"] for e in a["events"]], sorted(e["t"] for e in a["events"]))
                put(lf, [{"t": T + 20, "k": "tool", "id": "2", "text": "edit a.py"}])
                b = get("/api/live?bead=%s&run=%s-%s&since=%s" % (BEAD, BEAD, STAMP, a["cursor"]))
                self.assertEqual([e["k"] for e in b["events"]], ["tool"])
                self.assertEqual(a["newest"], a["run"])
                self.assertFalse(get("/api/live?bead=nope.1")["found"])
                self.assertFalse(get("/api/live?bead=--help")["found"])
                page = urllib.request.urlopen(base + "/live?bead=" + BEAD, timeout=60).read()
                self.assertIn(b"/api/live", page)
                self.assertIn(b"/live?bead=", urllib.request.urlopen(base + "/", timeout=60).read())
            finally:
                p.terminate()
                try:
                    p.wait(60)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


if __name__ == "__main__":
    unittest.main()
