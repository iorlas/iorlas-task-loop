import json
import os
import glob
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support import tools  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from taskloop_dash import bind as bind_mod, tails as tails_mod  # noqa: E402
from taskloop_dash.api import lanes as lanes_mod  # noqa: E402


SH_FAKE = unittest.skipIf(os.name == "nt", "the bd fake is a #!/bin/sh script, which Windows cannot execute")


def line(**kw):
    return json.dumps(kw) + "\n"


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.dash = make_dash()
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "s.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_transcript_events(self):
        self.p.write_text(
            line(type="user", timestamp="2026-10-18T10:00:00Z", message={"content": "do the thing"})
            + line(type="assistant", timestamp="2026-10-18T10:00:01Z", message={"content": [
                {"type": "text", "text": "On it."},
                {"type": "tool_use", "id": "u1", "name": "Bash", "input": {"command": "ls"}}]})
            + line(type="user", timestamp="2026-10-18T10:00:03Z", message={"content": [
                {"type": "tool_result", "tool_use_id": "u1", "content": "a b", "is_error": True}]})
            + "not json\n")
        evs = self.dash.events.claude(str(self.p))
        self.assertEqual([e["kind"] for e in evs], ["user", "msg", "cmd"])
        self.assertEqual(evs[2]["state"], "fail")
        self.assertEqual(evs[2]["dur"], 2)

    def test_window_filters_events(self):
        self.p.write_text(
            line(type="assistant", timestamp="2026-10-18T10:00:00Z", message={"content": [{"type": "text", "text": "a"}]})
            + line(type="assistant", timestamp="2026-10-18T11:00:00Z", message={"content": [{"type": "text", "text": "b"}]})
            + line(type="assistant", timestamp="2026-10-18T12:00:00Z", message={"content": [{"type": "text", "text": "c"}]}))
        t = tails_mod.parse_ts
        evs = self.dash.events.claude(str(self.p), t("2026-10-18T10:30:00Z"), t("2026-10-18T11:30:00Z"))
        self.assertEqual([e["text"] for e in evs], ["b"])

    def test_codex_log_events(self):
        self.p.write_text("[2026-10-18T10:00:00Z] Running command: /bin/zsh -lc 'just test'\n"
                          "[2026-10-18T10:00:05Z] Command failed: /bin/zsh -lc 'just test' (exit 1)\n"
                          "[2026-10-18T10:00:06Z] Assistant message captured: done\n")
        evs = self.dash.events.codex_log(str(self.p))
        self.assertEqual(evs[0]["text"], "just test")
        self.assertEqual(evs[0]["state"], "fail")
        self.assertEqual(evs[1]["text"], "done")

    def test_tail_reads_only_the_end(self):
        self.p.write_text("x" * 100 + "\n" + "keep\n")
        self.assertEqual(self.dash.env.tails.tail_lines(str(self.p), limit=7), ["keep"])


class Spans(unittest.TestCase):
    def setUp(self):
        self.dash = make_dash()

    def test_reclaim_ends_previous_span_and_close_ends_current(self):
        evs = [{"t": 1, "kind": "claim", "bead": "b", "session": "s1"},
               {"t": 2, "kind": "stage", "bead": "b", "session": "s1", "text": "write"},
               {"t": 5, "kind": "claim", "bead": "b", "session": "s2"},
               {"t": 9, "kind": "close", "bead": "b", "session": "s2"}]
        with mock.patch.object(self.dash.records, "events", return_value=evs):
            sp = self.dash.records.task_spans()["b"]
        self.assertEqual([(s["session"], s["from"], s["to"], s["end"]) for s in sp],
                         [("s1", 1, 5, "reclaimed"), ("s2", 5, 9, "close")])
        self.assertEqual(sp[0]["stage"], "write")

    def test_one_session_may_hold_two_beads(self):
        evs = [{"t": 1, "kind": "claim", "bead": "a", "session": "s"},
               {"t": 2, "kind": "claim", "bead": "b", "session": "s"}]
        with mock.patch.object(self.dash.records, "events", return_value=evs):
            sp = self.dash.records.task_spans()
        self.assertIsNone(sp["a"][0]["to"])
        self.assertIsNone(sp["b"][0]["to"])


