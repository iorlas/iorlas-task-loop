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
    """The owner answers an ask from the phone through the real server with no credentials (the dash has no auth): the answer is a
    typed record on the ask and the bead is opened; the page and the read API answer a plain GET."""

    def test_no_credentials_needed_to_read_or_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            asks = d / "task-loop" / "asks"
            asks.mkdir(parents=True)
            rec = wire.dump(MOCKS["lifesim-22b3"].replace(bead="x-1", id="x-1-1", repo=str(d), t=time.time() - 3600,
                                                    parks_at=time.time() + 86400))
            (asks / "x-1.json").write_text(json.dumps(rec))
            env = {"XDG_CONFIG_HOME": str(d), "APPDATA": str(d), "TASK_LOOP_DASH_BIND": "127.0.0.1", "HOME": str(d), "USERPROFILE": str(d)}
            with mock.patch.dict(os.environ, env), tlbd.bd_boundary() as bd_calls, serving(dash_ports.ports(snapshot())) as base:
                for path in ("/", "/api/snapshot", "/api/cost", "/api/version"):
                    with urllib.request.urlopen(base + path) as r:
                        self.assertEqual(r.status, 200, path)

                def post(text):
                    req = urllib.request.Request(base + "/api/answer", method="POST",
                                                 data=json.dumps({"project": "x", "ask": "x-1-1", "kind": "answer", "text": text}).encode(),
                                                 headers={"Content-Type": "application/json"})
                    try:
                        with urllib.request.urlopen(req) as r:
                            return r.status, json.loads(r.read())
                    except urllib.error.HTTPError as e:
                        return e.code, None
                self.assertEqual(post("new"), (200, {"ok": True, "message": ""}))
                got = json.loads((asks / "x-1.json").read_text())
                self.assertEqual((got["status"], got["answer"]["text"], got["answer"]["by"]), ("answered", "new", "dash"))
                self.assertIn(("update", "x-1", "--status", "open"), bd_calls.calls)
