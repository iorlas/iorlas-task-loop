"""Standalone cursor, refusal and close boundaries over injected capabilities."""
from types import SimpleNamespace
from unittest import mock

import pytest
from support.pipeline_ports import FakeBeadClosing, FakeRoundSteps

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


def standalone(host, *, close_result=0, landed=False):
    return Standalone(host, rounds=FakeRoundSteps(), once=mock.Mock(), lease=mock.Mock(),
                      closing=FakeBeadClosing(close_result), has_land=lambda: landed,
                      repo_of=lambda git, wt: wt, stage_run=mock.Mock())


def test_close_refuses_failed_bead_close():
    claim = mock.Mock(spec=fence.Claim)
    host = SimpleNamespace(claim=claim, steps=mock.Mock(), checkpoints=mock.Mock())
    runner = standalone(host, close_result=1)
    with pytest.raises(ValueError, match="bead close failed"):
        runner.finish_step(Step.CLOSE, Bead(id=BeadId("t-1"), title="task", status="open"))
    assert isinstance(runner.closing, FakeBeadClosing)
    assert runner.closing.close_calls == [(claim, "standalone close: land on record")]
    host.checkpoints.drop_unless_fenced.assert_not_called()


@pytest.mark.parametrize("step,reason", [(Step.LAND, "no green gate"), (Step.CLOSE, "no land on record")])
def test_refuse_requires_evidence(step, reason):
    host = SimpleNamespace(lander=SimpleNamespace(gate=SimpleNamespace(green=lambda: False)))
    with pytest.raises(ValueError, match=reason):
        standalone(host).refuse(step)


def test_next_step_selects_from_previous_checkpoint_fresh_and_requested(workdir):
    home = ConfigDir(str(workdir))
    locator = RunLocator(home)
    host = SimpleNamespace(bead=BeadId("t-1"), run_id="current", git=mock.Mock(), wt="repo", fresh=False)
    old = locator.create("repo", host.bead, 1)
    locator.end(old.run, 2, RunState.DONE)
    ck = Checkpoint(bead=host.bead, run="prior", t=1, step="gate")
    with mock.patch("taskloop.app.pipeline.standalone.select_step", return_value=Step.LAND) as select:
        assert standalone(host).next_step(locator, ck, "land") is Step.LAND
    select.assert_called_once_with(locator.get(old.run), ck, False, "land")


@pytest.mark.parametrize("kind,kept", [(Kind.DONE, False), (Kind.STAGE, True)])
def test_record_stage_drops_park_only_when_finished(workdir, kind, kept):
    home = ConfigDir(str(workdir))
    bead = BeadId("t-1")
    parks = ParkStore(home)
    parks.put(Park(bead=bead, hash="", runs=1, run="old", t=1))
    host = SimpleNamespace(home=home, bead=bead, kind=kind, why="", landed_sha="", dry=False, records=mock.Mock())
    standalone(host).record_stage()
    assert (parks.get(bead) is not None) is kept
    assert host.records.finish.call_args.args[0].kind is kind


def test_round_dispatch_uses_injected_composition():
    host = SimpleNamespace(checkpoints=mock.Mock())
    runner = standalone(host)
    ck = Checkpoint(bead="t-1", run="prior", t=1)
    bead = Bead(id=BeadId("t-1"), title="task", status="open")
    assert runner.dispatch(Step.REVIEW, bead, ck) is Step.VERIFY
    assert isinstance(runner.rounds, FakeRoundSteps)
    assert runner.rounds.calls == [(Step.REVIEW, ck)]
    host.checkpoints.save.assert_not_called()
