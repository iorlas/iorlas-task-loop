"""The loop's disk preflight and its prune at start. Split from test_loop."""
import io
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# isort: split
from support import looptest

from loop.test_loop import Base, LoopBase, rec
from taskloop.app.launch import loop as wloop
from tlkernel.run import RunState
from tltestkit.runs import manifest

GB = 1 << 30


class DiskPreflight(LoopBase):
    def free(self, gb):
        p = mock.patch.object(wloop, "free_bytes", return_value=int(gb * GB))  # the simulated free space of the config dir's disk
        p.start()
        self.addCleanup(p.stop)

    def test_below_the_threshold_the_loop_waits_without_claiming_then_wakes(self):
        self.beads({"x-1": [rec("landed")]})

        def free(cfg):
            assert cfg.root == Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop"
            if self.clock.t < self.clock.t0 + 120:
                assert self.started == []
                return GB
            return 50 * GB

        with mock.patch.object(wloop, "free_bytes", side_effect=free):
            assert self.run_loop() == 0
        assert [b for b, _ in self.started] == ["x-1"]
        assert "WAIT low_disk" in self.out
        assert looptest.last_exit(str(self.repo))["reason"] == "drained"

    def test_the_threshold_is_a_config_key(self):
        (self.repo / ".task-loop.json").write_text('{"slots": {"count": 2}, "loop": {"min_free_gb": 0.5}}')
        self.beads({"x-1": [rec("landed")]})
        self.free(1)
        assert self.run_loop() == 0
        assert [b for b, _ in self.started] == ["x-1"]

    def test_with_room_enough_the_loop_runs_the_bead(self):
        self.beads({"x-1": [rec("landed")]})
        self.free(50)
        assert self.run_loop() == 0
        assert [b for b, _ in self.started] == ["x-1"]

    def test_the_loop_prunes_once_at_its_start_before_any_bead(self):
        self.beads({"x-1": [rec("landed")]})
        self.free(50)
        def prune(*a, **k):
            assert self.started == []
        with mock.patch.object(wloop.prune_verb, "run", side_effect=prune) as run:
            self.run_loop()
        assert run.call_count == 1
        assert not run.call_args.args[5]  # not a dry run
        assert callable(run.call_args.kwargs["live"])

    def test_a_prune_that_breaks_never_stops_the_loop(self):
        self.beads({"x-1": [rec("landed")]})
        self.free(50)
        with mock.patch.object(wloop.prune_verb, "run", side_effect=RuntimeError("boom")):
            assert self.run_loop() == 0
        assert "prune failed: RuntimeError: boom" in self.out
        assert [b for b, _ in self.started] == ["x-1"]


class PruneVerb(Base):
    def test_tl_prune_dry_run_then_for_real_through_the_verb(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.fake()
        stem = "x-1-20200101-000000"
        config = Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop"
        run = manifest(config, stem, "x-1", 0.0, state=RunState.DONE, ended=1.0).dir  # a live run is never pruned
        (run / "evidence").mkdir(parents=True)
        (run / "evidence" / "a.png").write_bytes(b"P" * 100)
        old = time.time() - 40 * 86400
        for p in (run / "evidence" / "a.png", run / "evidence", run):
            os.utime(p, (old, old))
        outs = []
        for argv in (["--dry-run"], [], []):
            out = io.StringIO()
            with redirect_stdout(out):
                assert self.main(["prune", "--repo", str(self.repo), *argv]) == 0
            outs.append(out.getvalue())
            assert run.exists() == (argv == ["--dry-run"])
        assert "would remove" in outs[0]
        assert "removed" in outs[1]
        assert "removed 0 item(s)" in outs[2]
