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


class Asks(unittest.TestCase):
    """The owner answers an ask from the phone: only with the token, first answer wins, the bead is commented and opened."""

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
                self.assertEqual(post("", "new"), 401)
                self.assertEqual(post("wrong", "new"), 401)
                self.assertEqual(post(token, "New format."), 200)
                self.assertEqual(post(token, "Old, actually."), 409)
                log = (d / "bd.log").read_text()
                self.assertIn("comments add x-1 New format.", log)
                self.assertIn("update x-1 --status open", log)
                self.assertNotIn("Old, actually", log)
                self.assertIn(b"Asks", urllib.request.urlopen(base + "/").read())
            finally:
                p.terminate()
                p.wait(5)


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
        self.assertEqual(b["OPENAI_SUBSCRIPTION"]["text"], "Codex out until " + time.strftime("%H:%M", time.localtime(until)))

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
