"""Network facts (delegate-4n7, delegate-0sf, delegate-dlz): the probe, the words of a dropped connection, network never benching a pair,
roles{} in status --json --cheap, and the adapter registry."""

import contextlib
import io
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import mock

from any_agent import procs
from delegate.adapters import netprobe
from delegate.app import env, harnesses
from support.case import Case
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
from test_route import CFG, route

LANES = Path(__file__).resolve().parents[3] / "src" / "delegate" / "adapters"


@contextlib.contextmanager
def listener():
    """A local TCP server: the probe's 'vendor' that is up."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    try:
        yield f"127.0.0.1:{srv.getsockname()[1]}"
    finally:
        srv.close()


def closed_port():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()
    return f"127.0.0.1:{port}"












class Cheap(Case):
    def setup_method(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        p = mock.patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": self.d.name})
        p.start()
        self.addCleanup(p.stop)

    def cheap(self):
        boom = mock.Mock(side_effect=AssertionError("a process was spawned"))
        out = io.StringIO()
        with (
            mock.patch.object(subprocess, "run", boom),
            mock.patch.object(subprocess, "Popen", boom),
            mock.patch.object(procs, "run_capture", boom),
            mock.patch.object(socket, "create_connection", boom),
            contextlib.redirect_stdout(out),
        ):
            rc = route.main(["status", "--json", "--cheap"])
        return rc, json.loads(out.getvalue())

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_full_status_writes_roles_and_cheap_replays_them_with_a_fresh_net(self):
        out = io.StringIO()
        with mock.patch.object(harnesses, "probe_login", return_value=(True, "ok")), contextlib.redirect_stdout(out):
            route.main(["status", "--json"])
        full = json.loads(out.getvalue())
        assert set(full["roles"]) == set(CFG["roles"])
        for r in full["roles"].values():
            assert "usable" in r
            assert "net" in r
        netprobe.record(
            str(env.net_cache_path()), {"up": False, "ip_up": False, "why": "offline", "hosts": {"chatgpt.com": "tcp"}, "at": time.time()}
        )
        rc, cheap = self.cheap()
        assert rc == 0
        assert set(cheap["roles"]) == set(CFG["roles"])
        assert "chatgpt.com" in cheap["roles"]["worker"]["hosts"]
        assert cheap["roles"]["worker"]["net"]["up"] is False
        assert cheap["network"]["up"] is False
