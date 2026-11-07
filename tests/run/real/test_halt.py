"""SIGTERM only sets the run's stop flag (Engine.halt); the check, the worker call and the waits end on it and the run stops at a safe
point. Real processes; the signal is raised by signal.raise_signal, never os.kill of our own pid."""
import json
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tltestkit.tmpdir import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# isort: split
from support import engine_case as te
from support import gitq
from support.fake_api import FakeApi

from taskloop.adapters import delegate, runner
from taskloop.adapters import halt as halting
from tltestkit.plans import CLEAN, PLAN, WRITE

WAIT = 120  # the longest a helper waits for a started process on a loaded runner (it ends the moment the process is there)


class Halt(te.EngineTest):
    wt: Path
    tmp: Any
    eng: Any
    def test_sigterm_during_a_real_sleeping_check_ends_the_check_and_its_tree_and_the_run_closes_cleanly(self):
        pidfile = Path(self.tmp.name, "child.pid")
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.spawn(pidfile)])])
        # the signal goes when the check's child exists, however late a loaded runner starts it (a 5 s give-up left it unsignalled)
        sent = []  # when the signal went: the bound is on the stop, not on the steps before it
        waiter = threading.Thread(daemon=True, target=lambda: (
            self.child_of(pidfile, WAIT), sent.append(time.time()), signal.raise_signal(signal.SIGTERM)))
        waiter.start()
        with halting.halt_on_sigterm():
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        waiter.join(5)
        assert not waiter.is_alive()
        assert time.time() - sent[0] < 60  # the check's child sleeps 30 s
        assert rc == 2
        assert "stopped (SIGTERM)" in self.said()
        self.assertDead(self.child_of(pidfile))
        rows = [json.loads(line) for line in self.eng.log_path.read_text().splitlines()]
        assert [r["why"] for r in rows if r["kind"] == "kill"] == ["stopped"]
        assert "wip (t-1)" in gitq.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt))
        assert halting.RUN_HALT["ev"] is None
    def test_a_worker_call_is_stopped_by_the_run_flag_and_its_process_is_gone(self):
        d = Path(mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        pidfile = d / "w.pid"
        fake = FakeApi(d, "sleep 30")
        r = runner.ApiRunner(d / "err.log", 60.0, "", None, grace=0.5)
        r.outer = threading.Event()
        request = runner.api.RunRequest(role="worker", brief_file="b.md", cwd=str(d))
        # the flag goes when the call's process has written its pid (a fixed delay can beat a loaded runner's start)
        threading.Thread(target=lambda: (te.until(pidfile.exists, WAIT), te.until(lambda: pidfile.read_text().strip(), WAIT),
                                         r.outer.set()), daemon=True).start()
        t = time.time()
        with fake.patch(), pytest.raises(delegate.Stopped):
            r(["delegate"], request=request)
        assert time.time() - t < 20
        assert r.obs["why"] == "interrupted"
        te.until(lambda: te.pid_gone(int(pidfile.read_text())), 3)
        assert te.pid_gone(int(pidfile.read_text()))
