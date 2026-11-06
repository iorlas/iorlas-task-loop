"""The crash matrix, slice 1: a run that dies at each point of each transition resumes at a step the records allow.

The records a run leaves are the manifest's `next_step` (advanced before a step's work and again when it returns) and the checkpoint's
`step` (saved when the work returns, before the second advance). A kill between any two of those writes leaves one of four states,
and the reconciler marks the dead run LOST. `select_step` reads them back; for every edge of the step graph and every kill point it
must answer the step the table says: the same step again (at-least-once, so every step must be repeatable) or its successor, never a
step before it or past its successor, and never an error for a lost run. Pure: no clock, no process."""
from pathlib import Path

import pytest

from taskloop.app.run.stages import select_step
from taskloop.contracts.checkpoint import Checkpoint, EndRec
from taskloop.contracts.enums import Step
from taskloop.contracts.locator import RunBundle
from taskloop.contracts.run import RunManifest, RunState

S = Step
# (step, the steps its work can hand on to): stages.dispatch and stage_rounds.round_step. Slice 2 derives this from the code.
EDGES = [
    (S.RESET, S.PLAN), (S.PLAN, S.WRITE), (S.REPLAN, S.WRITE),
    (S.WRITE, S.WRITE), (S.WRITE, S.CHECKS), (S.WRITE, S.VERIFY), (S.WRITE, S.REPLAN),
    (S.CHECKS, S.REVIEW), (S.CHECKS, S.WRITE), (S.CHECKS, S.VERIFY),
    (S.REVIEW, S.WRITE), (S.REVIEW, S.LOOK), (S.REVIEW, S.VERIFY), (S.REVIEW, S.REPLAN),
    (S.LOOK, S.VERIFY), (S.LOOK, S.WRITE), (S.VERIFY, S.GATE), (S.GATE, S.LAND), (S.LAND, S.CLOSE), (S.CLOSE, S.REFLECT),
]
STARTED, CK_AT = 1000.0, 1500.0
POINTS = ["work-begun", "work-done-checkpoint-saved", "advanced"]


def bundle(manifest_next: Step | None, state: RunState = RunState.LOST, run: str = "r1") -> RunBundle:
    m = RunManifest(run=run, repo="/r", bead="t-1", started=STARTED, state=state, next_step=manifest_next)
    p = Path("/none")
    return RunBundle(manifest=m, log=p, err=p, live=p, dir=p)


def checkpoint(step: str, run: str = "r1", t: float = CK_AT, ended: EndRec | None = None) -> Checkpoint:
    return Checkpoint(bead="t-1", run=run, t=t, step=step, ended=ended)


def after_kill(step: Step, nxt: Step, point: str) -> tuple[RunBundle, Checkpoint]:
    """The records a run holds when it died at `point` of the edge step -> nxt."""
    if point == "work-begun":  # advanced to `step`, the work is not done: the checkpoint is the one the step before saved
        return bundle(step), checkpoint(step)
    if point == "work-done-checkpoint-saved":  # the work returned and saved its successor, the manifest not yet advanced
        return bundle(step), checkpoint(nxt)
    return bundle(nxt), checkpoint(nxt)


@pytest.mark.parametrize("point", POINTS)
@pytest.mark.parametrize(("step", "nxt"), EDGES, ids=lambda s: str(s.value))
def test_a_lost_run_resumes_at_the_step_or_its_successor_at_every_kill_point(step, nxt, point):
    last, ck = after_kill(step, nxt, point)
    got = select_step(last, ck, fresh=False, requested=None)
    assert got == (nxt if point == "advanced" else step)
    assert got in (step, nxt)


@pytest.mark.parametrize(("step", "nxt"), EDGES, ids=lambda s: str(s.value))
def test_a_run_that_is_still_live_is_not_resumed(step, nxt):
    with pytest.raises(ValueError, match="still"):
        select_step(bundle(step, RunState.RUNNING), checkpoint(step), fresh=False, requested=None)


@pytest.mark.parametrize("point", POINTS)
def test_a_new_run_after_a_kill_reads_the_dead_runs_records(point):
    """The next run has its own id: the manifest of the dead one still names the step when the checkpoint is not newer than it."""
    last, ck = after_kill(S.GATE, S.LAND, point)
    older = checkpoint(ck.step, run="r0", t=STARTED - 1)
    assert select_step(last, older, fresh=False, requested=None) == (S.LAND if point == "advanced" else S.GATE)


def test_a_checkpoint_newer_than_the_dead_run_of_another_run_is_the_cursor():
    last = bundle(S.GATE)
    assert select_step(last, checkpoint("land", run="r2"), fresh=False, requested=None) == S.LAND


def test_an_ended_checkpoint_resumes_at_close_and_a_red_gate_at_replan():
    gone = bundle(None)
    assert select_step(gone, checkpoint("land", ended=EndRec(run="r1", kind="landed", fingerprint="", detail="")), fresh=False,
                       requested=None) == S.CLOSE
    assert select_step(gone, checkpoint("gate-red"), fresh=False, requested=None) == S.REPLAN
    assert select_step(gone, checkpoint("land-verify-red"), fresh=False, requested=None) == S.REPLAN


def test_a_finished_run_has_no_next_step_unless_one_is_named():
    done = bundle(None, RunState.DONE)
    with pytest.raises(ValueError, match="complete"):
        select_step(done, None, fresh=False, requested=None)
    assert select_step(done, None, fresh=True, requested=None) == S.RESET
    assert select_step(done, None, fresh=False, requested="gate") == S.GATE


def test_no_record_at_all_starts_at_reset():
    assert select_step(None, None, fresh=False, requested=None) == S.RESET
