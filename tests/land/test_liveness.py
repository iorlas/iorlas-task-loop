"""Land retries and in-lock work have finite budgets without changing the gate."""
import unittest
from unittest import mock

import support.paths  # noqa: F401
from support.fake_deadline import FakeDeadline
from support.fakegit import FakeGit
from support.narrow_hosts import Stopped, table_kit

from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.state import Placing
from taskloop.domain.lanes.liveness import LIVENESS, LivenessCaps


class Liveness(unittest.TestCase):
    def kit(self):
        return table_kit(FakeGit(**{"rev_parse__origin/main": "base", "rev_parse__HEAD": "head",
                                    "rev_parse__HEAD^{tree}": "tree", "rebase": (0, "")}))

    def test_in_lock_stale_retries_park_at_the_cap_and_release_the_lock(self):
        kit = self.kit()
        stale = Problem(ProblemKind.STALE, "moved")
        with mock.patch.object(kit.lander, "optimistic", return_value=False), \
                mock.patch.object(kit.lander, "tries", side_effect=[("", stale)] * LIVENESS.stale_retries +
                                  [AssertionError("unbounded stale retry")]) as tries, self.assertRaises(Stopped) as stopped:
            kit.lander.land()
        self.assertEqual(stopped.exception.kind, "OWNER_PARK")
        self.assertIn("STALE", stopped.exception.why)
        self.assertEqual(tries.call_count, LIVENESS.stale_retries)
        self.assertEqual(kit.events[-1], "exit")

    def test_land_iterations_bound_fixable_outside_failures(self):
        kit = self.kit()
        problem = Problem(ProblemKind.GATE, "red")
        with mock.patch.object(kit.lander, "optimistic", return_value=True), \
                mock.patch.object(kit.lander, "outside", side_effect=[problem] * LIVENESS.land_iterations +
                                  [AssertionError("unbounded land")]) as outside, \
                mock.patch.object(kit.lander.fixing, "run"), self.assertRaises(Stopped) as stopped:
            kit.lander.land()
        self.assertEqual(stopped.exception.kind, "OWNER_PARK")
        self.assertEqual(outside.call_count, LIVENESS.land_iterations)

    def test_judge_hang_times_out_and_releases_land_lock(self):
        kit = self.kit()
        caps = LivenessCaps(judge_s=0.02)
        timer = FakeDeadline()
        with timer.patched(), mock.patch("taskloop.app.land.lander.LIVENESS", caps), \
                mock.patch.object(kit.lander, "optimistic", return_value=False), \
                mock.patch.object(kit.lander, "placing", return_value=Placing.INSIDE), \
                mock.patch.object(kit.lander.gate, "run", side_effect=lambda: timer.wait(0.5)), \
                self.assertRaises(Stopped) as stopped:
            kit.lander.land()
        self.assertEqual(stopped.exception.kind, "PAUSE_LANE")
        self.assertIn("deadline", stopped.exception.why)
        self.assertEqual(kit.events[-1], "exit")
