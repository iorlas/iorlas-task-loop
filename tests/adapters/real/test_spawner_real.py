"""adapters/spawner.py on real processes: capture, the timeout, a child that outlives the call, and the wait that times out."""
import os
import sys
import unittest
from unittest import mock

import support.paths  # noqa: F401

# isort: split
from taskloop.adapters.spawner import RealSpawner
from taskloop.contracts.ports import WaitTimeout


class RealSpawn(unittest.TestCase):
    def test_run_captures_text_and_the_exit_code(self):
        r = RealSpawner().run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"])
        self.assertEqual((r.exit, r.out.strip(), r.err.strip()), (3, "out", "err"))

    def test_a_timeout_is_exit_124(self):
        r = RealSpawner().run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.3)
        self.assertEqual((r.exit, r.timed_out), (124, True))

    def test_a_missing_program_is_an_oserror(self):
        with self.assertRaises(OSError):
            RealSpawner().run(["/no/such/program"])

    def test_the_virtualenv_does_not_reach_the_child(self):
        with mock.patch.dict(os.environ, {"VIRTUAL_ENV": "/v"}):
            r = RealSpawner().run([sys.executable, "-c", "import os; print(os.environ.get('VIRTUAL_ENV', 'none'))"])
        self.assertEqual(r.out.strip(), "none")

    def test_a_started_child_waits_times_out_and_stops(self):
        child = RealSpawner().start([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            with self.assertRaises(WaitTimeout):
                child.wait(0.2)
            self.assertIsNone(child.poll())
        finally:
            child.stop(0.5)
        self.assertIsNotNone(child.poll())


if __name__ == "__main__":
    unittest.main()
