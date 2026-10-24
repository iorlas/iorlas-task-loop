import json
import os
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
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import server  # noqa: E402


def line(**kw):
    return json.dumps(kw) + "\n"


class Transcripts(unittest.TestCase):
    def setUp(self):
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
        evs = server.claude_events(str(self.p))
        self.assertEqual([e["kind"] for e in evs], ["user", "msg", "cmd"])
        self.assertEqual(evs[2]["state"], "fail")
        self.assertEqual(evs[2]["dur"], 2)

    def test_window_filters_events(self):
        self.p.write_text(
            line(type="assistant", timestamp="2026-10-18T10:00:00Z", message={"content": [{"type": "text", "text": "a"}]})
            + line(type="assistant", timestamp="2026-10-18T11:00:00Z", message={"content": [{"type": "text", "text": "b"}]})
            + line(type="assistant", timestamp="2026-10-18T12:00:00Z", message={"content": [{"type": "text", "text": "c"}]}))
        t = server.parse_ts
        evs = server.claude_events(str(self.p), t("2026-10-18T10:30:00Z"), t("2026-10-18T11:30:00Z"))
        self.assertEqual([e["text"] for e in evs], ["b"])

    def test_codex_log_events(self):
        self.p.write_text("[2026-10-18T10:00:00Z] Running command: /bin/zsh -lc 'just test'\n"
                          "[2026-10-18T10:00:05Z] Command failed: /bin/zsh -lc 'just test' (exit 1)\n"
                          "[2026-10-18T10:00:06Z] Assistant message captured: done\n")
        evs = server.codex_log_events(str(self.p))
        self.assertEqual(evs[0]["text"], "just test")
        self.assertEqual(evs[0]["state"], "fail")
        self.assertEqual(evs[1]["text"], "done")

    def test_tail_reads_only_the_end(self):
        self.p.write_text("x" * 100 + "\n" + "keep\n")
        self.assertEqual(server.tail_lines(str(self.p), limit=7), ["keep"])


class Spans(unittest.TestCase):
    def test_reclaim_ends_previous_span_and_close_ends_current(self):
        evs = [{"t": 1, "kind": "claim", "bead": "b", "session": "s1"},
               {"t": 2, "kind": "stage", "bead": "b", "session": "s1", "text": "write"},
               {"t": 5, "kind": "claim", "bead": "b", "session": "s2"},
               {"t": 9, "kind": "close", "bead": "b", "session": "s2"}]
        with mock.patch.object(server, "events", return_value=evs):
            sp = server.task_spans()["b"]
        self.assertEqual([(s["session"], s["from"], s["to"], s["end"]) for s in sp],
                         [("s1", 1, 5, "reclaimed"), ("s2", 5, 9, "close")])
        self.assertEqual(sp[0]["stage"], "write")

    def test_one_session_may_hold_two_beads(self):
        evs = [{"t": 1, "kind": "claim", "bead": "a", "session": "s"},
               {"t": 2, "kind": "claim", "bead": "b", "session": "s"}]
        with mock.patch.object(server, "events", return_value=evs):
            sp = server.task_spans()
        self.assertIsNone(sp["a"][0]["to"])
        self.assertIsNone(sp["b"][0]["to"])

    def test_same_tree(self):
        self.assertTrue(server.same_tree("/a/b/c", "/a/b"))
        self.assertFalse(server.same_tree("/a/bc", "/a/b"))
        self.assertFalse(server.same_tree("", "/a"))


class ResolveRepo(unittest.TestCase):
    def test_a_link_may_name_the_repo_by_folder_or_not_at_all(self):
        known = ["/w/lifesim", "/w/other"]
        beads = {"/w/lifesim": [{"id": "lifesim-vbo"}], "/w/other": [{"id": "o-1"}]}
        with mock.patch.object(server, "repos", return_value=known), \
                mock.patch.object(server, "beads_of", side_effect=lambda r: beads.get(r, [])):
            self.assertEqual(server.resolve_repo("/w/other"), "/w/other")
            self.assertEqual(server.resolve_repo("lifesim"), "/w/lifesim")
            self.assertEqual(server.resolve_repo("", "o-1"), "/w/other")
            self.assertEqual(server.resolve_repo("nope", "x-1"), "")


