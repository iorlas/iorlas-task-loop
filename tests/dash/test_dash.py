"""The dashboard server: pages, API and live state."""
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401
from support.dashes import make_dash  # noqa: E402

from taskloop_dash import bind as bind_mod  # noqa: E402


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


