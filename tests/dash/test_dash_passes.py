"""Passes, cells and pieces of one bead, from recorded typed logs; the 3-pass bead is the shape of the mock's 7hv.2."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import RunScript, T
from support.narrow import must

from taskloop_dash.views import passes

NOW = T + 20_000


def comeback() -> list:
    """Run 1 on slot a: plan, write, a red check, a fix write, then the codex lane runs out. Run 2 on slot b: write, checks, review,
    land."""
    one = (
        RunScript("tl-7", "20261015-100000", slot="a", at=0)
        .step("reset", 5)
        .step("plan", 840, 133_000, "OC Go")
        .step("write", 2760, 437_000)
        .step("checks", 480, 76_000, outcome="red")
        .move("write", "bad_checks")
        .step("write", 1560, 247_000)
        .close("parked", "lane_out", "codex out until 14:00")
    )
    two = (
        RunScript("tl-7", "20261015-160000", slot="b", at=7_200, prev_run=one.name)
        .step("write", 590, 50_000, "OC Go")
        .step("checks", 300, 10_000)
        .step("review", 400, 20_000)
        .step("verify", 100, 1_000)
        .step("gate", 60)
        .step("land", 20)
        .close("landed")
    )
    return [one.run(NOW), two.run(NOW)]


class Passes(unittest.TestCase):
    def setUp(self):
        self.runs = comeback()
        self.ps = passes.passes_of(self.runs)

    def test_three_passes_with_how_each_ended(self):
        self.assertEqual([(p.n, p.end) for p in self.ps], [(1, "test_failed"), (2, "lane_out"), (3, "done")])
        self.assertEqual(self.ps[0].text, "test failed: back to write")
        self.assertEqual(self.ps[1].text, "codex out until 14:00")  # the engine's own line wins over the table
        self.assertEqual(self.ps[2].text, "landed")

    def test_the_cells_carry_minutes_tokens_and_a_state(self):
        by = {c.phase.value: (c.state, c.secs, c.tokens) for c in passes.cells_of(self.ps[0])}
        self.assertEqual(by["plan"], ("visited", 840, 133_000))
        self.assertEqual(by["write"], ("visited", 2760, 437_000))
        self.assertEqual(by["test"], ("failed", 480, 76_000))
        self.assertEqual(by["review"][0], "empty")
        second = {c.phase.value: c.state for c in passes.cells_of(self.ps[1])}
        self.assertEqual(second["plan"], "skipped")  # a stage the pass went past without visiting
        self.assertEqual(second["write"], "visited")
        third = {c.phase.value: (c.state, c.secs) for c in passes.cells_of(self.ps[2])}
        self.assertEqual(third["write"], ("small", 590))  # under 10 min and under 100k
        self.assertEqual(third["review"], ("small", 500))  # review and verify are one phase
        self.assertEqual(third["land"], ("small", 80))  # gate and land are one phase
        self.assertEqual(third["plan"][0], "skipped")

    def test_the_resumed_pass_says_where_and_how_long_it_waited(self):
        self.assertIsNone(self.ps[0].resumed)
        self.assertIsNone(self.ps[1].resumed)
        got = must(self.ps[2].resumed)
        self.assertEqual((got.slot, got.branch), ("b", ""))
        self.assertEqual(got.waited_secs, int(self.runs[1].t0 - self.runs[0].last_t))

    def test_two_pieces_one_per_slot_linked_as_a_comeback(self):
        pieces = passes.pieces_of("lifesim", "tl-7", self.runs, self.ps)
        self.assertEqual(
            [(p.n, p.slot, p.from_slot, p.to_slot, p.landed) for p in pieces], [(0, "a", None, "b", False), (1, "b", "a", None, True)]
        )
        self.assertEqual(
            [(s.label, s.kind) for s in pieces[0].segs],
            [("plan", "stage"), ("write", "stage"), ("test", "failed"), ("write", "stage"), ("lane ran out, parked", "parked")],
        )
        self.assertEqual(
            [(s.label, s.kind) for s in pieces[1].segs], [("write", "stage"), ("test", "stage"), ("review", "stage"), ("land", "stage")]
        )
        parked = pieces[0].segs[-1]
        self.assertEqual((parked.t0, parked.t1), (self.runs[0].close.t, self.runs[1].t0))  # the wait for a slot ends where run 2 starts
        for p in pieces:
            for s in p.segs:
                self.assertLessEqual(s.t0, s.t1)

    def test_runs_on_one_slot_are_one_piece(self):
        one = RunScript("tl-8", slot="a").step("write", 100, 1).close("parked", "needs_human")
        two = RunScript("tl-8", "20261015-130000", slot="a", at=3_000, prev_run="x").step("write", 100, 1).close("landed")
        runs = [one.run(NOW), two.run(NOW)]
        ps = passes.passes_of(runs)
        pieces = passes.pieces_of("p", "tl-8", runs, ps)
        self.assertEqual(len(pieces), 1)
        self.assertEqual([s.kind for s in pieces[0].segs], ["stage", "answered", "stage"])  # the ask the owner answered, between them
        self.assertIsNone(ps[1].resumed)  # waiting for the owner is not waiting for a slot
        self.assertEqual([p.end for p in ps], ["asked", "done"])


class OpenRuns(unittest.TestCase):
    def test_a_live_run_has_a_live_pass_and_a_live_segment(self):
        s = RunScript("tl-9").step("plan", 300, 1_000).step("write", 400, 5_000, end=False).beat()
        run = s.run(s.t + 10)
        (p,) = passes.passes_of([run])
        self.assertEqual((p.end, p.live), ("", True))
        cells = {c.phase.value: (c.state, c.secs) for c in passes.cells_of(p)}
        self.assertEqual(cells["write"], ("live", 400))  # an open step counts to the run's last record, not to the clock
        (piece,) = passes.pieces_of("p", "tl-9", [run], [p])
        self.assertEqual(piece.segs[-1].kind, "live")

    def test_a_run_that_died_ends_no_pass_by_guess(self):
        s = RunScript("tl-9").step("write", 400, 5_000, end=False)
        run = s.run(s.t + 1000)  # silent for longer than the runlife limit
        (p,) = passes.passes_of([run])
        self.assertEqual((p.end, p.live), ("", False))  # exited stays unset until the Stuck fact

    def test_stuck_and_failed_closes_name_no_ending(self):
        for why in ("stuck", "failed", "hung"):
            s = RunScript("tl-9").step("write", 400, 5_000).close("failed", why)
            self.assertEqual(passes.passes_of([s.run(NOW)])[0].end, "", why)

    def test_a_replan_pass_after_a_send_back(self):
        s = (
            RunScript("tl-9")
            .step("plan", 60)
            .step("write", 60)
            .step("review", 60)
            .move("replan", "plan_sent_back")
            .step("replan", 60)
            .step("write", 60)
            .close("landed")
        )
        self.assertEqual([p.end for p in passes.passes_of([s.run(NOW)])], ["replan", "done"])

    def test_a_run_with_no_drawn_step_makes_no_pass(self):
        s = RunScript("tl-9").step("reset", 5).close("failed", "failed")
        self.assertEqual(passes.passes_of([s.run(NOW)]), [])


if __name__ == "__main__":
    unittest.main()
