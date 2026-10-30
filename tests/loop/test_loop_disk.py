"""The loop's disk preflight and its prune at start. Split from test_loop."""
import io
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
from support import looptest
from loop.test_loop import Base, LoopBase, rec

from taskloop.app.launch import loop as wloop

GB = 1 << 30


class DiskPreflight(LoopBase):
    def free(self, gb):
        p = mock.patch.object(wloop, "free_bytes", return_value=int(gb * GB))  # the simulated free space of the config dir's disk
        p.start()
        self.addCleanup(p.stop)

    def test_below_the_threshold_the_loop_exits_0_without_claiming_a_bead_and_says_why(self):
        bd = self.beads({"x-1": [rec("landed")]})
        self.free(1)
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.started, [])
        self.assertFalse([c for c in bd.calls if c[0] == "update" and "--claim" in c and c[1] == "x-1"])
        self.assertIn("1.0 GB free", self.out)
        self.assertIn("loop.min_free_gb 5", self.out)
        self.assertEqual(looptest.last_exit(str(self.repo))["reason"], "low_disk")

    def test_the_threshold_is_a_config_key(self):
        (self.repo / ".task-loop.json").write_text('{"slots": {"count": 2}, "loop": {"min_free_gb": 0.5}}')
        self.beads({"x-1": [rec("landed")]})
        self.free(1)
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1"])

    def test_with_room_enough_the_loop_runs_the_bead(self):
        self.beads({"x-1": [rec("landed")]})
        self.free(50)
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual([b for b, _ in self.started], ["x-1"])

    def test_the_loop_prunes_once_at_its_start_before_any_bead(self):
        self.beads({"x-1": [rec("landed")]})
        self.free(50)
        with mock.patch.object(wloop.prune_verb, "run", side_effect=lambda *a, **k: self.assertEqual(self.started, [])) as run:
            self.run_loop()
        self.assertEqual(run.call_count, 1)
        self.assertFalse(run.call_args.args[5])  # not a dry run

    def test_a_prune_that_breaks_never_stops_the_loop(self):
        self.beads({"x-1": [rec("landed")]})
        self.free(50)
        with mock.patch.object(wloop.prune_verb, "run", side_effect=RuntimeError("boom")):
            self.assertEqual(self.run_loop(), 0)
        self.assertIn("prune failed: RuntimeError: boom", self.out)
        self.assertEqual([b for b, _ in self.started], ["x-1"])


class PruneVerb(Base):
    def test_tl_prune_dry_run_then_for_real_through_the_verb(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.fake()
        stem = "x-1-20200101-000000"
        run = Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop" / "runs" / stem
        (run / "evidence").mkdir(parents=True)
        (run / "evidence" / "a.png").write_bytes(b"P" * 100)
        old = time.time() - 40 * 86400
        for p in (run / "evidence" / "a.png", run / "evidence", run):
            os.utime(p, (old, old))
        outs = []
        for argv in (["--dry-run"], [], []):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(self.main(["prune", "--repo", str(self.repo), *argv]), 0)
            outs.append(out.getvalue())
            self.assertEqual(run.exists(), argv == ["--dry-run"])
        self.assertIn("would remove", outs[0])
        self.assertIn("removed", outs[1])
        self.assertIn("removed 0 item(s)", outs[2])


if __name__ == "__main__":
    unittest.main()
