"""The run body's refusal boundaries and stage hand-offs over fakes."""
from types import SimpleNamespace
from unittest import mock

import pytest
from support.pipeline_ports import FakeHeadHistory, FakeNarrate

from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.pipeline.run import RunBody
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData, RoundState


def host():
    return SimpleNamespace(
        stop_pending=False, halt=SimpleNamespace(is_set=lambda: False), store=mock.Mock(), bead="t-1",
        bead_title="", bead_parent="", delegation=mock.Mock(), route="delegate", refusal=None,
        cfg=SimpleNamespace(writer_exec_allow=[], writer_family=[], base="main", max_replans=1, max_rounds=3),
        contract={"contract": 1, "capabilities": []}, router=SimpleNamespace(contract_no=1),
        log=FakeNarrate(), tree=mock.Mock(), budget=SimpleNamespace(labels=[]), ask_flow=mock.Mock(),
        planner=mock.Mock(), answered=None, accepted=[], done=[], dry=True, pending_land_validation="",
        stage_loop=mock.Mock(), lander=mock.Mock(), checkpoints=mock.Mock(), reload=mock.Mock(),
        replans=1, extra=0, stats={}, stuck_why="stuck", wt="tree",
    )


@pytest.mark.parametrize("refusal,kind", [
    ("stop", Kind.PAUSE_KILLED), ("missing", Kind.FAULT_INFRA),
    ("route", Kind.FAULT_CONTRACT_SKEW), ("acceptance", Kind.ASK_TICKET),
])
def test_begin_refuses(refusal, kind):
    h = host()
    h.stop_pending = refusal == "stop"
    if refusal == "route":
        h.route = ""
    bead = None if refusal == "missing" else Bead(id=BeadId("t-1"), title="Task", status="open")
    lease, beat = mock.Mock(), mock.Mock()
    with mock.patch("taskloop.app.pipeline.run.beadtools.peek", return_value=bead), \
            mock.patch("taskloop.app.pipeline.run.ident.plugin_version", return_value="test"), \
            pytest.raises(Blocked) as caught:
        RunBody(h, FakeHeadHistory(), beat).begin(lease)
    assert caught.value.kind is kind
    if refusal in ("stop", "missing"):
        lease.start.assert_not_called()
        beat.assert_not_called()
    else:
        lease.start.assert_called_once_with()
        beat.assert_called_once_with()


def test_stages_accept_push_checkpoint_and_reload_in_order():
    h = host()
    h.pending_land_validation = "recovering"
    h.stage_loop.run.return_value = ""
    events = mock.Mock()
    for name, child in [("stage", h.stage_loop.run), ("push", h.lander.out.wip_push),
                        ("save", h.checkpoints.save), ("reload", h.reload.safe_point)]:
        events.attach_mock(child, name)
    plan: PlanData = {"stages": [{"goal": "first", "files": [], "checks": []},
                                 {"goal": "second", "files": [], "checks": []}]}
    state: RoundState = {"fix": False}
    RunBody(h, FakeHeadHistory(), mock.Mock()).stages(plan, 0, state)
    assert h.accepted == [0, 1]
    assert h.done == ["first", "second"]
    assert h.pending_land_validation == ""
    assert events.mock_calls == [
        mock.call.stage(plan, 0, state), mock.call.push(1),
        mock.call.save(stage=1, rounds=0, n=0, feedback="", step="write"),
        mock.call.stage(plan, 1, None), mock.call.push(2),
        mock.call.save(stage=2, rounds=0, n=0, feedback="", step="land"), mock.call.reload("land"),
    ]


def test_replan_past_cap_raises_planners_block():
    h = host()
    blocked = Blocked("cap", kind=Kind.OWNER_PARK)
    h.planner.cap.blocked.return_value = blocked
    with pytest.raises(Blocked) as caught:
        RunBody(h, FakeHeadHistory(), mock.Mock()).replan(2)
    assert caught.value is blocked
    assert h.stats["replans"] == 2
    h.planner.cap.blocked.assert_called_once_with("stage 3 stuck after 3 rounds. What failed: stuck")
    h.planner.plan.assert_not_called()


def test_its_work_formats_the_history_port():
    h = host()
    history = FakeHeadHistory("one\ntwo")
    assert RunBody(h, history, mock.Mock()).its_work() == "Its work: one; two"
    assert history.calls == [("tree", "main", 3)]