class ResolveRepo(unittest.TestCase):
    def setUp(self):
        self.dash = make_dash()

    def test_a_link_may_name_the_repo_by_folder_or_not_at_all(self):
        known = ["/w/lifesim", "/w/other"]
        beads = {"/w/lifesim": [{"id": "lifesim-vbo"}], "/w/other": [{"id": "o-1"}]}
        with mock.patch.object(self.dash.records, "repos", return_value=known), \
                mock.patch.object(self.dash.beads, "beads_of", side_effect=lambda r: beads.get(r, [])):
            self.assertEqual(self.dash.beads.resolve_repo("/w/other"), "/w/other")
            self.assertEqual(self.dash.beads.resolve_repo("lifesim"), "/w/lifesim")
            self.assertEqual(self.dash.beads.resolve_repo("", "o-1"), "/w/other")
            self.assertEqual(self.dash.beads.resolve_repo("nope", "x-1"), "")


class Contract(unittest.TestCase):
    """agent-runs v1: the only way other tools' workers reach the dashboard."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name})
        self.env.start()
        self.dash = make_dash()
        self.runs = Path(self.tmp.name) / "agent-runs" / "runs"
        self.runs.mkdir(parents=True)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, name, rec):
        (self.runs / name).write_text(rec if isinstance(rec, str) else json.dumps(rec))

    def test_missing_folder_is_fine(self):
        self.runs.rmdir()
        self.assertEqual(self.dash.lanes.contract_lanes(), [])

    def test_lanes_only_when_fresh(self):
        lanes = Path(self.tmp.name) / "agent-runs" / "lanes"
        lanes.mkdir()
        (lanes / "fresh.json").write_text(json.dumps({"v": 1, "producer": "x", "at": time.time(),
                                                      "lanes": [{"name": "A", "usage": [{"window": "5h", "used_pct": 3}]}]}))
        (lanes / "stale.json").write_text(json.dumps({"v": 1, "producer": "y", "at": 0, "lanes": [{"name": "B"}]}))
        self.assertEqual([l["name"] for l in self.dash.lanes.contract_lanes()], ["A"])


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Live(unittest.TestCase):
    """The real server process, against an empty config: every endpoint answers."""

    def test_endpoints(self):
        with tempfile.TemporaryDirectory() as d:
            port = free_port()
            env = dict(os.environ, XDG_CONFIG_HOME=d, APPDATA=d, TASK_LOOP_DASH_BIND="127.0.0.1", HOME=d,
                       USERPROFILE=d)
            p = subprocess.Popen([sys.executable, "-m", "taskloop_dash",
                                  "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = "http://127.0.0.1:%d" % port
                for _ in range(50):
                    try:
                        v = json.loads(urllib.request.urlopen(base + "/api/version", timeout=1).read())
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail("server did not start")
                self.assertTrue(v["version"])
                self.assertIn(b"task-loop", urllib.request.urlopen(base + "/").read())
            finally:
                p.terminate()
                p.wait(5)


class PostAuth(unittest.TestCase):
    """Denis 2026-10-22: the queue is local, so no token from loopback or Tailscale (100.64.0.0/10); any other source needs it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name,
                                                "HOME": self.tmp.name, "USERPROFILE": self.tmp.name})
        self.env.start()
        self.state = Path(self.tmp.name) / "task-loop"
        self.tok = bind_mod.token(self.state)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_loopback_and_tailscale_need_no_token(self):
        for addr in ("127.0.0.1", "127.5.5.5", "::1", "::ffff:127.0.0.1", "100.64.0.1", "100.101.102.103", "100.127.255.254"):
            self.assertTrue(bind_mod.post_allowed(addr, None, lambda: self.tok), addr)
            self.assertTrue(bind_mod.post_allowed(addr, "Bearer wrong", lambda: self.tok), addr)

    def test_any_other_source_needs_the_token(self):
        for addr in ("192.168.1.20", "10.0.0.5", "172.17.0.2", "100.63.255.255", "100.128.0.1", "8.8.8.8", "fe80::1", "junk", ""):
            self.assertFalse(bind_mod.post_allowed(addr, None, lambda: self.tok), addr)
            self.assertFalse(bind_mod.post_allowed(addr, "Bearer wrong", lambda: self.tok), addr)
            self.assertFalse(bind_mod.post_allowed(addr, "Bearer ", lambda: self.tok), addr)
            self.assertTrue(bind_mod.post_allowed(addr, "Bearer " + self.tok, lambda: self.tok), addr)

    def test_the_address_comes_from_the_socket_not_a_header(self):
        src = (ROOT / "src" / "taskloop_dash" / "http.py").read_text(encoding="utf-8")
        self.assertIn("post_allowed(self.client_address[0]", src)
        self.assertNotIn("X-Forwarded-For", src)


