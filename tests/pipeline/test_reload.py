"""Reload preserves counters and hands over only at eligible step boundaries."""
from unittest.mock import Mock, patch

import pytest
from support.pipeline_ports import FakeReexecs, FakeTrail

from taskloop.app.pipeline.reload import Exec, Reload
from taskloop.contracts import rundocs
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir


@pytest.fixture
def setup_reload(workdir):
    host = Mock(home=ConfigDir(workdir), run_id="run", bead=BeadId("t-1"), wt=str(workdir), env=snapshot(),
                t0=90, waited=2, cost=3, stats={"tokens": 4}, sessions=[{"node": "write"}],
                dry=False, moved=False, argv=["run-task", "t-1"], newer_fn=None, exec_fn=None)
    host.write.write_rounds = []
    host.steps.n = 5
    reexecs, trail = FakeReexecs(), FakeTrail()
    reload = Reload(host, reexecs, trail, lambda: ("2.0", workdir / "install"), lambda: "slot")
    return host, reexecs, trail, reload


def test_counter_round_trip(setup_reload):
    host, _, _, reload = setup_reload
    with patch("taskloop.app.pipeline.reload.time.time", return_value=100):
        counters = reload.counters()
    doc = Mock()
    doc.get.return_value = counters
    host.cost, host.stats, host.sessions, host.steps.n = 0, {}, [], 0
    reload.restore_run(doc)
    host.budget.restore.assert_called_once_with(10, 2)
    assert (host.cost, host.stats, host.sessions, host.steps.n) == (3, {"tokens": 4}, [{"node": "write"}], 5)
    assert host.write.write_rounds == counters.write_rounds


def test_net_pause_saved_and_write_failure_warns(setup_reload):
    host, reexecs, _, reload = setup_reload
    reload.save_net_pause()
    assert reexecs.pauses[0].run == host.run_id
    saved = rundocs.pause(host.home, host.run_id).get()
    assert saved is not None and saved.cost == 3
    reexecs.error = OSError("disk")
    reload.save_net_pause()
    assert "network pause" in host.warn.call_args.args[0]


@pytest.mark.parametrize("dry,no_args", [(True, False), (False, True)])
def test_ineligible_boundary_does_nothing(setup_reload, dry, no_args):
    host, reexecs, trail, reload = setup_reload
    host.dry = dry
    if no_args:
        reexecs.argv = None
    reload.safe_point("write")
    assert not reexecs.notes and not reexecs.execs and not trail.events


def test_newer_install_hands_over_and_execs(setup_reload):
    host, reexecs, trail, reload = setup_reload
    with pytest.raises(Exec):
        reload.safe_point("write")
    assert host.moved
    assert reexecs.notes[0].step == "write"
    saved = rundocs.reexec(host.home, host.run_id).get()
    assert saved is not None and saved.node_n == 5
    assert trail.events[0][1:3] == ("reload", host.bead)
    assert str(host.home.root / "install" / "skills" / "task-loop" / "tl.py") in reexecs.execs[0][0]


def test_exec_failure_drops_note_and_warns(setup_reload):
    host, reexecs, _, reload = setup_reload
    reexecs.error = OSError("exec failed")
    reload.safe_point("write")
    assert reexecs.dropped == [host.bead]
    assert not host.moved
    assert "exec failed" in host.warn.call_args.args[0]


def test_host_lookup_override_is_honoured(setup_reload):
    host, reexecs, _, reload = setup_reload
    host.newer_fn = Mock(return_value=None)
    reload.safe_point("write")
    host.newer_fn.assert_called_once_with()
    assert not reexecs.execs
