"""RUNSTATE contract (tl-9un.48): an engine process killed with SIGKILL leaves a run that is `lost` after one reconcile, and every reader
shows lost: the dashboard's live page and run facts, `tl wait`, `tl report`'s crash scan, the owner-request gate. The reconcile marks it
once; a live engine, or the same state seen again, is never changed."""
import os
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support import homes
from support.dashes import make_dash
from support.factory_index import ingest
from support.narrow import must
from support.waits import until

from taskloop.app.asks import owner_verbs as requests
from taskloop.app.report import card
from taskloop.cli import wait
from tlkernel import runlife
from tlkernel.ids import loop_key
from tlkernel.locator import RunLocator
from tlkernel.run import RunState
from tlkernel.runlife import STALE_AFTER, Liveness

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
            assert int(pid) == child.pid
            cfg, where = homes.cfg(), RunLocator(homes.cfg())
            m = must(where.get(run)).manifest
            assert (m.state, m.pid) == (RunState.RUNNING, child.pid)
            later = m.heartbeat + STALE_AFTER + 1
            assert runlife.reconcile(cfg, later) == [], "a stale heartbeat does not mark a process that lives"
            os.kill(child.pid, signal.SIGKILL)  # the pid of the child this test started
        finally:
            child.wait(WAIT)
        assert runlife.reconcile(cfg, m.heartbeat + 1) == [], "a dead process with a fresh heartbeat may be a restart"
        ingest(cfg, later)
        shown = make_dash(config=cfg.root, clock=lambda: later).live.page(loop_key(m.repo), "t-1")[1]["state"]
        assert shown == "lost", "the dashboard displays lost before anything wrote it"
        assert must(where.get(run)).manifest.state == RunState.RUNNING
        assert runlife.reconcile(cfg, later) == [run]
        got = must(where.get(run)).manifest
        assert got.state == RunState.LOST
        assert f"pid {child.pid}" in got.reason
        assert runlife.reconcile(cfg, later + 99) == [], "once"
        # every reader reads the recorded state
        ingest(cfg, later)
        dash = make_dash(config=cfg.root, clock=lambda: later)
        assert dash.live.page(loop_key(m.repo), "t-1")[1]["state"] == "lost"
        indexed, = dash.reads.worlds.runs()[(loop_key(m.repo), "t-1")]
        assert indexed.name == run
        assert indexed.life is Liveness.LOST
        code, line = must(wait.verdict(cfg, run, later))
        assert code == wait.CRASHED
        assert "lost" in line
        crashes = card.crashes(str(m.repo), m.started - 1, later, [], cfg, now=later)
        assert [c["run"] for c in crashes] == [run]
        assert not requests.live(cfg, run, later)
