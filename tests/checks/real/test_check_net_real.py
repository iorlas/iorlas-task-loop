"""NETISO slice 1: the real prefix on a real Linux host: a check cannot reach a server outside, and its own loopback works."""
import socket
import subprocess
import sys
from unittest import mock

import pytest

from taskloop.adapters import check_net
from taskloop.app.checks.shell import Shell
from tltestkit.procsim import real_proc

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


@real_proc("a real shell check connects to this host outside loopback")
def test_network_permission_reaches_a_non_loopback_listener():
    prefix()
    try:
        addresses = {str(row[4][0]) for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except socket.gaierror:
        pytest.skip("host has no resolvable non-loopback IPv4")
    address = next((ip for ip in addresses if not ip.startswith("127.") and ip != "0.0.0.0"), None)
    if address is None:
        pytest.skip("host has no non-loopback IPv4")
    with socket.socket() as listener:
        listener.bind((address, 0))
        listener.listen(5)
        argv = [sys.executable, "-c", "import socket,sys; socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3)",
                address, str(listener.getsockname()[1])]
        host = mock.Mock()
        host.cfg.check_net_isolate = True
        host.cfg.check_scratch_home = False
        host.env.vars = {}
        host.bead_env = {}
        host.spawner.stream.side_effect = lambda cmd, **kw: subprocess.run(cmd, capture_output=True, timeout=20, check=False)
        shell = Shell(host)
        assert shell.stream(argv, None, {}, False, [], 20, "m1", "check", 0.0, mock.Mock()).returncode != 0
        assert shell.stream(argv, None, {}, False, [], 20, "m2", "check", 0.0, mock.Mock(), network=True).returncode == 0
