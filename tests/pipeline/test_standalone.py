"""Standalone cursor, refusal and close boundaries over injected capabilities."""

from types import SimpleNamespace
from unittest import mock

import pytest
from support.pipeline_ports import FakeBeadClosing, FakeRoundSteps

from taskloop.adapters import beadtools
from taskloop.app.pipeline import closing_roles, standalone_roles
from taskloop.app.pipeline import standalone as standalone_module
from taskloop.app.pipeline.standalone import Standalone
from tlkernel import fence
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint
from tlkernel.enums import Step
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.locator import RunLocator
from tlkernel.parks import Park, ParkStore
from tlkernel.paths import ConfigDir
from tlkernel.run import RunState


def roles():
    return SimpleNamespace(
        context=SimpleNamespace(claim=None, dry=False, fresh=False, git=None, wt="repo"),
        cursor=SimpleNamespace(steps=mock.Mock(), checkpoints=mock.Mock()),
        operations=SimpleNamespace(lander=SimpleNamespace(gate=SimpleNamespace(green=lambda: False))),
        values=SimpleNamespace(landed_sha=""),
        journalling=SimpleNamespace(bead=BeadId("t-1"), run_id="current", records=mock.Mock()),
    )


def standalone(parts, *, close_result=0, landed=False):
    return Standalone(parts.context, parts.cursor, parts.operations, parts.values, parts.journalling,
                      rounds=FakeRoundSteps(), once=mock.Mock(), lease=mock.Mock(),
                      closing=FakeBeadClosing(close_result), has_land=lambda: landed,
                      repo_of=lambda git, wt: wt, stage_run=mock.Mock(), peek_bead=beadtools.peek)


def test_close_refuses_failed_bead_close():
    claim = mock.Mock(spec=fence.Claim)
    parts = roles()
    parts.context.claim = claim
    runner = standalone(parts, close_result=1)
    with pytest.raises(ValueError, match="bead close failed"):
        runner.finish_step(Step.CLOSE, Bead(id=BeadId("t-1"), title="task", status="open"))
    assert isinstance(runner.closing, FakeBeadClosing)
    assert runner.closing.close_calls == [(claim, "standalone close: land on record")]
    parts.cursor.checkpoints.drop_unless_fenced.assert_not_called()


@pytest.mark.parametrize("step,reason", [(Step.LAND, "no green gate"), (Step.CLOSE, "no land on record")])
def test_refuse_requires_evidence(step, reason):
    parts = roles()
    with pytest.raises(ValueError, match=reason):
        standalone(parts).refuse(step)


def test_next_step_selects_from_previous_checkpoint_fresh_and_requested(workdir):
    home = ConfigDir(str(workdir))
    locator = RunLocator(home)
    parts = roles()
    old = locator.create("repo", parts.journalling.bead, 1)
    locator.end(old.run, 2, RunState.DONE)
    ck = Checkpoint(bead=parts.journalling.bead, run="prior", t=1, step="gate")
    with mock.patch("taskloop.app.pipeline.standalone.select_step", return_value=Step.LAND) as select:
        assert standalone(parts).next_step(locator, ck, "land") is Step.LAND
    select.assert_called_once_with(locator.get(old.run), ck, False, "land")


@pytest.mark.parametrize("kind,kept", [(Kind.DONE, False), (Kind.STAGE, True)])
def test_record_stage_drops_park_only_when_finished(workdir, kind, kept):
    home = ConfigDir(str(workdir))
    bead = BeadId("t-1")
    parks = ParkStore(home)
    parks.put(Park(bead=bead, hash="", runs=1, run="old", t=1))
    parts = roles()
    parts.journalling.home, parts.journalling.kind, parts.journalling.why = home, kind, ""
    standalone(parts).record_stage()
    assert (parks.get(bead) is not None) is kept
    assert parts.journalling.records.finish.call_args.args[0].kind is kind


def test_round_dispatch_uses_injected_composition():
    parts = roles()
    runner = standalone(parts)
    ck = Checkpoint(bead="t-1", run="prior", t=1)
    bead = Bead(id=BeadId("t-1"), title="task", status="open")
    assert runner.dispatch(Step.REVIEW, bead, ck) is Step.VERIFY
    assert isinstance(runner.rounds, FakeRoundSteps)
    assert runner.rounds.calls == [(Step.REVIEW, ck)]
    parts.cursor.checkpoints.save.assert_not_called()


def test_standalone_protocols_have_at_most_sixteen_own_members():
    def members(protocol):
        return set(protocol.__annotations__) | {
            name for name, value in vars(protocol).items()
            if isinstance(value, property) or (callable(value) and not name.startswith("_"))}

    protocols = {name: value for module in (standalone_module, standalone_roles, closing_roles) for name, value in vars(module).items()
                 if isinstance(value, type) and getattr(value, "_is_protocol", False)
                 and value.__module__ in (standalone_module.__name__, standalone_roles.__name__, closing_roles.__name__)}
    assert protocols
    assert {name: len(members(value)) for name, value in protocols.items() if len(members(value)) > 16} == {}


def test_constructing_standalone_does_not_resolve_lazy_role_members():
    class LazyRole:
        def __getattribute__(self, name):
            raise AssertionError(f"constructor resolved {name}")

    lazy = LazyRole()
    standalone(SimpleNamespace(context=lazy, cursor=lazy, operations=lazy, values=lazy, journalling=lazy))
