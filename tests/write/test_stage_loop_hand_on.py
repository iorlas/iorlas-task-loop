"""B-WRITE 2: the write and check rounds leave their hand-offs in StageState.out; StageLoop.hand_on puts them on the engine once and clears
them, also when the round raises, and in the standalone step runner (run_round_step) that calls the rounds directly."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.cfgs import plan_of
from support.plans import PLAN

from taskloop.app.run.stage_rounds import run_round_step
from taskloop.app.write.stage_loop import StageLoop
from taskloop.app.write.state import REPLAN, StageState
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.enums import Step

OLD = {"tests_added": 1, "tests_removed": 2, "rounds": 5, "writes": 7}


def host():
    return SimpleNamespace(last_run="old", stuck_why="old why", last_summary="old summary", stats=dict(OLD))


def state():
    return StageState(plan_of(PLAN), 0, None)


def test_hand_on_applies_what_the_round_left_and_clears_it():
    e, s = host(), state()
    run = CheckRun(round=1, results=[])
    s.out.run, s.out.stuck_why, s.out.tests, s.out.rounds = run, "why", (3, 4), 1
    s.out.writes, s.out.summary = 2, "done"
    StageLoop(e).hand_on(s)
    assert (e.last_run, e.stuck_why, e.last_summary) == (run, "why", "done")
    assert e.stats == {"tests_added": 3, "tests_removed": 4, "rounds": 6, "writes": 9}
    StageLoop(e).hand_on(s)  # nothing new: a second call changes nothing
    assert (e.stuck_why, e.stats["rounds"], e.stats["writes"]) == ("why", 6, 9)


def test_hand_on_with_nothing_left_keeps_the_engine_as_it_was():
    e = host()
    StageLoop(e).hand_on(state())
    assert (e.last_run, e.stuck_why, e.last_summary, e.stats) == ("old", "old why", "old summary", OLD)


def test_a_round_that_raises_still_hands_on():
    e, s = host(), state()
    loop = StageLoop(e)

    def parks(st):
        st.out.stuck_why = "parked"
        raise RuntimeError("ASK_STUCK")

    with mock.patch.object(loop.checking, "run", side_effect=parks), pytest.raises(RuntimeError):
        loop.check(s)
    assert e.stuck_why == "parked"


def test_the_standalone_checks_step_hands_on_too():
    e, s = mock.Mock(), state()
    e.stuck_why, e.stats = "old why", dict(OLD)
    e.stage_loop = loop = StageLoop(e)

    def red(st):
        st.out.stuck_why = "checks still red"
        return REPLAN

    with mock.patch.object(loop.checking, "run", side_effect=red):
        following, _ = run_round_step(e, Step.CHECKS, s)
    assert (following, e.stuck_why) == (Step.REPLAN, "checks still red")
