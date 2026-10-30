"""Engine tests: the checks round."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.engine_case import CLEAN, PLAN, WRITE, EngineTest, pid_gone

# isort: split
import os
import shlex
import signal
from pathlib import Path

from support.waits import until

from taskloop.adapters import gitrepo
from taskloop.app.run import (
    engine,
)
from taskloop.app.wire import slots as wslots
from taskloop.contracts.ids import BeadId
from taskloop.domain import outcome as oc


class EngineChecksTest(EngineTest):


    def sleeping_check(self, secs, counter):
        """A check that counts its runs in `counter` and would take `secs` seconds (the sim stops it at the wall limit, nothing sleeps)."""
        return procsim.fake(f"sleep-{secs}", procsim.takes(secs, then=procsim.appends(counter)))
    def test_a_stop_during_a_check_stops_the_check_and_everything_it_started(self):
        if os.name == "nt":
            self.skipTest("POSIX process groups")
        eng = engine.Engine(BeadId("t-1"), str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        pidfile = Path(self.wt, "child.pid")

        def stopped(*_):  # what the run's SIGTERM handler does, from the same thread, once the check has started its child
            until(lambda: pidfile.exists() and pidfile.read_text().strip(), 5)
            raise engine.Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
        old = signal.signal(signal.SIGALRM, stopped)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.setitimer(signal.ITIMER_REAL, 0.5)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)
        with self.assertRaises(engine.Blocked):
            eng.sh(shlex.split(self.spawn(pidfile)))
        child = int(pidfile.read_text())
        if not until(lambda: pid_gone(child), 2.5):
            os.kill(child, 9)
            self.fail("the check's child outlived the stop")
    def test_sigterm_during_a_stage_check_stops_its_tree_and_still_closes(self):
        pidfile = Path(self.tmp.name, "child.pid")
        check = self.spawn(pidfile, term=True)
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])])
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.said())
        self.assertDead(self.child_of(pidfile))
        self.assertIn("wip (t-1)", gitrepo.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))


