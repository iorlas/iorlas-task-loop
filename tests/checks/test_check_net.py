"""NETISO slice 1 (tl-7i9k.59): the pure choice of the prefix that takes a check's network away, and its place in the check's argv."""
from unittest import mock

import pytest

from taskloop.adapters import check_net
from taskloop.app.run.shell import Shell


def found(*names):
    return lambda name: f"/bin/{name}" if name in names else None


@pytest.mark.parametrize(("system", "tools", "userns", "head"), [
    ("Linux", ("unshare",), True, ["/bin/unshare", "-rn"]),
    ("Darwin", ("sandbox-exec",), False, ["/bin/sandbox-exec", "-p"]),
])
def test_a_host_with_a_tool_gets_its_prefix(system, tools, userns, head):
    plan = check_net.plan(system, found(*tools), lambda: userns)
    assert plan.warning == ""
    assert list(plan.prefix[: len(head)]) == head


def test_the_linux_prefix_brings_loopback_up_then_runs_the_check():
    prefix = check_net.plan("Linux", found("unshare"), lambda: True).prefix
    assert prefix[-2:] == ("sh", "-c") or "lo up" in " ".join(prefix)
    assert prefix[-1] == "sh"  # $0 of the wrapper script; the check's argv follows as "$@"


def test_the_mac_profile_denies_the_network_but_not_loopback():
    profile = check_net.plan("Darwin", found("sandbox-exec"), lambda: False).prefix[2]
    assert "(deny network*)" in profile and "localhost" in profile


@pytest.mark.parametrize(("system", "tools", "userns"), [
    ("Linux", (), True),  # no unshare
    ("Linux", ("unshare",), False),  # user namespaces off (the devbox container)
    ("Darwin", (), False),
    ("Windows", ("unshare",), True),
])
def test_a_host_that_cannot_remove_the_network_warns_and_adds_nothing(system, tools, userns):
    plan = check_net.plan(system, found(*tools), lambda: userns)
    assert plan.prefix == ()
    assert "cannot remove the network" in plan.warning


def host(isolate):
    h = mock.Mock()
    h.cfg.check_net_isolate = isolate
    h.env.vars = {"PATH": "/bin"}
    h.bead_env = {}
    h.spawner.stream.return_value = mock.Mock()
    return h


def argv_of_check(h):
    with mock.patch.object(check_net, "plan", return_value=check_net.Plan(("netoff", "--"), "")), \
            mock.patch("taskloop.app.run.shell.check_nice", return_value=()):
        Shell(h).stream(["just", "check"], None, {}, False, [], 60, "m1", "check", 0.0, mock.Mock())
    return h.spawner.stream.call_args.args[0]


def test_the_setting_off_leaves_the_checks_argv_alone():
    assert argv_of_check(host(False)) == ["just", "check"]


def test_the_setting_on_puts_the_prefix_before_the_check():
    assert argv_of_check(host(True)) == ["netoff", "--", "just", "check"]


def test_a_host_that_cannot_isolate_says_so_once_and_still_runs_the_check():
    h = host(True)
    with mock.patch.object(check_net, "plan", return_value=check_net.Plan((), "this host cannot remove the network")):
        check_net.said.clear()
        for _ in range(2):
            Shell(h).stream(["just", "check"], None, {}, False, [], 60, "m1", "check", 0.0, mock.Mock())
    assert h.spawner.stream.call_args.args[0][-2:] == ["just", "check"]
    assert h.log.note.call_count == 1
