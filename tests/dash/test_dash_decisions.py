"""The drawer says why a bead was slow and why it switched lane: each Overrun and RetryDecision of its runs, with time and reason."""

from support.dashlogs import RunScript, T, bead

from taskloop_dash.views import bead_detail
from taskloop_dash.views.board import Board
from taskloop_dash.views.world import ProjectIn, World

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
