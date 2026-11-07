"""The drawer says why a bead was slow and why it switched lane: each Overrun and RetryDecision of its runs, with time and reason."""

from tldash.testing import RunScript, T, bead
from tldash.views import bead_detail
from tldash.views.board import Board
from tldash.views.names import hhmm
from tldash.views.world import ProjectIn, World

NOW = T + 600


def detail(script):
    b = bead("p-1", "Slow", "in_progress")
    w = World(now=NOW, host="host", version="test", projects=[ProjectIn(id="p", name="p", beads=[b])],
              runs={("p", "p-1"): [script.run(NOW)]}, asks={})
    return bead_detail.build(Board(w), w.projects[0], b, [], [])


def test_overrun_and_retry_decisions_are_listed_oldest_first_with_time_and_reason():
    s = (RunScript("p-1").step("review", 100, 10, end=False).wait(60)
         .add("overrun", stage="review", budget_s=120.0, elapsed_s=121.4, lane="codex").wait(5)
         .add("retry_decision", step="review", plan="lane_poll", action="reroute", attempt=2, reason="codex out of quota",
              lane="codex"))
    got = detail(s).decisions
    assert [(m.t, m.who, m.icon) for m in got] == [(T + 160, "engine", "⏱"), (T + 165, "engine", "↪")]
    assert "review" in got[0].md and "120" in got[0].md and "121" in got[0].md
    assert "reroute" in got[1].md and "codex out of quota" in got[1].md and "attempt 2" in got[1].md


def test_a_bead_with_neither_has_no_decisions():
    assert detail(RunScript("p-1").step("write", 10, 1)).decisions == []


def test_a_vendor_error_says_the_lane_the_reason_and_until_when_it_is_closed_to_us():
    s = (RunScript("p-1").step("review", 100, 10, end=False).wait(10)
         .add("vendor_error", node="n1", reason="quota", lane="codex", until=T + 7200.0).wait(5)
         .add("vendor_error", node="n1", reason="overloaded", lane="claude"))
    got = detail(s).decisions
    assert [(m.who, m.icon) for m in got] == [("engine", "⛔"), ("engine", "⛔")]
    assert "codex" in got[0].md and "quota" in got[0].md and f"until {hhmm(T + 7200.0)}" in got[0].md
    assert "claude" in got[1].md and "overloaded" in got[1].md and "until" not in got[1].md


def test_a_land_try_says_its_phase_seconds_and_why_it_went_on_or_retried():
    s = (RunScript("p-1").step("land", 100, 10, end=False).wait(5)
         .add("land_try", n=1, failing="gate", gate="outside", fetch_s=2.0, rebase_s=1.0, gate_s=84.0, rebase_moved=True).wait(5)
         .add("land_try", n=2, failing="", gate="cached", fetch_s=1.0, rebase_s=0.0, gate_s=0.0))
    got = detail(s).decisions
    assert [(m.icon, m.who) for m in got] == [("🛬", "engine"), ("🛬", "engine")]
    assert "try 1" in got[0].md and "gate red" in got[0].md and "fetch 2 s" in got[0].md and "gate 84 s" in got[0].md
    assert "try 2" in got[1].md and "pushing" in got[1].md and "fetch 1 s" in got[1].md
