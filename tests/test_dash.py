import dataclasses
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
from asks.samples import MOCKS  # noqa: E402
from support import tools  # noqa: E402
from taskloop.contracts import codec  # noqa: E402
from support.dashes import make_dash  # noqa: E402
from taskloop_dash import bind as bind_mod, tails as tails_mod  # noqa: E402
from taskloop_dash.api import lanes as lanes_mod  # noqa: E402
from support.narrow import must  # noqa: E402


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
    the answer is a typed record on the ask and the bead is opened."""

    @SH_FAKE
    def test_answer_needs_the_token_and_reaches_the_ask_once(self):
        with tempfile.TemporaryDirectory() as d:
            port = free_port()
            d = Path(d)
            bin_ = d / "bin"
            bin_.mkdir()
            (bin_ / "bd").write_text("#!/bin/sh\necho \"$*\" >> %s\n" % (d / "bd.log"))
            (bin_ / "bd").chmod(0o755)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            rec = codec.to_json(dataclasses.replace(MOCKS["lifesim-22b3"], bead="x-1", id="x-1-1", repo=str(d), t=time.time() - 3600,
                                                    parks_at=time.time() + 86400))
            (asks / "x-1.json").write_text(json.dumps(rec))
            env = dict(os.environ, XDG_CONFIG_HOME=str(d), APPDATA=str(d), TASK_LOOP_DASH_BIND="127.0.0.1", HOME=str(d),
                       USERPROFILE=str(d), PATH=str(bin_) + os.pathsep + os.environ["PATH"],
                       PYTHONPATH=os.pathsep.join([os.environ["PYTHONPATH"], str(ROOT / "skills" / "task-loop")]))
            p = subprocess.Popen([sys.executable, "-m", "taskloop_dash", "--ports", "dash_wiring:ports",  # the launcher's bd, the fake one
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
                got = json.loads((asks / "x-1.json").read_text())
                self.assertEqual((got["status"], got["answer"]["text"], got["answer"]["by"]), ("answered", "new", "dash"))
                self.assertIn("update x-1 --status open", (d / "bd.log").read_text())
                self.assertIn(b"Asks", urllib.request.urlopen(base + "/").read())
                self.assertNotIn(b"prompt(", urllib.request.urlopen(base + "/").read())
            finally:
                p.terminate()
                p.wait(5)


class Markdown(unittest.TestCase):
    """The page's md(): bullets, tables, bold and code render; HTML in ask text never does."""

    def run_md(self, text):
        import re
        tools.need(self, "node")
        node = tools.real("node")
        page = (ROOT / "src" / "taskloop_dash" / "static" / "index.html").read_text(encoding="utf-8")
        src = must(re.search(r"/\*md\*/(.*?)/\*end md\*/", page, re.S)).group(1)
        esc = "const esc=s=>String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        r = subprocess.run([must(node), "-e", esc + src + "\nprocess.stdout.write(md(JSON.parse(process.argv[1])))", json.dumps(text)],
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
        j = {"v": 1, "lanes": {"CLAUDE_SUBSCRIPTION": self.lane(out=True, notes=["claude is logged out: run `claude auth login`"])},
             "cockpit": {"v": 1, "lanes": [{"id": "CLAUDE_SUBSCRIPTION", "state": "logged_out"}]}}
        self.dash = make_dash()
        with mock.patch.object(glob, "glob", return_value=["/x/iorlas-delegate/0.35.0/skills/delegate/route.py"]), \
                mock.patch.object(subprocess, "run", return_value=mock.Mock(stdout=json.dumps(j))):
            d = self.dash.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertEqual(d["detail"]["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")


if __name__ == "__main__":
    unittest.main()
