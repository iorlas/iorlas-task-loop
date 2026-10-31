"""Time, tokens and cost per stage and bead (views/cost.py) over recorded typed logs: a fixture of 7 calls in 3 runs.
Each grouping is one exact snapshot; an unknown cost is counted apart, never summed as 0."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashlogs import RunScript, T, bead

from taskloop.contracts.dashcost import CostRow
from taskloop_dash.views import cost
from taskloop_dash.views.world import ProjectIn, World

NOW = T + 20_000


def world(project="p", extra=()):
    one = (RunScript("b-1", "20261015-100000", at=0)
           .step("plan", 100, 1000, "OC", role="planner", cost=0.5, source="harness")
           .step("write", 400, 5000, "OC", cost=2.0, source="harness")
           .step("write", 200, 2000, "CL", cost=0.0, source="unknown")
           .step("checks", 60, 0)
           .add("wait_start", id="w1", what="resource").wait(15).add("wait_end", id="w1", wait_seconds=15.0)
           .step("review", 50, 700, "CL", role="reviewer", cost=0.0, source="free").close("landed"))
    two = RunScript("b-1", "20261015-150000", at=4000).step("write", 300, 3000, "OC", cost=1.0, source="harness").close("parked")
    three = (RunScript("b-2", "20261015-160000", at=5000).step("plan", 80, 400, "CL", role="planner").close("parked"))
    old = RunScript("b-3", "20261001-100000", at=-900_000).step("plan", 10, 10, "OC", cost=9.0, source="harness").close("landed")
    runs = {"b-1": [one.run(NOW), two.run(NOW)], "b-2": [three.run(NOW)], "b-3": [old.run(NOW)]}
    projects = [ProjectIn(id="p", name="p", beads=[bead("b-1"), bead("b-2")]), ProjectIn(id="q", name="q", beads=[bead("b-3"), *extra])]
    return World(now=NOW, host="h", version="v", projects=projects, runs=runs, asks={})


def view(rows):
    return [(r.key, r.secs, r.tokens, r.cost, r.calls, r.unknown) for r in rows]


class Cost(unittest.TestCase):
    def setUp(self):
        self.page = cost.build(world(), "24h")

    def test_by_stage(self):
        self.assertEqual(view(self.page.stages), [
            ("write", 900, 10000, 3.0, 3, 1), ("plan", 180, 1400, 0.5, 2, 1), ("test", 60, 0, 0.0, 0, 0), ("review", 50, 700, 0.0, 1, 0)])

    def test_by_bead_and_the_drill_down(self):
        self.assertEqual(view(self.page.beads), [("b-1", 1110, 11700, 3.5, 5, 1), ("b-2", 80, 400, 0.0, 1, 1)])
        self.assertEqual([(r.bead, r.key, r.secs, r.tokens) for r in self.page.drill if r.bead == "b-1"],
                         [("b-1", "write", 900, 10000), ("b-1", "plan", 100, 1000), ("b-1", "test", 60, 0), ("b-1", "review", 50, 700)])

    def test_waits(self):
        self.assertEqual(view(self.page.waits), [("resource", 15, 0, 0.0, 0, 0)])

    def test_the_window_and_the_project_and_the_last_runs(self):
        self.assertEqual(self.page.runs, 3)
        self.assertEqual(cost.build(world(), "7d").runs, 3)
        self.assertEqual(cost.build(world(), "24h", project="q").runs, 0)
        self.assertEqual([r.key for r in cost.build(world(), "24h", last=1).beads], ["b-2"])

    def test_unknown_cost_is_not_zero_dollars(self):
        row = next(r for r in self.page.stages if r.key == "plan")
        self.assertEqual((row.cost, row.unknown), (0.5, 1))
        self.assertIsInstance(row, CostRow)


if __name__ == "__main__":
    unittest.main()
