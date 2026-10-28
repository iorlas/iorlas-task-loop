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
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.logs import typed  # noqa: E402
from taskloop_dash.api import live, overview  # noqa: E402
from taskloop_dash.views import live_state  # noqa: E402
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
    put(log, [typed("run_start", T, run="%s-%s" % (BEAD, STAMP), bead=BEAD, worktree=""),
              typed("cmd_start", T + 1, id="m1", text="git fetch -q origin"),
              typed("cmd_end", T + 3, id="m1", exit=0),
              typed("step_start", T + 4, id="n1", text="write: x", step="write"),
              typed("call_start", T + 5, id="c1", n=1, step="write", node="n1", role="worker")])
    lf = os.path.join(eng, "%s-%s.live" % (BEAD, STAMP), "01-write.jsonl")
    put(lf, [{"t": T + 6, "k": "start", "harness": "codex", "lane": "CODEX", "model": "gpt-x", "effort": "high", "role": "worker", "pid": 1},
             {"t": T + 6.5, "k": "msg", "text": "between the start and the command"},
             {"t": T + 7, "k": "cmd", "id": "1", "text": "pytest -q", "cwd": "/w"}])
    return log, lf


class Feed(unittest.TestCase):
    def run_of(self, d):
        log, lf = make_run(d)
        return log, lf, live.LiveRun(log)

    def test_merge_by_time_seq_keys_and_the_cursor(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf, run = self.run_of(d)
            run.refresh()
            a = live.page(run)
            ts = [e["t"] for e in a["events"]]
            self.assertEqual(ts, sorted(ts))
            self.assertEqual([e["seq"].split(":")[0] for e in a["events"]][:3], ["engine", "engine", "engine"])
            self.assertEqual(len({e["seq"] for e in a["events"]}), len(a["events"]))
            pairs = {(e["src"], e["k"], e.get("id")) for e in a["events"]}
            self.assertIn(("engine", "cmd_end", "m1"), pairs)
            self.assertIn(("01-write", "cmd", "1"), pairs)
            self.assertEqual(live.page(run, live.decode(a["cursor"]))["events"], [])  # nothing new: nothing
            put(lf, [{"t": T + 9, "k": "cmd_end", "id": "1", "exit": 1, "out": "boom", "secs": 2.0}])
            with open(lf, "a") as f:
                f.write('{"t": %s, "k": "msg", "te' % (T + 10))  # a half-written line waits
            run.refresh()
            b = live.page(run, live.decode(a["cursor"]))
            self.assertEqual([(e["k"], e["id"]) for e in b["events"]], [("cmd_end", "1")])
            with open(lf, "a") as f:
                f.write('xt": "hi"}\n')
            put(log, [typed("warn", T + 11, text="slow")])
            run.refresh()
            c = live.page(run, live.decode(b["cursor"]))
            self.assertEqual([(x["k"], x["t"]) for x in c["events"]], [("msg", T + 10), ("warn", T + 11)])
            self.assertIsNone(live.decode("garbage!"))

    def test_every_engine_kind_passes_through(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf, run = self.run_of(d)
            put(log, [typed("wait_start", T + 12, id="w1", what="lane", holder="DEEPSEEK_FREE"), typed("wait_end", T + 13, id="w1", secs=60),
                      typed("vendor_error", T + 14, node="write", reason="hung"), typed("kill", T + 15, what="call", why="silent"),
                      typed("lock", T + 16, what="land_lock", holder="tl-2"), typed("unlock", T + 17, what="land_lock", secs=1.0)])
            run.refresh()
            got = {e["k"]: e for e in live.page(run)["events"]}
            for k in ("wait_start", "wait_end", "vendor_error", "kill", "lock", "unlock"):
                self.assertIn(k, got)
            self.assertEqual((got["wait_end"]["secs"], got["vendor_error"]["reason"]), (60, "hung"))

    def test_before_pages_return_the_rest_exactly_once(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf, run = self.run_of(d)
            put(log, [typed("note", T + 20 + i, text="n%d" % i) for i in range(30)])
            put(lf, [{"t": T + 20.5 + i, "k": "msg", "text": "m%d" % i} for i in range(30)])
            run.refresh()
            everything = [e["seq"] for e in run.events()]
            seen, got = [], live.page(run, limit=25)
            while True:
                seen = [e["seq"] for e in got["events"]] + seen
                if not got["before"]:
                    break
                got = live.page(run, before=live.decode(got["before"]), limit=25)
            self.assertEqual(seen, everything)

    def test_a_run_without_worker_files(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf, run = self.run_of(d)
            os.remove(lf)
            run.refresh()
            self.assertEqual({e["src"] for e in run.events()}, {"engine"})

    def test_long_poll_returns_when_a_file_grows_and_waits_when_none_does(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf, run = self.run_of(d)
            cur = live.page(live.poll(run, None) and run)["cursor"]
            t0 = time.monotonic()
            self.assertEqual(live.poll(run, live.decode(cur), wait=2)["events"], [])
            self.assertGreaterEqual(time.monotonic() - t0, 2)
            threading = __import__("threading")
            threading.Timer(0.5, put, (lf, [{"t": T + 30, "k": "tool", "id": "9", "text": "edit"}])).start()
            t0 = time.monotonic()
            got = live.poll(run, live.decode(cur), wait=2)
            self.assertLess(time.monotonic() - t0, 2.5)
            self.assertEqual([e["k"] for e in got["events"]], ["tool"])


class States(unittest.TestCase):
    """The eight states of the state line, each from the open pairs and the last events."""

    def ev(self, *items):
        out = []
        for i, (src, k, t, kw) in enumerate(items):
            out.append(dict(kw, src=src, k=k, t=T + t, seq="%s:%d" % (src, i)))
        return out

    def st(self, items, now=100, alive=True, output_t=lambda e: None):
        return live_state.state_of(self.ev(*items), T + now, alive, output_t)

    def test_each_state(self):
        base = [("engine", "step_start", 1, {"id": "n1", "step": "write", "text": "write"})]
        w = ("w", "start", 2, {"lane": "ZAI", "model": "glm"})
        self.assertEqual(self.st(base + [("engine", "wait_start", 3, {"id": "w1", "what": "lane", "holder": "X"})])["what"], "wait")
        chk = self.st(base + [("engine", "check_start", 3, {"id": "k1", "check": "unit", "cmd": "pytest", "round": 1, "log": "checks/a.log"})],
                      output_t=lambda e: T + 50)
        self.assertEqual((chk["what"], chk["last_output_t"]), ("check", T + 50))
        self.assertEqual(self.st(base + [("engine", "gate_start", 3, {"cmd": "just check"})])["what"], "check")
        self.assertEqual(self.st(base + [w, ("w", "cmd", 4, {"id": "1", "text": "pytest -q"})])["what"], "tool")
        self.assertEqual(self.st(base + [w, ("w", "msg", 90, {"text": "hi"})], now=100)["what"], "thinking")
        self.assertEqual(self.st(base + [w, ("w", "msg", 10, {"text": "hi"})], now=100)["what"], "silent")
        self.assertEqual(self.st(base + [("engine", "kill", 5, {"what": "call", "why": "silent"})])["what"], "hung")
        self.assertEqual(self.st(base)["what"], "engine")
        self.assertEqual(self.st(base + [("engine", "close", 6, {"outcome": "landed"})])["what"], "ended")
        self.assertEqual(self.st(base, alive=False)["what"], "ended")

    def test_a_closed_pair_is_not_open_and_pairs_match_by_src_and_id(self):
        items = [("engine", "cmd_start", 1, {"id": "a"}), ("w", "cmd", 2, {"id": "a"}), ("engine", "cmd_end", 3, {"id": "a"})]
        opened = live_state.open_pairs(self.ev(*items))
        self.assertEqual([(s, k) for s, k, _ in opened], [("w", "cmd")])


class Overview(unittest.TestCase):
    def test_three_rows_one_alive_one_paused_one_queued(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf = make_run(d)
            eng = os.path.dirname(log)
            other = os.path.join(eng, "tl-live.2-%s.jsonl" % STAMP)
            put(other, [typed("run_start", T, run="tl-live.2-" + STAMP, bead="tl-live.2", worktree=""), typed("step_start", T + 1, id="n1", step="write"),
                        typed("step_end", T + 5, id="n1", step="write", outcome="done"), typed("step_start", T + 6, id="n2", step="close", text="close"),
                        typed("close", T + 6, outcome="blocked", why="paused: no lane for write until 09:02 (lane_out: OPENAI_SUBSCRIPTION)")])
            entries = []
            for bead, path, alive in ((BEAD, log, True), ("tl-live.2", other, False)):
                run = live.LiveRun(path)
                run.refresh()
                entries.append({"bead": bead, "repo": "r", "title": "", "name": os.path.basename(path)[:-6], "run": run, "alive": alive})
            lanes = [{"name": "OPENAI_SUBSCRIPTION", "out": True, "out_until": T + 5000, "usage": [{"window": "5h", "used_pct": 97}]}]
            queue = [{"repo": "r", "bead": "tl-live.3", "prio": 2, "since": T, "ahead": 2}]
            out = overview.overview(entries, queue, lanes, T + 100)
            rows = out["beads"]
            self.assertEqual([(r["bead"], r["state"]) for r in rows], [(BEAD, "tool"), ("tl-live.3", "queued"), ("tl-live.2", "paused")])
            self.assertEqual(rows[1]["ahead"], 2)
            self.assertEqual((rows[2]["lane"], rows[2]["until"]), ("OPENAI_SUBSCRIPTION", T + 5000))
            self.assertEqual(out["lanes"], [{"id": "OPENAI_SUBSCRIPTION", "state": "out", "out_until": T + 5000, "used_pct": 97}])


class RunningFromTheLog(unittest.TestCase):
    """running comes from the typed log alone: no end record, no stale heartbeat, no process needed (a scripted lane has none)."""

    def test_steps_and_no_end_record_is_running_with_no_process(self):
        with tempfile.TemporaryDirectory() as d:
            log, lf = make_run(d)
            put(log, [typed("run_start", T, run="%s-%s" % (BEAD, STAMP), bead=BEAD, worktree="/no/such/worktree")], mode="w")
            put(log, [typed("step_start", T + 1, id="n1", step="write", text="write")])
            run = live.LiveRun(log)
            run.refresh()
            now = os.stat(log).st_mtime + 1
            self.assertTrue(run.is_alive(now, 1200))
            ans = live.answer(run, BEAD, "n", run.is_alive(now, 1200), now=now)
            self.assertTrue(ans["running"])
            rows = overview.overview([{"bead": BEAD, "repo": "r", "title": "", "name": "n", "run": run, "alive": run.is_alive(now, 1200)}], [], [], now)["beads"]
            self.assertEqual([r["bead"] for r in rows], [BEAD])
            self.assertFalse(run.is_alive(now + 5000, 1200))  # the heartbeat lapsed
            put(log, [typed("close", T + 9, outcome="landed", why="")])
            run.refresh()
            self.assertFalse(run.is_alive(now, 1200))


class Page(unittest.TestCase):
    """The page is one html file; its renderer keys rows by src + kind + id and ticks from data-t0 (checked on the source)."""

    def test_the_page_source(self):
        html = (ROOT / "src" / "taskloop_dash" / "static" / "live.html").read_text(encoding="utf-8")
        self.assertIn("/api/live?", html)
        self.assertIn("/api/live/overview", html)
        self.assertIn("dataset.t0", html)       # an open row ticks from its start
        self.assertIn("dataset.t1", html)       # a closed one freezes at its end
        self.assertIn("'exit '+e.exit", html)   # a closed command shows its exit code
        self.assertIn("e.secs", html)           # and its seconds
        self.assertNotIn("innerHTML", html)     # append-only: rows are built, never re-parsed
        self.assertIn("max-width:600px", html)  # the phone layout
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))  # no CDN


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

    def test_engine_numbers_its_calls(self):
        import engine
        with tempfile.TemporaryDirectory() as d:
            e = object.__new__(engine.Engine)
            e.log_path = Path(d) / ("%s-%s.jsonl" % (BEAD, STAMP))
            p1, p2 = e.live("plan"), e.live("write")
            self.assertTrue(p1.endswith(".live/01-plan.jsonl") and p2.endswith(".live/02-write.jsonl"))
            self.assertTrue(os.path.isdir(os.path.dirname(p1)))
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
            p = subprocess.Popen([sys.executable, "-m", "taskloop_dash", "--port", str(port)], env=env,
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
                self.assertEqual((a["bead"], a["run"], a["step"], a["worker"]["lane"], a["worker"]["model"]), (BEAD, "%s-%s" % (BEAD, STAMP), "write", "CODEX", "gpt-x"))
                self.assertIn(a["state"]["what"], ("tool",))
                self.assertEqual([e["t"] for e in a["events"]], sorted(e["t"] for e in a["events"]))
                put(lf, [{"t": T + 20, "k": "tool", "id": "2", "text": "edit a.py"}])
                b = get("/api/live?bead=%s&run=%s-%s&since=%s" % (BEAD, BEAD, STAMP, a["cursor"]))
                self.assertEqual([e["k"] for e in b["events"]], ["tool"])
                self.assertEqual(get("/api/live/overview")["beads"][0]["bead"], BEAD)
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
