"""The dashboard server: pages, API and live state."""
import json
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

from taskloop.contracts.env import Env as ProcessEnv  # noqa: E402
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


class NoAuth(unittest.TestCase):
    """Denis 2026-10-31: "we should not have any auth strategy". The bind is the whole access rule: loopback and Tailscale only."""

    def test_loopback_and_tailscale_may_be_bound(self):
        for addr in ("127.0.0.1", "127.5.5.5", "::1", "localhost", "100.64.0.1", "100.101.102.103", "100.127.255.254"):
            self.assertTrue(bind_mod.allowed_addr(addr), addr)

    def test_any_other_address_is_refused_even_for_the_installed_copy(self):
        here = Path.home() / ".claude" / "plugins" / "cache" / "m" / "p" / "1"
        for addr in ("0.0.0.0", "::", "192.168.1.20", "10.0.0.5", "172.17.0.2", "100.63.255.255", "100.128.0.1", "myhost.local", ""):
            self.assertFalse(bind_mod.allowed_addr(addr), addr)
            public = ProcessEnv({"TASK_LOOP_DASH_DEV_PUBLIC": "1"})
            why = bind_mod.bind_refusal(["127.0.0.1", addr], 0, here, Path.home(), "/nonexistent", public)
            self.assertIn("no auth", why or "", addr)

    def test_there_is_no_token(self):
        for name in ("http.py", "bind.py", "serve.py"):
            src = (ROOT / "src" / "taskloop_dash" / name).read_text(encoding="utf-8")
            self.assertNotIn("Authorization", src, name)
            self.assertNotIn("dash.token", src, name)