class Asks(unittest.TestCase):
    """The owner answers an ask from the phone: a token only from outside loopback and Tailscale, first answer wins,
    the bead is commented and opened."""

    @SH_FAKE
    def test_answer_needs_the_token_and_reaches_the_bead_once(self):
        with tempfile.TemporaryDirectory() as d:
            port = free_port()
            d = Path(d)
            bin_ = d / "bin"
            bin_.mkdir()
            (bin_ / "bd").write_text("#!/bin/sh\necho \"$*\" >> %s\n" % (d / "bd.log"))
            (bin_ / "bd").chmod(0o755)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            (asks / "x-1.json").write_text(json.dumps({"v": 1, "id": "x-1-1", "bead": "x-1", "kind": "decision",
                                                       "question": "Old or new?", "t": time.time() - 3600,
                                                       "parks_at": time.time() + 86400, "status": "open",
                                                       "repo": str(d)}))
            env = dict(os.environ, XDG_CONFIG_HOME=str(d), APPDATA=str(d), TASK_LOOP_DASH_BIND="127.0.0.1", HOME=str(d),
                       USERPROFILE=str(d), PATH=str(bin_) + os.pathsep + os.environ["PATH"],
                       PYTHONPATH=os.pathsep.join([os.environ["PYTHONPATH"], str(ROOT / "skills" / "task-loop")]))
            p = subprocess.Popen([sys.executable, "-m", "taskloop_dash", "--ports", "tl:dash_ports",  # the launcher's bd, the fake one
                                  "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = "http://127.0.0.1:%d" % port
                for _ in range(50):
                    try:
                        urllib.request.urlopen(base + "/api/version", timeout=1)
                        break
                    except OSError:
                        time.sleep(0.1)
                a = json.loads(urllib.request.urlopen(base + "/api/asks").read())
                self.assertEqual([x["id"] for x in a["asks"]], ["x-1-1"])
                self.assertGreater(a["asks"][0]["age_s"], 3000)
                token = (d / "task-loop" / "dash.token").read_text().strip()

                def post(tok, text):
                    req = urllib.request.Request(base + "/api/answer", method="POST",
                                                 data=json.dumps({"ask": "x-1-1", "text": text}).encode(),
                                                 headers={"Content-Type": "application/json",
                                                          **({"Authorization": "Bearer " + tok} if tok else {})})
                    try:
                        return urllib.request.urlopen(req).status
                    except urllib.error.HTTPError as e:
                        return e.code
                self.assertEqual(post("", "new"), 200)  # loopback: no token
                self.assertEqual(post(token, "Old, actually."), 409)
                log = (d / "bd.log").read_text()
                self.assertIn("comments add x-1 new", log)
                self.assertIn("update x-1 --status open", log)
                self.assertNotIn("Old, actually", log)
                self.assertIn(b"Asks", urllib.request.urlopen(base + "/").read())
                self.assertNotIn(b"prompt(", urllib.request.urlopen(base + "/").read())
            finally:
                p.terminate()
                p.wait(5)


class AskOptions(unittest.TestCase):
    """An option is one click: it posts its answer text through /api/answer, and bd gets that exact text."""

    @SH_FAKE
    def test_an_option_answer_reaches_bd_with_the_exact_text_and_shows_as_answered(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            (d / "bin" / "bd").write_text("#!/bin/sh\nshift 2; for a in \"$@\"; do printf '[%s]' \"$a\"; done >> " + str(d / "bd.log") + "\necho >> " + str(d / "bd.log") + "\n")
            (d / "bin" / "bd").chmod(0o755)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            text = "B: keep it parked; relabel sim-later (no new code)"
            opts = [{"label": "Build it", "answer": "A: build now", "note": "4 stages"},
                    {"label": "Keep parked", "answer": text, "note": "none", "recommended": True}]
            (asks / "x-1.json").write_text(json.dumps({"v": 1, "id": "x-1-1", "bead": "x-1", "kind": "decision",
                                                       "question": "Build or park?", "t": time.time(), "status": "open",
                                                       "parks_at": time.time() + 86400, "repo": str(d), "options": opts}))
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "HOME": str(d), "USERPROFILE": str(d),
                   "PATH": str(d / "bin") + os.pathsep + os.environ["PATH"]}
            with mock.patch.dict(os.environ, env):
                self.dash = make_dash()
                shown = self.dash.asks.asks()["asks"][0]
                strip = lambda os: [{k: o[k] for k in ("label", "answer", "note", "recommended") if k in o} for o in os]
                self.assertEqual(strip(shown["options"]), opts)  # the page renders these (plus what happens next)
                self.assertEqual(strip(self.dash.asks.open_ask("x-1")["options"]), opts)
                clicked = shown["options"][1]["answer"]
                code, out = self.dash.asks.answer({"ask": "x-1-1", "text": clicked})
                self.assertEqual((code, out["ok"]), (200, True))
                self.assertIn("x-1", out["next"])
                self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "A: build now"})[0], 409)
                self.assertEqual(self.dash.asks.asks()["asks"][0]["answer"], text)
            log = (d / "bd.log").read_text().splitlines()
            self.assertEqual(log[0], "[comments][add][x-1][%s][--json]" % text)
            self.assertEqual(log[1], "[show][x-1][--json]")  # the answer is filed on the bead's notes (here bd shows nothing: skipped)
            self.assertEqual(log[-1], "[update][x-1][--status][open][--json]")


