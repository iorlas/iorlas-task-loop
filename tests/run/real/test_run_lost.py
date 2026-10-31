"""RUNSTATE contract (tl-9un.48): an engine process killed with SIGKILL leaves a run that is `lost` after one reconcile, and every reader
shows lost: the dashboard's live page and run facts, `tl wait`, `tl report`'s crash scan, the owner-request gate. The reconcile marks it
once; a live engine, or the same state seen again, is never changed."""
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support import homes
from support.dashes import make_dash
from support.waits import until

from taskloop.app.report import card
from taskloop.app.run import requests
from taskloop.cli import wait
from taskloop.contracts import runlife
from taskloop.contracts.locator import RunLocator
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import STALE_AFTER, Liveness

CHILD = Path(te.ROOT, "tests", "support", "state_child.py")
WAIT = 120


class KilledEngine(te.EngineTest):
    @te.real_git("a child engine process is killed by its pid and the reconciler probes that pid")
    def test_a_killed_engine_is_lost_after_one_reconcile_and_every_reader_says_so(self):
        marker = Path(self.tmp.name, "marker")
        env = {**os.environ, "STATE_WT": str(self.wt), "PYTHONPATH": os.pathsep.join([str(te.ROOT / "tests"), str(te.ROOT / "src")])}
        child = subprocess.Popen([sys.executable, str(CHILD), str(marker)], env=env, cwd=str(te.ROOT), stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE)
        try:
            until(marker.exists, WAIT)
            pid, run = marker.read_text().split()
            self.assertEqual(int(pid), child.pid)
            cfg, where = homes.cfg(), RunLocator(homes.cfg())
            m = where.get(run).manifest  # type: ignore[union-attr]
            self.assertEqual((m.state, m.pid), (RunState.RUNNING, child.pid))
            later = m.heartbeat + STALE_AFTER + 1
            self.assertEqual(runlife.reconcile(cfg, later), [], "a stale heartbeat does not mark a process that lives")
            os.kill(child.pid, signal.SIGKILL)  # the pid of the child this test started
        finally:
            child.wait(WAIT)
        self.assertEqual(runlife.reconcile(cfg, m.heartbeat + 1), [], "a dead process with a fresh heartbeat may be a restart")
        shown = make_dash(config=cfg.root, clock=lambda: later).live.page("t-1")[1]["state"]
        self.assertEqual(shown, "lost", "the dashboard displays lost before anything wrote it")
        self.assertEqual(where.get(run).manifest.state, RunState.RUNNING)  # type: ignore[union-attr]
        self.assertEqual(runlife.reconcile(cfg, later), [run])
        got = where.get(run).manifest  # type: ignore[union-attr]
        self.assertEqual(got.state, RunState.LOST)
        self.assertIn(f"pid {child.pid}", got.reason)
        self.assertEqual(runlife.reconcile(cfg, later + 99), [], "once")
        # every reader reads the recorded state
        dash = make_dash(config=cfg.root, clock=lambda: later)
        self.assertEqual(dash.live.page("t-1")[1]["state"], "lost")
        bundle = where.get(run)
        assert bundle is not None
        self.assertIs(dash.runlogs.typed_run(bundle, later).life, Liveness.LOST)
        code, line = wait.verdict(cfg, run, later)  # type: ignore[misc]
        self.assertEqual(code, wait.CRASHED)
        self.assertIn("lost", line)
        crashes = card.crashes(str(m.repo), m.started - 1, later, [], cfg, now=later)
        self.assertEqual([c["run"] for c in crashes], [run])
        self.assertFalse(requests.live(cfg, run, later))


if __name__ == "__main__":
    unittest.main()
