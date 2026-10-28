"""SIGTERM only sets the run's stop flag (Engine.halt); the check, the worker call and the waits end on it and the run stops at a safe
point. Real processes; the signal is raised by signal.raise_signal, never os.kill of our own pid."""
import json
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import test_engine as te  # noqa: E402
import tl  # noqa: E402
from taskloop.adapters import delegate, runner  # noqa: E402
from taskloop.adapters import halt as halting  # noqa: E402
from test_engine import CLEAN, PLAN, WRITE, engine, pyc  # noqa: E402


class Halt(unittest.TestCase):
    wt: Path
    tmp: Any
    eng: Any
    setUp: Any = te.EngineTest.setUp
    tearDown: Any = te.EngineTest.tearDown
    fake_bd: Any = te.EngineTest.fake_bd
    run_engine: Any = te.EngineTest.run_engine
    checks_engine: Any = te.EngineTest.checks_engine
    spawn: Any = te.EngineTest.spawn
    child_of: Any = te.EngineTest.child_of
    assertDead: Any = te.EngineTest.assertDead
    said: Any = te.EngineTest.said

    def test_sigterm_during_a_real_sleeping_check_ends_the_check_and_its_tree_and_the_run_closes_cleanly(self):
        pidfile = Path(self.tmp.name, "child.pid")
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.spawn(pidfile)])])
        waiter = threading.Thread(target=lambda: (self.child_of(pidfile), signal.raise_signal(signal.SIGTERM)), daemon=True)
        waiter.start()
        t = time.time()
        with halting.halt_on_sigterm():
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        waiter.join(5)
        self.assertLess(time.time() - t, 60)
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.said())
        self.assertDead(self.child_of(pidfile))
        rows = [json.loads(line) for line in self.eng.log_path.read_text().splitlines()]
        self.assertEqual([r["why"] for r in rows if r["kind"] == "kill"], ["stopped"])
        self.assertIn("wip (t-1)", tl.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))
        self.assertIsNone(halting.RUN_HALT["ev"])

    def test_a_wait_of_the_engine_ends_on_the_stop_flag_and_stops_the_run(self):
        eng = self.checks_engine()
        threading.Timer(0.3, eng.halt.set).start()
        t = time.time()
        with self.assertRaises(engine.Blocked) as cm:
            eng.halt_point(wait=30)
        self.assertLess(time.time() - t, 10)
        self.assertEqual(cm.exception.kind, engine.oc.Kind.PAUSE_KILLED)

    def test_a_worker_call_is_stopped_by_the_run_flag_and_its_process_is_gone(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        pidfile = d / "pid"
        r = runner.StreamRunner(d / "err.log", None, 60.0, "", None, grace=0.5)
        r.outer = threading.Event()
        threading.Timer(1.0, r.outer.set).start()
        t = time.time()
        with self.assertRaises(delegate.Stopped):
            r(["python3", "-c", "import os,time; open(%r,'w').write(str(os.getpid())); time.sleep(30)" % str(pidfile)])
        self.assertLess(time.time() - t, 20)
        self.assertEqual(r.obs["why"], "interrupted")
        te.until(lambda: te.pid_gone(int(pidfile.read_text())), 3)
        self.assertTrue(te.pid_gone(int(pidfile.read_text())))


if __name__ == "__main__":
    unittest.main()
