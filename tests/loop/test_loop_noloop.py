"""The loop verbs: the engine loop's pick, run and stop."""
import io
from contextlib import redirect_stdout

import support.paths  # noqa: F401

from loop.test_loop import LoopBase


class LoopStopLogic(LoopBase):
    def test_stop_with_no_loop_running_says_so(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(self.main(["stop", "--repo", str(self.repo)]), 1)
        self.assertIn("no loop", out.getvalue())
