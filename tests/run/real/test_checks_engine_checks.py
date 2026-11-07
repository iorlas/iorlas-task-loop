"""Whole beads through the Engine, moved out of tests/checks/test_engine_checks.py (they run the pipeline, not only the checks stage)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq, procsim
from support.engine_case import EngineTest
from support.plans import CLEAN, PLAN, WRITE
from support.world import pid_gone

# isort: split
import os
import shlex
import threading
from pathlib import Path

from support.spawn import port_git, real_spawner
from support.waits import until
from support.who import who

from taskloop.adapters import halt as halting
from taskloop.app.run import (
    engine,
)
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId


class EngineChecksTest(EngineTest):
    def sleeping_check(self, secs, counter):
        """A check that counts its runs in `counter` and would take `secs` seconds (the sim stops it at the wall limit, nothing sleeps)."""
        return procsim.fake(f"sleep-{secs}", procsim.takes(secs, then=procsim.appends(counter)))

    def test_a_stop_during_a_check_stops_the_check_and_everything_it_started(self):
        if os.name == "nt":
            pytest.skip("POSIX process groups")
        pidfile = Path(self.wt, "child.pid")
        with self.stoppable():  # the run's own halt event; the stop is delivered once the check has started its child
            eng = engine.Engine(
                BeadId("t-1"),
                str(self.wt),
                wslots.load_cfg(str(self.wt), port_git()),
                store=self.store,
                env=snapshot(),
                spawner=real_spawner(),
                git=port_git(), who=who())
            halt = halting.RUN_HALT["ev"]
            assert halt is not None

            def stop_when_started():
                until(lambda: pidfile.exists() and pidfile.read_text().strip(), 30)
                halt.set()  # what the run's SIGTERM handler does
            stopper = threading.Thread(target=stop_when_started, daemon=True)
            stopper.start()
            with pytest.raises(engine.Blocked):
                eng.sh(shlex.split(self.spawn(pidfile)))
            stopper.join(5)
        child = int(pidfile.read_text())
        if not until(lambda: pid_gone(child), 2.5):
            os.kill(child, 9)
            pytest.fail("the check's child outlived the stop")

    def test_sigterm_during_a_stage_check_stops_its_tree_and_still_closes(self):
        pidfile = Path(self.tmp.name, "child.pid")
        check = self.spawn(pidfile, term=True)
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])])
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        assert rc == 2
        assert "stopped (SIGTERM)" in self.said()
        self.assertDead(self.child_of(pidfile))
        assert "wip (t-1)" in gitq.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt))