class AskFailures(unittest.TestCase):
    """Every way an answer can fail says what is true and what to do, never a raw bd line (the demo-1 502, the
    withdrawn ask that said 'already answered', the superseded ask that said 'no such ask')."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / "bin").mkdir()
        self.asks = self.d / "task-loop" / "asks"
        self.asks.mkdir(parents=True)
        env = {"XDG_CONFIG_HOME": str(self.d), "APPDATA": str(self.d), "HOME": str(self.d), "USERPROFILE": str(self.d),
               "PATH": str(self.d / "bin") + os.pathsep + os.environ["PATH"]}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.dash = make_dash()

    def bd(self, script):
        (self.d / "bin" / "bd").write_text("#!/bin/sh\nshift 2\n" + script)
        (self.d / "bin" / "bd").chmod(0o755)

    def ask(self, bead="x-1", n=1, **kw):
        a = {"v": 1, "id": "%s-%d" % (bead, n), "bead": bead, "kind": "verify", "question": "ok?", "t": time.time(),
             "parks_at": time.time() + 9e4, "status": "open", "repo": str(self.d), "options": []}
        a.update(kw)
        (self.asks / ("%s.json" % bead)).write_text(json.dumps(a))

    @SH_FAKE
    def test_a_bead_bd_does_not_know_says_the_ask_is_out_of_date(self):
        self.bd("echo 'Error: resolving demo: no issue found matching \"demo\"' >&2; exit 1\n")
        self.ask("demo")
        code, out = self.dash.asks.answer({"ask": "demo-1", "text": "b"})
        self.assertEqual((code, out["code"]), (404, "bead_missing"))
        self.assertNotIn("resolving", out["error"])
        self.assertIn("dismiss", out["error"])

    @SH_FAKE
    def test_any_other_bd_failure_keeps_its_last_line_and_says_nothing_was_sent(self):
        self.bd("echo 'boom: disk full' >&2; exit 1\n")
        self.ask()
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (502, "bd"))
        self.assertIn("boom: disk full", out["error"])
        self.assertEqual(json.loads((self.asks / "x-1.json").read_text()).get("answer"), None)

    def test_no_bd_on_the_path_is_an_error_message_not_a_dropped_connection(self):
        self.ask()
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory")):
            code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (502, "no_bd"))

    def test_a_withdrawn_ask_says_who_and_why_and_is_not_listed(self):
        self.ask(status="withdrawn", withdrawn_why="fixed in 0.23.5")
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (410, "withdrawn"))
        self.assertIn("fixed in 0.23.5", out["error"])
        self.assertEqual(self.dash.asks.inbox(), [])

    def test_an_ask_the_engine_replaced_points_at_the_new_one(self):
        self.ask(n=2)
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"], out["new_ask"]), (409, "superseded", "x-1-2"))
        self.assertEqual(self.dash.asks.answer({"ask": "nope-1", "text": "b"})[1]["code"], "gone")

    def test_withdraw_marks_the_ask_and_leaves_the_bead_alone(self):
        self.bd("echo called >> %s\n" % (self.d / "bd.log"))
        self.ask()
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": "stale"})[0], 200)
        a = json.loads((self.asks / "x-1.json").read_text())
        self.assertEqual((a["status"], a["withdrawn_why"]), ("withdrawn", "stale"))
        self.assertFalse((self.d / "bd.log").exists())
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1"})[0], 200)  # twice is fine

    def test_the_inbox_is_ordered_by_what_each_ask_unblocks_and_drops_closed_beads(self):
        (self.d / ".beads").mkdir()
        beads = [{"id": "a", "status": "open"}, {"id": "b", "status": "open"}, {"id": "c", "status": "closed"},
                 {"id": "d", "status": "open", "dependencies": [{"type": "blocks", "id": "b"}]},
                 {"id": "e", "status": "open", "dependencies": [{"type": "blocks", "id": "b"}]}]
        for bead in ("a", "b", "c"):
            self.ask(bead)
        with mock.patch.object(self.dash.beads, "beads_of", return_value=beads):
            rows = self.dash.asks.inbox()
        self.assertEqual([(r["bead"], r["unblocks"]) for r in rows], [("b", 2), ("a", 0)])

    def test_odd_requests_get_an_error_not_a_crash(self):
        self.ask()
        for body in ([], "x", {"ask": ["x-1-1"], "text": "b"}, {"ask": "../../etc-1", "text": "b"}, {"ask": "x-1-1", "text": 5}):
            self.assertIn(self.dash.asks.answer(body)[0], (400, 404, 409))
        self.assertEqual(self.dash.asks.withdraw([])[0], 400)
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": 7})[0], 200)
        self.assertEqual(json.loads((self.asks / "x-1.json").read_text())["withdrawn_why"], "dismissed by the owner")

    def test_a_new_bead_missing_from_a_stale_listing_is_not_hidden_but_an_old_gone_one_is(self):
        (self.d / ".beads").mkdir()
        self.ask("fresh")
        self.ask("old", t=time.time() - 3600)
        with mock.patch.object(self.dash.beads, "beads_of", return_value=[{"id": "zzz", "status": "open"}]):
            self.assertEqual([r["bead"] for r in self.dash.asks.inbox()], ["fresh"])

    def test_a_second_process_reuses_the_bead_list_of_the_last_30_seconds(self):
        """tl-u08: tl ask list is a fresh process every time; bd list takes seconds under load, so it is read once per 30 s."""
        (self.d / ".beads").mkdir()
        out = mock.Mock(returncode=0, stdout=json.dumps([{"id": "a", "status": "open"}]), stderr="")
        with mock.patch.object(subprocess, "run", return_value=out) as run, mock.patch.object(shutil, "which", return_value="/bin/bd"):
            self.dash.env.ttl.clear()
            self.assertEqual(self.dash.beads.beads_of(str(self.d)), [{"id": "a", "status": "open"}])
            self.dash.env.ttl.clear()  # a new process: nothing in memory
            self.assertEqual(self.dash.beads.beads_of(str(self.d)), [{"id": "a", "status": "open"}])
        self.assertEqual(run.call_count, 1)

    @SH_FAKE
    def test_amend_replaces_an_unused_answer_and_keeps_the_history(self):
        """tl-ptv: a second answer is refused; --amend replaces one no run has used yet, and nothing is lost."""
        self.bd("echo \"$*\" >> %s\n" % (self.d / "bd.log"))
        self.ask()
        self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "first"})[0], 200)
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "second"})
        self.assertEqual((code, out["code"]), (409, "answered"))
        self.assertIn("--amend", out["error"])
        self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "second", "amend": True})[0], 200)
        a = json.loads((self.asks / "x-1.json").read_text())
        self.assertEqual(a["answer"], "second")
        self.assertEqual([x["text"] for x in a["answers"]], ["first", "second"])
        self.assertIn("comments add x-1 Answer amended (replaces the one above, not used yet): second", (self.d / "bd.log").read_text())
        a["status"] = "answered"  # a run used it
        (self.asks / "x-1.json").write_text(json.dumps(a))
        code, out = self.dash.asks.answer({"ask": "x-1-1", "text": "third", "amend": True})
        self.assertEqual((code, out["code"]), (409, "consumed"))
        # a run that picked the answer up while bd was working is not undone: status stays answered, the amend is told it is late
        self.ask("z")
        real = subprocess.run

        def engine_consumes(cmd, *a, **k):
            if "comments" in cmd and "add" in cmd:
                f = self.asks / "z.json"
                d = json.loads(f.read_text())
                d["status"] = "answered"
                f.write_text(json.dumps(d))
            return real(cmd, *a, **k)
        self.assertEqual(self.dash.asks.answer({"ask": "z-1", "text": "one"})[0], 200)
        d = json.loads((self.asks / "z.json").read_text())
        d["status"] = "open"
        (self.asks / "z.json").write_text(json.dumps(d))
        with mock.patch.object(subprocess, "run", side_effect=engine_consumes):
            code, out = self.dash.asks.answer({"ask": "z-1", "text": "two", "amend": True})
        self.assertEqual((code, out["code"]), (409, "consumed"))
        self.assertEqual(json.loads((self.asks / "z.json").read_text())["status"], "answered")
        self.ask("y")  # no answer yet: amend is just the first answer
        self.assertEqual(self.dash.asks.answer({"ask": "y-1", "text": "one", "amend": True})[0], 200)
        self.assertNotIn("answers", json.loads((self.asks / "y.json").read_text()))

    @SH_FAKE
    def test_amending_replaces_the_line_filed_for_the_old_answer(self):
        self.bd("""case "$1" in
