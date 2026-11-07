"""The run body's refusal boundaries and stage hand-offs over fakes."""

from types import SimpleNamespace
from unittest import mock

import pytest

from taskloop.adapters import beadtools, ident
from tlkernel.bead import Bead
from tlkernel.checkpoint import RunState
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData, RoundState
from tlpipeline import run, run_roles
from tlpipeline.blocked import Blocked
from tlpipeline.run import RunBody
from tlpipeline.testing import FakeHeadHistory, FakeNarrate


def roles():
    return SimpleNamespace(
        leasing=SimpleNamespace(stop_pending=False, halt=SimpleNamespace(is_set=lambda: False),
                                store=SimpleNamespace(), bead="t-1", dry=True,
                                cfg=SimpleNamespace(writer_exec=False, reviewer_other_family=True, base="main",
                                                    max_replans=1, max_rounds=3)),
        delegating=SimpleNamespace(delegation=mock.Mock(), route="delegate", refusal=None,
                                   contract={"contract": 1, "capabilities": []}, router=SimpleNamespace(contract_no=1)),
        stages=SimpleNamespace(planner=mock.Mock(), stage_loop=mock.Mock(), lander=mock.Mock()),
        records=SimpleNamespace(log=FakeNarrate(), tree=mock.Mock(), budget=SimpleNamespace(labels=[]),
                                ask_flow=mock.Mock(), answered=None, checkpoints=mock.Mock(), reload=mock.Mock()),
        moves=SimpleNamespace(wt="tree"),
        values=SimpleNamespace(bead_title="", bead_parent="", scope="", state=RunState(replans=1),
                               stats={}, stuck_why="stuck"),
        crashes=SimpleNamespace(),
    )


def run_body(parts, history=None, beat=None):
    return RunBody(parts.leasing, parts.delegating, parts.stages, parts.records, parts.moves,
                   parts.values, parts.crashes, history or FakeHeadHistory(), beat or mock.Mock(), beadtools.peek, ident.plugin_version)


@pytest.mark.parametrize("refusal,kind", [
    ("stop", Kind.PAUSE_KILLED), ("missing", Kind.FAULT_INFRA),
    ("route", Kind.FAULT_CONTRACT_SKEW), ("acceptance", Kind.ASK_TICKET),
])
def test_begin_refuses(refusal, kind):
    h = roles()
    h.leasing.stop_pending = refusal == "stop"
    if refusal == "route":
        h.delegating.route = ""
    bead = None if refusal == "missing" else Bead(id=BeadId("t-1"), title="Task", status="open")
    lease, beat = mock.Mock(), mock.Mock()
    with mock.patch("taskloop.adapters.beadtools.peek", return_value=bead), \
            mock.patch("taskloop.adapters.ident.plugin_version", return_value="test"), \
            pytest.raises(Blocked) as caught:
        run_body(h, FakeHeadHistory(), beat).begin(lease)
    assert caught.value.kind is kind
    if refusal in ("stop", "missing"):
        lease.start.assert_not_called()
        beat.assert_not_called()
    else:
        lease.start.assert_called_once_with()
        beat.assert_called_once_with()


def test_stages_accept_push_checkpoint_and_reload_in_order():
    h = roles()
    h.values.state.pending_land_validation = "recovering"
    h.stages.stage_loop.run.return_value = ""
    events = mock.Mock()
    for name, child in [("stage", h.stages.stage_loop.run), ("push", h.stages.lander.out.wip_push),
                        ("save", h.records.checkpoints.save), ("reload", h.records.reload.safe_point)]:
        events.attach_mock(child, name)
    plan: PlanData = {"stages": [{"goal": "first", "files": [], "checks": []},
                                 {"goal": "second", "files": [], "checks": []}]}
    state: RoundState = {"fix": False}
    run_body(h, FakeHeadHistory(), mock.Mock()).stages(plan, 0, state)
    assert h.values.state.accepted == [0, 1]
    assert h.values.state.done == ["first", "second"]
    assert h.values.state.pending_land_validation == ""
    assert events.mock_calls == [
        mock.call.stage(plan, 0, state), mock.call.push(1),
        mock.call.save(stage=1, rounds=0, n=0, feedback="", step="write"),
        mock.call.stage(plan, 1, None), mock.call.push(2),
        mock.call.save(stage=2, rounds=0, n=0, feedback="", step="land"), mock.call.reload("land"),
    ]


def test_replan_past_cap_raises_planners_block():
    h = roles()
    blocked = Blocked("cap", kind=Kind.OWNER_PARK)
    h.stages.planner.cap.blocked.return_value = blocked
    with pytest.raises(Blocked) as caught:
        run_body(h, FakeHeadHistory(), mock.Mock()).replan(2)
    assert caught.value is blocked
    assert h.values.stats["replans"] == 2
    h.stages.planner.cap.blocked.assert_called_once_with("stage 3 stuck after 3 rounds. What failed: stuck")
    h.stages.planner.plan.assert_not_called()


def test_its_work_formats_the_history_port():
    h = roles()
    history = FakeHeadHistory("one\ntwo")
    assert run_body(h, history, mock.Mock()).its_work() == "Its work: one; two"
    assert history.calls == [("tree", "main", 3)]


def test_stages_follow_state_replaced_by_restart_between_calls():
    h = roles()
    original = h.values.state
    body = run_body(h, FakeHeadHistory(), mock.Mock())
    fresh = RunState(pending_land_validation="validate restarted attempt")
    h.stages.stage_loop.run.side_effect = lambda *_: setattr(h.values, "state", fresh) or ""
    plan: PlanData = {"stages": [{"goal": "restarted", "files": [], "checks": []}]}
    body.stages(plan, 0, None)
    assert original.accepted == original.done == []
    assert (fresh.accepted, fresh.done, fresh.pending_land_validation) == ([0], ["restarted"], "")


def test_run_protocols_have_at_most_sixteen_members():
    def members(protocol):
        return {name for base in protocol.__mro__ for name, value in vars(base).items()
                if isinstance(value, property) or (callable(value) and not name.startswith("_"))} | {
                    name for base in protocol.__mro__ for name in vars(base).get("__annotations__", {})}

    protocols = {name: value for module in (run, run_roles) for name, value in vars(module).items()
                 if isinstance(value, type) and getattr(value, "_is_protocol", False)}
    assert protocols
    assert {name: len(members(value)) for name, value in protocols.items() if len(members(value)) > 16} == {}


def test_constructing_body_does_not_resolve_lazy_role_members():
    class LazyRole:
        def __getattribute__(self, name):
            raise AssertionError(f"constructor resolved {name}")

    lazy = LazyRole()
    parts = roles()
    RunBody(lazy, lazy, lazy, lazy, lazy, parts.values, parts.crashes, FakeHeadHistory(), lambda: None,
            beadtools.peek, ident.plugin_version)
