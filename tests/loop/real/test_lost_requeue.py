"""A restarted loop closes the runs found lost with a reason and takes their bead again, with no owner action (tl-9un.63)."""
from unittest import mock

import support.paths  # noqa: F401
from support import homes
from support.runs import manifest

from loop.test_loop import LoopBase, rec
from taskloop.app.loop.core import Core
from tlkernel.locator import RunLocator, host_name
from tlkernel.run import RunState
from tlkernel.runlife import STALE_AFTER

NOBODY = 4_194_303  # a pid no process has


class LostRun(LoopBase):
    def test_a_run_whose_process_is_gone_is_closed_lost_and_its_bead_is_taken_again(self):
        self.beads({"x-1": [rec("landed")]})
        run = "x-1-20261026-100000"
        began = self.clock.t - 3 * STALE_AFTER
        manifest(homes.cfg(), run, "x-1", began, repo=str(self.repo), state=RunState.RUNNING, pid=NOBODY, heartbeat=began + 5,
                 host=host_name())
        real_nap = self.clock.nap

        def capped(secs, *a, **kw):
            assert len(self.clock.naps) < 20, f"the loop idles instead of ending: {self.out}"
            real_nap(secs, *a, **kw)
        self.clock.nap = capped
        with mock.patch.object(Core, "nap", capped):
            self.run_loop("--max-beads", "1")
        assert f"run {run} is lost" in self.out
        got = RunLocator(homes.cfg()).get(run)
        assert got is not None and got.manifest.state is RunState.LOST and "is gone" in got.manifest.reason
        assert [b for b, _ in self.started] == ["x-1"]
