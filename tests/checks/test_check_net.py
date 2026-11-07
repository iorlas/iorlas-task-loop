"""NETISO slice 1 (tl-7i9k.59): the pure choice of the prefix that takes a check's network away, and its place in the check's argv."""
import hashlib
from unittest import mock

import pytest

from taskloop.adapters import check_net
from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.run.shell import Shell
from taskloop.domain.checks.inputs import config_digest
from taskloop.domain.checks.specs import repo_check
from tlkernel import log as rec
from tlkernel.checks import Check
from tlkernel.config import CheckSpec, ConfigError, EngineConfig, load
from tlkernel.ids import CheckId
from tlkernel.kinds import Kind


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
    h.cfg.check_scratch_home = False
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


def test_a_host_that_cannot_isolate_refuses_the_check_with_the_reason():
    h = host(True)
    with (
        mock.patch.object(check_net, "plan", return_value=check_net.Plan((), "this host cannot remove the network")),
        pytest.raises(Blocked) as refused,
    ):
        Shell(h).stream(["just", "check"], None, {}, False, [], 60, "m1", "check", 0.0, mock.Mock())
    assert refused.value.kind == Kind.FAULT_INFRA
    assert "this host cannot remove the network" in str(refused.value)
    assert "engine.check_net_isolate" in str(refused.value)
    h.spawner.stream.assert_not_called()
    assert not any(isinstance(call.args[0], rec.Kill) for call in h.log.emit.call_args_list)

@pytest.mark.parametrize("network", [False, True])
def test_network_permission_on_a_host_that_cannot_isolate(network):
    h = host(True)
    with mock.patch.object(check_net, "current", return_value=check_net.Plan((), "cannot remove the network")), \
            mock.patch("taskloop.app.run.shell.check_nice", return_value=()):
        if network:
            Shell(h).stream(["just", "check"], None, {}, False, [], 60, "m1", "check", 0.0, mock.Mock(), network=True)
            assert h.spawner.stream.call_args.args[0] == ["just", "check"]
        else:
            with pytest.raises(Blocked, match="cannot remove the network"):
                Shell(h).stream(["just", "check"], None, {}, False, [], 60, "m1", "check", 0.0, mock.Mock(), network=False)
            h.spawner.stream.assert_not_called()


def test_network_config_loads_and_unknown_keys_are_refused():
    raw = {"engine": {"checks": [{"id": "net", "argv": ["true"], "network": True}]}}
    assert load(raw).engine.checks[0].network is True
    raw["engine"]["checks"][0]["netwrok"] = True
    with pytest.raises(ConfigError):
        load(raw)


def test_repo_check_carries_network():
    assert repo_check(CheckSpec(id=CheckId("net"), argv=["true"], network=True), EngineConfig()).network is True


def test_network_digest_preserves_the_default_and_distinguishes_permission():
    default = Check(id=CheckId("net"), cmd="true")
    assert config_digest(default) == hashlib.sha1(b'[[],[],false,"",[],[],[]]').hexdigest()
    assert config_digest(Check(id=default.id, cmd=default.cmd, network=False)) == config_digest(default)
    assert config_digest(Check(id=default.id, cmd=default.cmd, network=True)) != config_digest(default)
