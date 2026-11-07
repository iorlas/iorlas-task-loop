"""ROUNDRESULT: a write, check or review round returns what it came to (a RoundResult); StageLoop.play puts it on the engine once, also when
the round raises (the closer still reads the run and why), also in the standalone step runner (run_round_step)."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.app.write.rounds import run_round_step
from taskloop.app.write.stage_loop import StageLoop
from taskloop.app.write.state import REPLAN, RoundResult, RoundStop, StageState, WriteState, carrying
from tlkernel.checks import CheckRun
from tlkernel.enums import Step
from tltestkit.cfgs import plan_of
from tltestkit.plans import PLAN

OLD = {"tests_added": 1, "tests_removed": 2, "rounds": 5, "writes": 7, "reviews": 3}


def host():
    return SimpleNamespace(last_run="old", stuck_why="old why", stats=dict(OLD), writer_family="old",
                           writer=SimpleNamespace(last_stage=False), write=WriteState())


def state():
    return StageState(plan_of(PLAN), 0, None)


def test_play_applies_the_result_and_answers_its_flow():
    e, s = host(), state()
    run = CheckRun(round=1, results=[])
    got = RoundResult(flow="again", run=run, stuck_why="why", tests=(3, 4), rounds=1, writes=2, reviews=1, summary="done",
                      family="openai", last_stage=True, write_rows=({"write": 1},))
    assert StageLoop(e).play(lambda st: got, s) == "again"
    assert (e.last_run, e.stuck_why, e.write.last_summary, e.writer_family, e.writer.last_stage) == (run, "why", "done", "openai", True)
    assert e.stats == {"tests_added": 3, "tests_removed": 4, "rounds": 6, "writes": 9, "reviews": 4}
    assert e.write.write_rounds == [{"write": 1}]


def test_an_empty_result_keeps_the_engine_as_it_was():
    e = host()
    assert StageLoop(e).play(lambda st: RoundResult(), state()) == ""
    assert (e.last_run, e.stuck_why, e.stats, e.writer_family) == ("old", "old why", OLD, "old")
    assert e.write.last_summary == ""


def test_a_round_that_raises_still_hands_on_and_raises_the_cause():
    e = host()

    def parks(st):
        out = RoundResult(stuck_why="parked")
        with carrying(out):
            raise RuntimeError("ASK_STUCK")

    with pytest.raises(RuntimeError, match="ASK_STUCK"):
        StageLoop(e).play(parks, state())
    assert e.stuck_why == "parked"


def test_carrying_wraps_any_exception_with_the_result():
    out = RoundResult(rounds=2)
    with pytest.raises(RoundStop) as got, carrying(out):
        raise KeyError("x")
    assert (got.value.result, type(got.value.cause)) == (out, KeyError)


def test_the_standalone_checks_step_hands_on_too():
    e, s = mock.Mock(), state()
    e.stuck_why, e.stats = "old why", dict(OLD)
    e.stage_loop = loop = StageLoop(e)
    with mock.patch.object(loop.checking, "run", return_value=RoundResult(flow=REPLAN, stuck_why="checks still red")):
        following, _ = run_round_step(e, Step.CHECKS, s)
    assert (following, e.stuck_why) == (Step.REPLAN, "checks still red")
