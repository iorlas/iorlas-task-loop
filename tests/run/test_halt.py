"""SIGTERM only sets the run's stop flag (Engine.halt); the check, the worker call and the waits end on it and the run stops at a safe
point. Real processes; the signal is raised by signal.raise_signal, never os.kill of our own pid."""
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from support import engine_case as te
from support.engine_case import engine

from taskloop.domain import outcome as oc


class Halt(te.EngineTest):
    wt: Path
    tmp: Any
    eng: Any


    def test_a_wait_of_the_engine_ends_on_the_stop_flag_and_stops_the_run(self):
        eng = self.checks_engine()
        threading.Timer(0.3, eng.halt.set).start()
        t = time.time()
        with self.assertRaises(engine.Blocked) as cm:
            eng.halt_point(wait=30)
        self.assertLess(time.time() - t, 10)
        self.assertEqual(cm.exception.kind, oc.Kind.PAUSE_KILLED)


if __name__ == "__main__":
    unittest.main()
