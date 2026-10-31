"""The v2 board's pure rules: column, marker, status line and dots over typed facts, one row per value."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import log
from taskloop.contracts.dash import Column, Marker, Phase
from taskloop.contracts.enums import Outcome, WaitWhat, WhyCode
from taskloop.contracts.runlife import Liveness
from taskloop_dash.views import columns
from taskloop_dash.views.columns import Facts

LIVE, CRASHED, ENDED = Liveness.LIVE, Liveness.CRASHED, Liveness.ENDED
PARKED = log.Close(t=1.0, outcome=Outcome.PARKED, why_code=WhyCode.LANE_OUT, why="codex ran out\nuntil 14:00")
FAILED = log.Close(t=1.0, outcome=Outcome.FAILED, why_code=WhyCode.FAILED)
LANDED = log.Close(t=1.0, outcome=Outcome.LANDED)

# (name, facts, column, marker)
ROWS = [
    ("blocked backlog", Facts(blocked=True, blocker="b-1"), Column.BACKLOG, Marker.BLOCKED),
    ("ready backlog", Facts(), Column.BACKLOG, Marker.READY),
    ("ready after a failed run", Facts(life=ENDED, close=FAILED), Column.BACKLOG, Marker.READY),
    ("parked by a lane running out", Facts(life=ENDED, close=PARKED), Column.BACKLOG, Marker.PARKED),
    ("claimed, no run", Facts(claimed=True), Column.WORKING, Marker.RUN),
    ("planning", Facts(claimed=True, life=LIVE, phase=Phase.PLAN), Column.WORKING, Marker.RUN),
    ("writing", Facts(claimed=True, life=LIVE, phase=Phase.WRITE), Column.WORKING, Marker.RUN),
    ("checking", Facts(claimed=True, life=LIVE, phase=Phase.TEST), Column.WORKING, Marker.RUN),
    ("a step with no phase (reset)", Facts(claimed=True, life=LIVE, phase=None), Column.WORKING, Marker.RUN),
    ("reviewing", Facts(claimed=True, life=LIVE, phase=Phase.REVIEW), Column.REVIEW, Marker.RUN),
    ("in the look step", Facts(claimed=True, life=LIVE, phase=Phase.LOOK), Column.LOOK, Marker.RUN),
    ("landing", Facts(claimed=True, life=LIVE, phase=Phase.LAND), Column.LANDING, Marker.RUN),
    ("run died in write, still claimed", Facts(claimed=True, life=CRASHED, phase=Phase.WRITE), Column.WORKING, Marker.EXITED),
    ("run died in review, still claimed", Facts(claimed=True, life=CRASHED, phase=Phase.REVIEW), Column.WORKING, Marker.EXITED),
    ("run died, not claimed", Facts(life=CRASHED, phase=Phase.LAND), Column.BACKLOG, Marker.EXITED),
    ("open ask", Facts(ask=True), Column.QUESTIONS, Marker.ASK),
    ("open ask beats a live run", Facts(ask=True, claimed=True, life=LIVE, phase=Phase.WRITE), Column.QUESTIONS, Marker.ASK),
    ("open look", Facts(look=True), Column.LOOK, Marker.LOOK),
    ("open look on a closed bead", Facts(look=True, closed=True), Column.LOOK, Marker.LOOK),
    ("ask beats look", Facts(ask=True, look=True), Column.QUESTIONS, Marker.ASK),
    ("closed", Facts(closed=True, life=ENDED, close=LANDED), Column.DONE, Marker.DONE),
]


class ColumnAndMarker(unittest.TestCase):
    def test_every_row(self):
        for name, f, col, mark in ROWS:
            with self.subTest(name):
                self.assertEqual((columns.column(f), columns.marker(f)), (col, mark))

    def test_every_column_and_every_derivable_marker_is_covered(self):
        self.assertEqual({r[2] for r in ROWS}, set(Column))
        # stuck and soft_ask wait for their facts (backend items 5 and 6): no rule makes them yet
        self.assertEqual({r[3] for r in ROWS}, set(Marker) - {Marker.STUCK, Marker.SOFT_ASK})


class Status(unittest.TestCase):
    def test_lines(self):
        wait = log.WaitStart(t=1.0, id="w1", what=WaitWhat.LAND_LOCK)
        rows = [
            (Facts(ask=True, ask_line="Which bills are weekly?\nmore"), "Which bills are weekly?"),
            (Facts(ask=True), "waiting for your answer"),
            (Facts(look=True), "waiting for your look"),
            (Facts(closed=True, closed_reason="landed abc123"), "landed abc123"),
            (Facts(closed=True), "closed"),
            (Facts(life=LIVE, claimed=True, step_text="write 2: fix weather_tick", phase=Phase.WRITE), "write 2: fix weather_tick"),
            (Facts(life=LIVE, claimed=True, phase=Phase.TEST), "test"),
            (Facts(life=LIVE, claimed=True), "running"),
            (Facts(life=LIVE, claimed=True, wait=wait), "waiting for land lock"),
            (Facts(life=CRASHED, claimed=True), "the run stopped writing records"),
            (Facts(claimed=True, assignee="tl-a"), "claimed by tl-a"),
            (Facts(life=ENDED, close=PARKED), "codex ran out"),
            (Facts(blocked=True, blocker="b-1"), "waits for b-1"),
            (Facts(), "ready"),
        ]
        for f, want in rows:
            with self.subTest(want):
                self.assertEqual(columns.status_line(f), want)


class Dots(unittest.TestCase):
    def dots(self, visited, current, marker, closed=False):
        return [(d.phase.value, d.state) for d in columns.dots_of(visited, current, marker, closed)]

    def test_a_bead_without_passes_has_no_dots(self):
        self.assertEqual(columns.dots_of(set(), None, Marker.READY, False), [])

    def test_the_current_phase_shows_what_the_bead_is_doing(self):
        seen = {Phase.PLAN, Phase.WRITE}
        self.assertEqual(self.dots(seen, Phase.WRITE, Marker.RUN)[:3], [("plan", "done"), ("write", "live"), ("test", "todo")])
        self.assertEqual(self.dots(seen, Phase.WRITE, Marker.ASK)[1], ("write", "you"))
        self.assertEqual(self.dots(seen, Phase.WRITE, Marker.EXITED)[1], ("write", "bad"))
        self.assertEqual(self.dots(seen, Phase.WRITE, Marker.PARKED)[1], ("write", "done"))

    def test_a_closed_bead_is_all_done(self):
        self.assertEqual({s for _, s in self.dots({Phase.PLAN}, Phase.LAND, Marker.DONE, True)}, {"done"})


if __name__ == "__main__":
    unittest.main()
