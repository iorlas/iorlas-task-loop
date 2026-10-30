"""A hold on a bead keeps the loop off it until it ends or is released, end to end through `tl loop` on a fake clock: no sleeping."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from loop.test_loop import LoopBase, rec

from taskloop.app.asks import intake
from taskloop.app.loop.core import Core

HOUR = 3600


class HoldEndToEnd(LoopBase):
    """The loop waits out a held bead (it is not drained), so each test fakes the loop's nap: it moves the fake clock and runs what the
    test says should happen meanwhile. The real sleep is never reached."""

    def put_hold(self, bead, **meta):
        self.bd.beads[bead]["metadata"] = {intake.HOLD: "denis", **{k: str(v) for k, v in meta.items()}}

    def loop_with(self, meanwhile):
        naps = []

        def nap(secs, until=0):
            naps.append(secs)
            self.clock.t += secs
            meanwhile(len(naps))
            if "x-1" in [b for b, _ in self.started]:  # what the test waited for has happened: the loop ends after this bead
                with redirect_stdout(io.StringIO()):
                    self.main(["stop", "--repo", str(self.repo)])
            if len(naps) > 50:
                self.fail("the loop is still waiting after 50 naps")
        with mock.patch.object(Core, "nap", staticmethod(nap)):
            self.assertEqual(self.run_loop("--wait-drained"), 0)  # without it a loop with only held beads left is drained and ends
        return naps

    def test_a_hold_with_an_end_keeps_the_loop_off_the_bead_until_the_clock_passes_it(self):
        self.beads({"x-1": [rec("landed")], "x-2": [rec("landed")]})
        until = int(self.clock.t) + HOUR
        self.put_hold("x-1", **{intake.HOLD_UNTIL: until})
        at_pick = {}

        def meanwhile(n):
            at_pick.setdefault(tuple(b for b, _ in self.started), self.clock.t)  # the clock when each set of started beads was seen
        naps = self.loop_with(meanwhile)
        self.assertEqual([b for b, _ in self.started], ["x-2", "x-1"])  # the held bead waited; the one behind it did not
        self.assertEqual(at_pick[("x-2",)] < until, True)  # while the hold stood, only x-2 had run
        self.assertGreaterEqual(self.clock.t, until)  # x-1 ran only after the clock passed the end of the hold
        self.assertTrue(naps)

    def test_a_hold_without_an_end_lasts_until_it_is_released(self):
        self.beads({"x-1": [rec("landed")]})
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.main(["hold", "x-1"]), 0)  # the owner's own verb, through bd

        def meanwhile(n):
            if n == 10:
                self.clock.t += 365 * 24 * HOUR  # a year: a hold with no end has not ended
            if n == 12:
                self.assertEqual(self.started, [])
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(self.main(["hold", "x-1", "--release"]), 0)
        self.loop_with(meanwhile)
        self.assertEqual([b for b, _ in self.started], ["x-1"])  # picked only after the release
        self.assertNotIn(intake.HOLD, self.bd.beads["x-1"].get("metadata", {}))


if __name__ == "__main__":
    unittest.main()