show) python3 -c "import json,sys;print(json.dumps([{'id':'x','notes':open(sys.argv[1]).read()}]))" NOTES ;;
update) [ "$3" = "--notes" ] && printf '%s' "$4" > NOTES ;;
esac
""".replace("NOTES", str(self.d / "notes.txt")))
        (self.d / "notes.txt").write_text("")
        self.ask("x", kind="decision", question="**Which db?**")
        self.assertEqual(self.dash.asks.answer({"ask": "x-1", "text": "use sqlite"})[0], 200)
        self.assertEqual(self.dash.asks.answer({"ask": "x-1", "text": "use postgres", "amend": True})[0], 200)
        text = (self.d / "notes.txt").read_text()
        self.assertIn("use postgres", text)
        self.assertNotIn("use sqlite", text)
        self.assertEqual(self.dash.asks.answer({"ask": "x-1", "text": "run again", "amend": True})[0], 200)  # a bare answer removes the line
        self.assertNotIn("(ask x-1)", (self.d / "notes.txt").read_text())

    @SH_FAKE
    def test_withdrawing_an_answered_but_unused_ask_drops_the_answer_and_notes_it(self):
        """tl-gy4: withdraw refused 'already answered'; only --fresh worked, which dropped the answer unseen."""
        self.bd("echo \"$*\" >> %s\n" % (self.d / "bd.log"))
        self.ask()
        self.assertEqual(self.dash.asks.answer({"ask": "x-1-1", "text": "go with B"})[0], 200)
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1", "why": "wrong ask"})[0], 200)
        a = json.loads((self.asks / "x-1.json").read_text())
        self.assertEqual((a["status"], a.get("answer"), a["withdrawn_answer"]), ("withdrawn", None, "go with B"))
        self.assertIn("answer dropped: go with B", a["withdrawn_why"])
        self.assertIn("comments add x-1 Answer to ask x-1-1 withdrawn, no run used it: go with B", (self.d / "bd.log").read_text())
        a["status"], a["answer"] = "answered", "used"  # a run consumed it: too late to withdraw
        (self.asks / "x-1.json").write_text(json.dumps(a))
        self.assertEqual(self.dash.asks.withdraw({"ask": "x-1-1"})[1]["code"], "answered")

    @SH_FAKE
    def test_an_answer_for_an_ask_the_engine_replaced_meanwhile_writes_nothing(self):
        self.ask("x", n=1)
        real = subprocess.run

        def engine_asks_again(cmd, *a, **k):
            if "comments" in cmd and "add" in cmd:
                self.ask("x", n=2, question="a new question")
            return real(cmd, *a, **k)
        self.bd("echo ok\n")
        with mock.patch.object(subprocess, "run", side_effect=engine_asks_again):
            code, out = self.dash.asks.answer({"ask": "x-1", "text": "for the old one"})
        self.assertEqual((code, out["code"], out["new_ask"]), (409, "superseded", "x-2"))
        a = json.loads((self.asks / "x.json").read_text())
        self.assertEqual((a["id"], a.get("answer")), ("x-2", None))  # the new ask is whole, no stale answer on it

    @SH_FAKE
    def test_a_parked_ask_is_listed_last_flagged_and_answerable(self):
        self.bd("echo \"$*\" >> %s\n" % (self.d / "bd.log"))
        self.ask("quiet", status="parked")
        self.ask("loud")
        rows = self.dash.asks.inbox()
        self.assertEqual([(r["bead"], r["parked"]) for r in rows], [("loud", False), ("quiet", True)])
        self.assertEqual(self.dash.asks.answer({"ask": "quiet-1", "text": "go on"})[0], 200)

    @SH_FAKE
    def test_a_substantive_answer_is_filed_on_the_bead_under_decisions_or_testing(self):
        notes = {"v": "existing note"}
        self.bd("""case "$1" in
