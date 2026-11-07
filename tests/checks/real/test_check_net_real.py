"""NETISO slice 1: the real prefix on a real Linux host: a check cannot reach a server outside, and its own loopback works."""
import socket
import subprocess
import sys

import pytest
from support.procsim import real_proc

from taskloop.adapters import check_net

CONNECT = "import socket,sys; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', int(sys.argv[1])))"
LOOPBACK = (
    "import socket; srv=socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1); c=socket.socket(); c.settimeout(3); "
    "c.connect(srv.getsockname()); print('loopback ok')"
)


def prefix():
    plan = check_net.current()
    if not plan.prefix:
        pytest.skip(plan.warning)
    return list(plan.prefix)


@pytest.fixture
def server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    yield srv.getsockname()[1]
    srv.close()


@real_proc("a real check under the real network-removing tool")
def test_a_check_under_the_prefix_cannot_reach_a_server_the_engine_can(server):
    connect = [sys.executable, "-c", CONNECT, str(server)]
    assert subprocess.run(connect, capture_output=True, timeout=20, check=False).returncode == 0  # the control: outside, it connects
    assert subprocess.run([*prefix(), *connect], capture_output=True, timeout=20, check=False).returncode != 0


@real_proc("a real check under the real network-removing tool")
def test_the_checks_own_loopback_still_works():
    got = subprocess.run([*prefix(), sys.executable, "-c", LOOPBACK], capture_output=True, text=True, timeout=20, check=False)
    assert (got.returncode, got.stdout.strip()) == (0, "loopback ok")