class Contract(unittest.TestCase):
    """agent-runs v1: the only way other tools' workers reach the dashboard."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name})
        self.env.start()
        server._cache.clear()
        self.runs = Path(self.tmp.name) / "agent-runs" / "runs"
        self.runs.mkdir(parents=True)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, name, rec):
        (self.runs / name).write_text(rec if isinstance(rec, str) else json.dumps(rec))

    def test_reads_v1_and_skips_the_rest(self):
        now = time.time()
        log = Path(self.tmp.name) / "w.jsonl"
        log.write_text("")
        self.write("a.json", {"v": 1, "producer": "x", "id": "a", "kind": "claude-p", "parent_session": "p",
                              "cwd": "/w", "started": now, "status": "running", "transcript": str(log), "extra": 1})
        self.write("b.json", {"v": 2, "id": "b", "kind": "claude-p", "started": now, "status": "running"})
        self.write("c.json", "{broken")
        self.write("d.json", {"v": 1, "kind": "other"})
        runs = server.contract_runs(now - 60)
        self.assertEqual([(r["kind"], r["parent"]) for r in runs], [("claude-p", "p")])
        self.assertTrue(runs[0]["id"].startswith("claude-p:"))

    def test_missing_folder_is_fine(self):
        self.runs.rmdir()
        self.assertEqual(server.contract_runs(0), [])
        self.assertEqual(server.contract_lanes(), [])

    def test_lanes_only_when_fresh(self):
        lanes = Path(self.tmp.name) / "agent-runs" / "lanes"
        lanes.mkdir()
        (lanes / "fresh.json").write_text(json.dumps({"v": 1, "producer": "x", "at": time.time(),
                                                      "lanes": [{"name": "A", "usage": [{"window": "5h", "used_pct": 3}]}]}))
        (lanes / "stale.json").write_text(json.dumps({"v": 1, "producer": "y", "at": 0, "lanes": [{"name": "B"}]}))
        self.assertEqual([l["name"] for l in server.contract_lanes()], ["A"])


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
            p = subprocess.Popen([sys.executable, str(ROOT / "skills" / "task-loop" / "dash" / "server.py"),
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
                s = json.loads(urllib.request.urlopen(base + "/api/summary").read())
                self.assertEqual(s["repos"], [])
                self.assertEqual(json.loads(urllib.request.urlopen(base + "/api/runs").read()), [])
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
        self.tok = server.token()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_loopback_and_tailscale_need_no_token(self):
        for addr in ("127.0.0.1", "127.5.5.5", "::1", "::ffff:127.0.0.1", "100.64.0.1", "100.101.102.103", "100.127.255.254"):
            self.assertTrue(server.post_allowed(addr, None), addr)
            self.assertTrue(server.post_allowed(addr, "Bearer wrong"), addr)

    def test_any_other_source_needs_the_token(self):
        for addr in ("192.168.1.20", "10.0.0.5", "172.17.0.2", "100.63.255.255", "100.128.0.1", "8.8.8.8", "fe80::1", "junk", ""):
            self.assertFalse(server.post_allowed(addr, None), addr)
            self.assertFalse(server.post_allowed(addr, "Bearer wrong"), addr)
            self.assertFalse(server.post_allowed(addr, "Bearer "), addr)
            self.assertTrue(server.post_allowed(addr, "Bearer " + self.tok), addr)

    def test_the_address_comes_from_the_socket_not_a_header(self):
        src = (ROOT / "skills" / "task-loop" / "dash" / "server.py").read_text()
        self.assertIn("post_allowed(self.client_address[0]", src)
        self.assertNotIn("X-Forwarded-For", src)


class Asks(unittest.TestCase):
    """The owner answers an ask from the phone: a token only from outside loopback and Tailscale, first answer wins,
    the bead is commented and opened."""

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
                       USERPROFILE=str(d), PATH=str(bin_) + os.pathsep + os.environ["PATH"])
            p = subprocess.Popen([sys.executable, str(ROOT / "skills" / "task-loop" / "dash" / "server.py"),
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

    def test_an_option_answer_reaches_bd_with_the_exact_text_and_shows_as_answered(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            (d / "bin" / "bd").write_text("#!/bin/sh\nfor a in \"$@\"; do printf '[%s]' \"$a\"; done >> " + str(d / "bd.log") + "\necho >> " + str(d / "bd.log") + "\n")
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
                shown = server.asks()["asks"][0]
                strip = lambda os: [{k: o[k] for k in ("label", "answer", "note", "recommended") if k in o} for o in os]
                self.assertEqual(strip(shown["options"]), opts)  # the page renders these (plus what happens next)
                self.assertEqual(strip(server.open_ask("x-1")["options"]), opts)
                self.assertTrue(all(o["then"] for o in shown["options"]))
                clicked = shown["options"][1]["answer"]
                code, out = server.answer({"ask": "x-1-1", "text": clicked})
                self.assertEqual((code, out["ok"]), (200, True))
                self.assertIn("x-1", out["next"])
                self.assertEqual(server.answer({"ask": "x-1-1", "text": "A: build now"})[0], 409)
                self.assertEqual(server.asks()["asks"][0]["answer"], text)
            log = (d / "bd.log").read_text().splitlines()
            self.assertEqual(log[0], "[comments][add][x-1][%s]" % text)
            self.assertEqual(log[1], "[show][x-1][--json]")  # the answer is filed on the bead's notes (here bd shows nothing: skipped)
            self.assertEqual(log[-1], "[update][x-1][--status][open]")


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

    def bd(self, script):
        (self.d / "bin" / "bd").write_text("#!/bin/sh\n" + script)
        (self.d / "bin" / "bd").chmod(0o755)

    def ask(self, bead="x-1", n=1, **kw):
        a = {"v": 1, "id": "%s-%d" % (bead, n), "bead": bead, "kind": "verify", "question": "ok?", "t": time.time(),
             "parks_at": time.time() + 9e4, "status": "open", "repo": str(self.d), "options": []}
        a.update(kw)
        (self.asks / ("%s.json" % bead)).write_text(json.dumps(a))

    def test_a_bead_bd_does_not_know_says_the_ask_is_out_of_date(self):
        self.bd("echo 'Error: resolving demo: no issue found matching \"demo\"' >&2; exit 1\n")
        self.ask("demo")
        code, out = server.answer({"ask": "demo-1", "text": "b"})
        self.assertEqual((code, out["code"]), (404, "bead_missing"))
        self.assertNotIn("resolving", out["error"])
        self.assertIn("dismiss", out["error"])

    def test_any_other_bd_failure_keeps_its_last_line_and_says_nothing_was_sent(self):
        self.bd("echo 'boom: disk full' >&2; exit 1\n")
        self.ask()
        code, out = server.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (502, "bd"))
        self.assertIn("boom: disk full", out["error"])
        self.assertEqual(json.loads((self.asks / "x-1.json").read_text()).get("answer"), None)

    def test_no_bd_on_the_path_is_an_error_message_not_a_dropped_connection(self):
        self.ask()
        with mock.patch.object(server.subprocess, "run", side_effect=FileNotFoundError(2, "No such file or directory")):
            code, out = server.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (502, "no_bd"))

    def test_a_withdrawn_ask_says_who_and_why_and_is_not_listed(self):
        self.ask(status="withdrawn", withdrawn_why="fixed in 0.23.5")
        code, out = server.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"]), (410, "withdrawn"))
        self.assertIn("fixed in 0.23.5", out["error"])
        self.assertEqual(server.inbox(), [])

    def test_an_ask_the_engine_replaced_points_at_the_new_one(self):
        self.ask(n=2)
        code, out = server.answer({"ask": "x-1-1", "text": "b"})
        self.assertEqual((code, out["code"], out["new_ask"]), (409, "superseded", "x-1-2"))
        self.assertEqual(server.answer({"ask": "nope-1", "text": "b"})[1]["code"], "gone")

    def test_withdraw_marks_the_ask_and_leaves_the_bead_alone(self):
        self.bd("echo called >> %s\n" % (self.d / "bd.log"))
        self.ask()
        self.assertEqual(server.withdraw({"ask": "x-1-1", "why": "stale"})[0], 200)
        a = json.loads((self.asks / "x-1.json").read_text())
        self.assertEqual((a["status"], a["withdrawn_why"]), ("withdrawn", "stale"))
        self.assertFalse((self.d / "bd.log").exists())
        self.assertEqual(server.withdraw({"ask": "x-1-1"})[0], 200)  # twice is fine

    def test_the_inbox_is_ordered_by_what_each_ask_unblocks_and_drops_closed_beads(self):
        (self.d / ".beads").mkdir()
        beads = [{"id": "a", "status": "open"}, {"id": "b", "status": "open"}, {"id": "c", "status": "closed"},
                 {"id": "d", "status": "open", "dependencies": [{"type": "blocks", "depends_on_id": "b"}]},
                 {"id": "e", "status": "open", "dependencies": [{"type": "blocks", "depends_on_id": "b"}]}]
        for bead in ("a", "b", "c"):
            self.ask(bead)
        with mock.patch.object(server, "beads_of", return_value=beads):
            rows = server.inbox()
        self.assertEqual([(r["bead"], r["unblocks"]) for r in rows], [("b", 2), ("a", 0)])

    def test_odd_requests_get_an_error_not_a_crash(self):
        self.ask()
        for body in ([], "x", {"ask": ["x-1-1"], "text": "b"}, {"ask": "../../etc-1", "text": "b"}, {"ask": "x-1-1", "text": 5}):
            self.assertIn(server.answer(body)[0], (400, 404, 409))
        self.assertEqual(server.withdraw([])[0], 400)
        self.assertEqual(server.withdraw({"ask": "x-1-1", "why": 7})[0], 200)
        self.assertEqual(json.loads((self.asks / "x-1.json").read_text())["withdrawn_why"], "dismissed by the owner")

    def test_a_new_bead_missing_from_a_stale_listing_is_not_hidden_but_an_old_gone_one_is(self):
        (self.d / ".beads").mkdir()
        self.ask("fresh")
        self.ask("old", t=time.time() - 3600)
        with mock.patch.object(server, "beads_of", return_value=[{"id": "zzz", "status": "open"}]):
            self.assertEqual([r["bead"] for r in server.inbox()], ["fresh"])

    def test_the_real_over_budget_ask_reads_as_a_question_with_options_and_no_zero_dollars(self):
        """lifesim-fld.27.12 as the old engine wrote it: kind stuck, 'over budget: $0.00 of $15, 183 of 180 min', no buttons."""
        a = json.loads((Path(__file__).parent / "fixtures" / "ask_over_budget_legacy.json").read_text())
        a["repo"] = str(self.d)
        (self.asks / "lifesim-fld.27.12.json").write_text(json.dumps(a))
        eng = self.d / "task-loop" / "engine"
        eng.mkdir()
        (eng / (a["run"] + ".jsonl")).write_text("\n".join(json.dumps({"kind": "end", "step": st, "secs": sec}) for st, sec in (
            ("checks", 9800), ("write", 900), ("plan", 100))))
        (shown,) = server.inbox()
        self.assertEqual(shown["kind"], "budget")
        self.assertNotIn("$", shown["question"])
        self.assertIn("**Over its time limit: 183 of 180 min**", shown["question"])
        self.assertIn("- checks took 163 min (1 round)", shown["question"])
        self.assertIn("- write took 15 min (1 round)", shown["question"])
        self.assertIn("**What I need from you:** Pick an option", shown["question"])
        self.assertEqual([o["label"] for o in shown["options"]], ["Run again", "Split the bead"])
        self.assertTrue(all(o["then"] and o["cost"] for o in shown["options"]))
        self.assertTrue(shown["quick"])

    def test_every_real_ask_reads_as_headline_bullets_and_a_need(self):
        """Copies of the open asks (tests/fixtures/asks): a headline, at most 3 bullets, one need line, no wall of text, no
        cut-off dump, no $0.00; asks that can be answered with a click carry a table's worth of options."""
        names = sorted((Path(__file__).parent / "fixtures" / "asks").glob("*.json"))
        self.assertGreaterEqual(len(names), 10)
        for f in names:
            a = json.loads(f.read_text())
            a["repo"] = str(self.d)
            (self.asks / ("%s.json" % a["bead"])).write_text(json.dumps(a))
        eng = self.d / "task-loop" / "engine"
        eng.mkdir()
        rows = server.inbox()
        self.assertEqual(len(rows), len(names))
        for r in rows:
            lines = [x for x in r["question"].split("\n") if x.strip()]
            self.assertTrue(lines[0].startswith("**") and lines[0].endswith("**"), (r["bead"], lines[0]))
            self.assertTrue(lines[-1].startswith("**What I need from you:**"), r["bead"])
            bullets = [x for x in lines if x.startswith("- ")]
            self.assertLessEqual(len(bullets), 3, r["bead"])
            for x in lines:
                self.assertLessEqual(len(x), 330, (r["bead"], x))
                self.assertNotIn("$0.00", x)
                self.assertNotIn("<<'PY'", x)
                self.assertFalse(x.rstrip().endswith((";", ",", ":", "(")), (r["bead"], x))
            self.assertEqual(r["fmt"], 3)
        by = {r["bead"]: r for r in rows}
        self.assertEqual([o["label"] for o in by["lifesim-d5f.61"]["options"]], ["Defer the sink", "Add a stand-in sink now"])
        self.assertIn("Re-planned 3 times", by["lifesim-d5f.34"]["question"])
        self.assertTrue(all(o["then"] for r in rows for o in r["options"]))


    def test_a_parked_ask_is_listed_last_flagged_and_answerable(self):
        self.bd("echo \"$*\" >> %s\n" % (self.d / "bd.log"))
        self.ask("quiet", status="parked")
        self.ask("loud")
        rows = server.inbox()
        self.assertEqual([(r["bead"], r["parked"]) for r in rows], [("loud", False), ("quiet", True)])
        self.assertEqual(server.answer({"ask": "quiet-1", "text": "go on"})[0], 200)

    def test_a_substantive_answer_is_filed_on_the_bead_under_decisions_or_testing(self):
        notes = {"v": "existing note"}
        self.bd("""case "$1" in
show) python3 -c "import json,sys;print(json.dumps([{'id':'x','notes':open(sys.argv[1]).read()}]))" NOTES ;;
update) [ "$3" = "--notes" ] && printf '%s' "$4" > NOTES; echo "$@" >> LOG ;;
esac
""".replace("NOTES", str(self.d / "notes.txt")).replace("LOG", str(self.d / "bd.log")))
        (self.d / "notes.txt").write_text(notes["v"])
        self.ask("x", kind="decision", question="**Build the sink now?**\n\n**What I need from you:** pick")
        self.assertEqual(server.answer({"ask": "x-1", "text": "B: add a stand-in sink"})[0], 200)
        text = (self.d / "notes.txt").read_text()
        self.assertIn("existing note\n\n## Decisions\n- ", text)
        self.assertIn("(ask x-1) Build the sink now? -> B: add a stand-in sink", text)
        self.ask("x", kind="verify", n=2)
        self.assertEqual(server.answer({"ask": "x-2", "text": "right"})[0], 200)  # a bare button answer files nothing
        self.assertNotIn("## Testing", (self.d / "notes.txt").read_text())
        self.ask("x", kind="verify", n=3)
        self.assertEqual(server.answer({"ask": "x-3", "text": "wrong: the unit is ms"})[0], 200)
        text = (self.d / "notes.txt").read_text()
        self.assertIn("## Testing\n- ", text)
        self.assertIn("## Decisions\n- ", text)  # the first section is kept, the second beside it


class Markdown(unittest.TestCase):
    """The page's md(): bullets, tables, bold and code render; HTML in ask text never does."""

    def run_md(self, text):
        import re
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        page = (ROOT / "skills" / "task-loop" / "dash" / "index.html").read_text()
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
        return server.lane_banners({"v": 1, "lanes": lanes})

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
        until = 1793104732
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
        server._cache.clear()
        with mock.patch.object(server.glob, "glob", return_value=["/x/iorlas-delegate/0.35.0/skills/delegate/route.py"]), \
                mock.patch.object(server.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(j))):
            d = server.delegate_status()
        server._cache.clear()
        self.assertFalse(d["ok"])
        self.assertEqual(d["detail"]["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")


if __name__ == "__main__":
    unittest.main()
