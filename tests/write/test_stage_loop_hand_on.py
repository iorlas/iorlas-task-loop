"""B-WRITE 2: a check round leaves its hand-offs in StageState.out; StageLoop.hand_on puts them on the engine once and clears them."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.cfgs import plan_of
from support.plans import PLAN

from taskloop.app.write.stage_loop import StageLoop
from taskloop.app.write.state import StageState
from taskloop.contracts.checks import CheckRun


def host():
    return SimpleNamespace(last_run="old", stuck_why="old why", stats={"tests_added": 1, "tests_removed": 2, "rounds": 5})


def test_hand_on_applies_what_the_round_left_and_clears_it():
    e = host()
    s = StageState(plan_of(PLAN), 0, None)
    run = CheckRun(round=1, results=[])
    s.out.run, s.out.stuck_why, s.out.tests, s.out.rounds = run, "why", (3, 4), 1
    StageLoop(e).hand_on(s)
    assert (e.last_run, e.stuck_why, e.stats) == (run, "why", {"tests_added": 3, "tests_removed": 4, "rounds": 6})
    StageLoop(e).hand_on(s)  # nothing new: a second call changes nothing
    assert (e.last_run, e.stuck_why, e.stats["rounds"]) == (run, "why", 6)


def test_hand_on_with_nothing_left_keeps_the_engine_as_it_was():
    e = host()
    StageLoop(e).hand_on(StageState(plan_of(PLAN), 0, None))
    assert (e.last_run, e.stuck_why, e.stats) == ("old", "old why", {"tests_added": 1, "tests_removed": 2, "rounds": 5})
