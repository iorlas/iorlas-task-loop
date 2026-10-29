"""The dashboard server: pages, API and live state."""
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401
from asks.samples import MOCKS  # noqa: E402
from support.dashes import make_dash  # noqa: E402

from taskloop.contracts import wire  # noqa: E402
from taskloop_dash import bind as bind_mod  # noqa: E402

SH_FAKE = unittest.skipIf(os.name == "nt", "the bd fake is a #!/bin/sh script, which Windows cannot execute")


def line(**kw):
    return json.dumps(kw) + "\n"


class Tails(unittest.TestCase):
    def setUp(self):
        self.dash = make_dash()
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "s.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_tail_reads_only_the_end(self):
        self.p.write_text("x" * 100 + "\n" + "keep\n")
        self.assertEqual(self.dash.env.tails.tail_lines(str(self.p), limit=7), ["keep"])


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
                base = f"http://127.0.0.1:{port}"
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
    """The owner answers an ask from the phone through the real server: no token from loopback, the answer is a typed record on the
    ask and the bead is opened."""

    @SH_FAKE
    def test_answer_needs_the_token_and_reaches_the_ask_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = free_port()
            d = Path(tmp)
            bin_ = d / "bin"
            bin_.mkdir()
            (bin_ / "bd").write_text("#!/bin/sh\necho \"$*\" >> {}\n".format(d / "bd.log"))
            (bin_ / "bd").chmod(0o755)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            rec = wire.dump(MOCKS["lifesim-22b3"].model_copy(update={"bead": "x-1", "id": "x-1-1", "repo": str(d), "t": time.time() - 3600,
                                                    "parks_at": time.time() + 86400}))
            (asks / "x-1.json").write_text(json.dumps(rec))
            env = dict(os.environ, XDG_CONFIG_HOME=str(d), APPDATA=str(d), TASK_LOOP_DASH_BIND="127.0.0.1", HOME=str(d),
                       USERPROFILE=str(d), PATH=str(bin_) + os.pathsep + os.environ["PATH"],
                       PYTHONPATH=os.environ["PYTHONPATH"])
            p = subprocess.Popen([sys.executable, "-m", "taskloop_dash", "--ports",
                                  "taskloop.app.launch.dash_ports:ports",  # the launcher's bd, the fake one
                                  "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                base = f"http://127.0.0.1:{port}"
                for _ in range(50):
                    try:
                        urllib.request.urlopen(base + "/api/version", timeout=1)
                        break
                    except OSError:
                        time.sleep(0.1)

                def post(tok, text):
                    req = urllib.request.Request(base + "/api/answer", method="POST",
                                                 data=json.dumps({"project": "x", "ask": "x-1-1", "kind": "answer", "text": text}).encode(),
                                                 headers={"Content-Type": "application/json",
                                                          **({"Authorization": "Bearer " + tok} if tok else {})})
                    try:
                        with urllib.request.urlopen(req) as r:
                            return r.status, json.loads(r.read())
                    except urllib.error.HTTPError as e:
                        return e.code, None
                self.assertEqual(post("", "new"), (200, {"ok": True, "message": ""}))  # loopback: no token
                got = json.loads((asks / "x-1.json").read_text())
                self.assertEqual((got["status"], got["answer"]["text"], got["answer"]["by"]), ("answered", "new", "dash"))
                self.assertIn("update x-1 --status open", (d / "bd.log").read_text())
            finally:
                p.terminate()
                p.wait(5)
