"""The crash matrix: a run that dies at each point of each transition resumes at a step the records allow.

The edges of the step graph are read off the code (tests/support/stepgraph.py). The records a run leaves are the manifest's `next_step`
(advanced before a step's work and again when it returns) and the checkpoint's `step` (saved when the work returns, before the second
advance). A kill between any two of those writes leaves one of three states, and the reconciler marks the dead run LOST. `select_step`
reads them back; for every edge and every kill point it must answer the same step again (at-least-once, so every step must be
repeatable) or its successor, never a step before it or past its successor, and never an error for a lost run. Pure: no clock, no
process."""
from pathlib import Path

import pytest
from support import stepgraph

from tlkernel.checkpoint import Checkpoint, CloseIntent, EndRec, PauseFacts
from tlkernel.enums import Step
from tlkernel.locator import RunBundle
from tlkernel.run import RunManifest, RunState
from tlpipeline.cursor import select_step

S = Step
GRAPH = stepgraph.graph()  # read off the code (tests/support/stepgraph.py), not typed here
EDGES = sorted(((a, b) for a, nexts in GRAPH.items() for b in nexts if b is not None), key=lambda e: (e[0].value, e[1].value))
STARTED, CK_AT = 1000.0, 1500.0
POINTS = ["work-begun", "work-done-checkpoint-saved", "advanced"]


def bundle(manifest_next: Step | None, state: RunState = RunState.LOST, run: str = "r1") -> RunBundle:
    m = RunManifest(run=run, repo="/r", bead="t-1", started=STARTED, state=state, next_step=manifest_next)
    p = Path("/none")
    return RunBundle(manifest=m, log=p, err=p, live=p, dir=p)


def checkpoint(step: str, run: str = "r1", t: float = CK_AT, ended: EndRec | None = None) -> Checkpoint:
    return Checkpoint(bead="t-1", run=run, t=t, step=step, ended=CloseIntent(outcome=ended, pause=PauseFacts()) if ended else None)


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


def test_the_graph_read_from_the_code_covers_every_step_and_ends_at_reflect():
    assert set(GRAPH) == set(Step)
    assert [s for s, nexts in GRAPH.items() if None in nexts] == [S.REFLECT]
    assert all(nexts for nexts in GRAPH.values())
