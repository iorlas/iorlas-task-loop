"""tl-bxk.12.4: dash ensure replaces stale servers, binds fail loudly, dev checkouts stay on loopback."""
import contextlib
import io
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

# isort: split

from taskloop_dash import bind, serve  # noqa: E402
from taskloop_dash.cli import dash as dash_cli  # noqa: E402
from taskloop_dash.env import Env, Ports  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def live(script, version="v1", binds=("127.0.0.1",), pid=4242):
    return {"version": version, "pid": pid, "script": str(script), "binds": list(binds),
            "urls": [f"http://{b}:7878" for b in binds], "started": 1.0}


class LoudBind(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(socket, "getfqdn", lambda name="": name)
        p.start()
        self.addCleanup(p.stop)

    def test_open_servers_fails_on_any_address(self):
        port = free_port()
        with self.assertRaises(bind.BindError) as cm:
            bind.open_servers(["127.0.0.1", "203.0.113.9"], port, mock.Mock())
        self.assertIn(f"203.0.113.9:{port}", str(cm.exception))

    def test_open_servers_closes_earlier_sockets_on_failure(self):
        port = free_port()
        with self.assertRaises(bind.BindError):
            bind.open_servers(["127.0.0.1", "203.0.113.9"], port, mock.Mock())
        s = socket.socket()
        s.bind(("127.0.0.1", port))  # would raise if the first server were left open
        s.close()

    def test_the_server_exits_nonzero_and_serves_nothing(self):
        port = free_port()
        cfg = tempfile.mkdtemp()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"TASK_LOOP_DASH_DEV_PUBLIC": "1", "XDG_CONFIG_HOME": cfg, "APPDATA": cfg}), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            dash_cli.main(["--port", str(port), "--bind", "127.0.0.1,203.0.113.9"])
        self.assertNotEqual(stop.exception.code, 0)
        self.assertIn(f"203.0.113.9:{port}", err.getvalue())
        s = socket.socket()
        self.assertNotEqual(s.connect_ex(("127.0.0.1", port)), 0)
        s.close()


class DevCheckout(unittest.TestCase):


    def test_dev_server_listens_on_random_loopback_port(self):
        cfg = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": cfg, "APPDATA": cfg, "TASK_LOOP_DASH_BIND": ""}):
            servers, addrs, port, _dash = serve.start(Env(ports=Ports()), dash_cli.PACKAGE, [])
        try:
            first = ", ".join(bind.urls(addrs, port))  # what the server prints on its first line
            self.assertIn("127.0.0.1:", first)
            self.assertNotIn(":7878", first)
            self.assertNotIn("100.", first)
        finally:
            for s in servers:
                s.server_close()
        # a dev server must not claim the shared pid file
        self.assertFalse((Path(cfg) / "task-loop" / "dash.pid").exists())


if __name__ == "__main__":
    unittest.main()
