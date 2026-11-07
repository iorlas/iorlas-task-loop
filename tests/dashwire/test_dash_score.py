"""The overnight scorecard strip: the project carries the numbers `tl report` computes for the loop's window, from one port."""

from support.dashes import make_dash

from taskloop.app.report.card import score_of
from tldash.env import Ports
from tldash.testing import T, bead
from tldash.views.snapshot import build
from tldash.views.world import ProjectIn, World
from tlkernel.dashhealth import Score
from tlkernel.loop import LoopState

CARD = {"since": T, "until": T + 600, "beads": 9, "landed": 8, "landed_no_ask": 6, "asks": {"count": 3, "beads": 2}, "lost": 1,
        "crashes": 2, "m2": {"pass": False}}


def test_the_strip_numbers_are_the_scorecards_own():
    assert score_of(CARD) == Score(since=T, until=T + 600, beads=9, landed=8, landed_no_ask=6, asks=3, lost=1, crashes=2, m2_pass=False)


def test_the_snapshot_publishes_a_projects_score_and_none_without_a_port():
    score = score_of(CARD)
    p = ProjectIn(id="p", name="p", beads=[bead("p-1")], score=score)
    snap = build(World(now=T + 600, host="h", version="v", projects=[p, ProjectIn(id="q", name="q", beads=[])], runs={}, asks={}))
    assert [x.score for x in snap.projects] == [score, None]


def test_the_default_port_says_nothing():
    assert Ports().scorecard("/repo", T, T + 1) is None


def test_a_loops_window_starts_when_it_started(tmp_path):
    seen = []
    dash = make_dash(Ports(scorecard=lambda repo, since, until: seen.append((since, until))), config=str(tmp_path), clock=lambda: T + 900)
    state = LoopState(pid=1, started=T + 100, t=T + 800, repo="/r", version="v", code_dir="", actor="tl-loop")
    dash.reads.worlds.score("/r", [state])
    dash.reads.worlds.score("/r", [state])
    assert seen == [(T + 100, T + 900)]  # one build inside the minute
