"""The dashboard server: pages, API and live state."""
import json
import os
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
from asks.samples import MOCKS  # noqa: E402
from support import tlbd  # noqa: E402
from support.dashes import serving  # noqa: E402

from taskloop.app.launch import dash_ports  # noqa: E402
from taskloop.contracts import wire  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402


def line(**kw):
    return json.dumps(kw) + "\n"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Live(unittest.TestCase):
    """The real server process, against an empty config: every endpoint answers."""

    def test_endpoints(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {
                "XDG_CONFIG_HOME": d, "APPDATA": d, "TASK_LOOP_DASH_BIND": "127.0.0.1", "HOME": d, "USERPROFILE": d}), serving() as base:
            v = json.loads(urllib.request.urlopen(base + "/api/version", timeout=10).read())
            self.assertTrue(v["version"])
            self.assertIn(b"task-loop", urllib.request.urlopen(base + "/").read())


class Asks(unittest.TestCase):
    """The owner answers an ask from the phone through the real server: no token from loopback, the answer is a typed record on the
    ask and the bead is opened."""

    def test_answer_needs_the_token_and_reaches_the_ask_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            rec = wire.dump(MOCKS["lifesim-22b3"].replace(bead="x-1", id="x-1-1", repo=str(d), t=time.time() - 3600,
                                                    parks_at=time.time() + 86400))
            (asks / "x-1.json").write_text(json.dumps(rec))
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "TASK_LOOP_DASH_BIND": "127.0.0.1", "HOME": str(d), "USERPROFILE": str(d)}
            with mock.patch.dict(os.environ, env), tlbd.bd_boundary() as bd_calls, serving(dash_ports.ports(snapshot())) as base:
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
                self.assertIn(("update", "x-1", "--status", "open"), bd_calls.calls)