show) python3 -c "import json,sys;print(json.dumps([{'id':'x','notes':open(sys.argv[1]).read()}]))" NOTES ;;
update) [ "$3" = "--notes" ] && printf '%s' "$4" > NOTES; echo "$@" >> LOG ;;
esac
""".replace("NOTES", str(self.d / "notes.txt")).replace("LOG", str(self.d / "bd.log")))
        (self.d / "notes.txt").write_text(notes["v"])
        self.ask("x", kind="decision", question="**Build the sink now?**\n\n**What I need from you:** pick")
        self.assertEqual(self.dash.asks.answer({"ask": "x-1", "text": "B: add a stand-in sink"})[0], 200)
        text = (self.d / "notes.txt").read_text()
        self.assertIn("existing note\n\n## Decisions\n- ", text)
        self.assertIn("(ask x-1) Build the sink now? -> B: add a stand-in sink", text)
        self.ask("x", kind="verify", n=2)
        self.assertEqual(self.dash.asks.answer({"ask": "x-2", "text": "right"})[0], 200)  # a bare button answer files nothing
        self.assertNotIn("## Testing", (self.d / "notes.txt").read_text())
        self.ask("x", kind="verify", n=3)
        self.assertEqual(self.dash.asks.answer({"ask": "x-3", "text": "wrong: the unit is ms"})[0], 200)
        text = (self.d / "notes.txt").read_text()
        self.assertIn("## Testing\n- ", text)
        self.assertIn("## Decisions\n- ", text)  # the first section is kept, the second beside it
        (self.d / "notes.txt").write_text("### Testing plan\nsee ## Testing below in prose\n")
        self.ask("x", kind="verify", n=4)
        self.assertEqual(self.dash.asks.answer({"ask": "x-4", "text": "wrong: another"})[0], 200)
        text = (self.d / "notes.txt").read_text()
        self.assertTrue(text.startswith("### Testing plan\nsee ## Testing below in prose\n\n## Testing\n- "), text)  # a new section, not inside the prose


class Markdown(unittest.TestCase):
    """The page's md(): bullets, tables, bold and code render; HTML in ask text never does."""

    def run_md(self, text):
        import re
        tools.need(self, "node")
        node = tools.real("node")
        page = (ROOT / "src" / "taskloop_dash" / "static" / "index.html").read_text(encoding="utf-8")
        src = re.search(r"/\*md\*/(.*?)/\*end md\*/", page, re.S).group(1)
        esc = "const esc=s=>String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        r = subprocess.run([node, "-e", esc + src + "\nprocess.stdout.write(md(JSON.parse(process.argv[1])))", json.dumps(text)],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_structure_renders(self):
        out = self.run_md("**Head**\n\n**What happened**\n- one `x`\n- two\n\n| a | b |\n|---|---|\n| 1 | **2** |\n\n**Need:** it")
        self.assertIn("<b>Head</b>", out)
        self.assertIn("<ul><li>one <code>x</code></li><li>two</li></ul>", out)
        self.assertIn("<th>a</th>", out)
        self.assertIn("<td><b>2</b></td>", out)

    def test_html_in_ask_text_is_escaped(self):
        out = self.run_md("- <img src=x onerror=alert(1)>\n| <script>x</script> |\n[a](javascript:alert(1))")
        self.assertNotIn("<img", out)
        self.assertNotIn("<script", out)
        self.assertNotIn("<a ", out)


class LaneBanner(unittest.TestCase):
    """What the banner says of delegate's `route.py status --json` lanes (tl-bxk.10.22)."""

    def banners(self, lanes):
        return lanes_mod.lane_banners({"v": 1, "lanes": lanes})

    def lane(self, **kw):
        return dict({"family": "claude", "kind": "subscription", "out": False, "out_until": None, "notes": []}, **kw)

    def test_a_logged_out_claude_lane_says_to_log_in(self):
        b = self.banners({"CLAUDE_SUBSCRIPTION": self.lane(out=True, notes=["claude is logged out: run `claude auth login`"])})
        self.assertEqual(b["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")

    def test_a_logged_out_codex_lane_says_to_log_in(self):
        b = self.banners({"OPENAI_SUBSCRIPTION": self.lane(family="openai", out=True, out_until=time.time() + 60,
                                                           notes=["codex is not logged in: run codex login"])})
        self.assertEqual(b["OPENAI_SUBSCRIPTION"]["text"], "Codex logged out: run codex login")

    def test_a_limit_says_the_local_time_it_ends(self):
        until = time.time() + 2 * 86400  # a future date distinct from today, whenever the test runs
        b = self.banners({"OPENAI_SUBSCRIPTION": self.lane(family="openai", out=True, out_until=until,
                                                           notes=["limit refusal: try again later"])})
        self.assertEqual(b["OPENAI_SUBSCRIPTION"]["text"], "Codex out until " + time.strftime("%a %H:%M", time.localtime(until)))

    def test_a_limit_ending_today_says_only_the_time(self):
        until = time.time() + 60
        if time.strftime("%Y%m%d", time.localtime(until)) != time.strftime("%Y%m%d"):
            self.skipTest("a minute before midnight")
        b = self.banners({"OPENAI_SUBSCRIPTION": self.lane(family="openai", out=True, out_until=until)})
        self.assertEqual(b["OPENAI_SUBSCRIPTION"]["text"], "Codex out until " + time.strftime("%H:%M", time.localtime(until)))

    def test_an_end_that_has_passed_is_called_out(self):
        until = time.time() - 3600
        b = self.banners({"OPENAI_SUBSCRIPTION": self.lane(family="openai", out=True, out_until=until)})
        self.assertIn("has passed", b["OPENAI_SUBSCRIPTION"]["text"])

    def test_an_out_lane_with_no_time_says_only_out(self):
        b = self.banners({"CLAUDE_SUBSCRIPTION": self.lane(out=True)})
        self.assertEqual(b["CLAUDE_SUBSCRIPTION"]["text"], "Claude out")

    def test_a_usable_lane_and_an_out_credit_lane_get_no_banner(self):
        b = self.banners({"CLAUDE_SUBSCRIPTION": self.lane(), "CLAUDE_CREDIT": self.lane(kind="credit", out=True)})
        self.assertEqual(b, {})

    def test_a_logged_out_reason_needs_no_note(self):
        b = self.banners({"CLAUDE_SUBSCRIPTION": self.lane(out=True, reason="logged_out")})
        self.assertEqual(b["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")

    def test_a_busy_lane_gets_no_banner(self):
        self.assertEqual(self.banners({"CLAUDE_SUBSCRIPTION": self.lane(out=True, reason="busy")}), {})

    def test_delegate_status_carries_the_text(self):
        j = {"v": 1, "lanes": {"CLAUDE_SUBSCRIPTION": self.lane(out=True, notes=["claude is logged out: run `claude auth login`"])}}
        j = {"v": 1, "lanes": {"CLAUDE_SUBSCRIPTION": self.lane(out=True, notes=["claude is logged out: run `claude auth login`"])},
             "cockpit": {"v": 1, "lanes": [{"id": "CLAUDE_SUBSCRIPTION", "state": "logged_out"}]}}
        with mock.patch.object(glob, "glob", return_value=["/x/iorlas-delegate/0.35.0/skills/delegate/route.py"]), \
                mock.patch.object(subprocess, "run", return_value=mock.Mock(stdout=json.dumps(j))):
            d = self.dash.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertEqual(d["detail"]["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")


if __name__ == "__main__":
    unittest.main()
