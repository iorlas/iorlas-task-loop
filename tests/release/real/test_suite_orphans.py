"""No pytest worker outlives the launcher that started it: a wall limit, an interrupt and a dead launcher each end every process."""
import _thread
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import conftest
import stream_proc
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.waits import until

from taskloop.adapters import procs
from taskloop.app.release import suite

ROOT = Path(__file__).resolve().parents[3]
SLEEPER = """import os, time, unittest
class S(unittest.TestCase):
    def test_sleep(self):
        open(os.environ["PIDFILE"], "w").write(str(os.getpid()))
        time.sleep(300)
"""
class Orphans(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "test_sleep.py").write_text(SLEEPER)
        self.pidfile = self.root / "pid"
        tests = str(ROOT / "tests")
        self.env = dict(os.environ, PIDFILE=str(self.pidfile), PYTHONPATH=os.pathsep.join([tests, os.environ.get("PYTHONPATH", "")]))
        # -p conftest: the repo's own wiring (the worker leaves with its controller) in a tree that has none
        self.argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest", "-n", "1", "test_sleep.py"]
        self.pids: list[int] = []
        self.addCleanup(self.reap)

    def reap(self):
        for pid in self.pids:  # a failing test must not leave its sleeper behind
            if stream_proc.alive(pid):
                procs.stop_pid(pid)

    def worker_pid(self) -> int:
        text = until(lambda: self.pidfile.exists() and self.pidfile.read_text().strip(), 60)
        self.assertTrue(text, "the worker never started its test")
        pid = int(text or 0)
        self.pids.append(pid)
        return pid

    def run_in_thread(self, wall, argv):
        """suite.run_pytest as the launcher runs it, here in this process (no launcher interpreter) -> (the part, or the exception)."""
        with mock.patch.object(suite, "RUN_WALL_S", wall):
            return suite.run_pytest(argv, str(self.root), dict(self.env), "parallel")

    def test_a_run_past_its_wall_limit_is_stopped_and_red(self):
        sleeper = ["sh", "-c", 'echo $$ > "$PIDFILE"; sleep 300']  # the stand-in for a hung worker: a shell, not an interpreter
        part = self.run_in_thread(1.5, sleeper)  # room to start under load
        pid = self.worker_pid()
        self.assertEqual(part.code, 124)
        self.assertIn("its process tree was killed", part.out)
        self.assertFalse(stream_proc.alive(pid))

    def test_an_interrupted_launcher_stops_its_workers_before_it_exits(self):
        old = signal.signal(signal.SIGINT, signal.default_int_handler)  # a background shell starts a launcher with SIGINT ignored
        self.addCleanup(signal.signal, signal.SIGINT, old)

        def interrupt():  # once the worker is inside its test
            until(self.pidfile.exists, 60)
            _thread.interrupt_main()
        threading.Thread(target=interrupt, daemon=True).start()
        with self.assertRaises(KeyboardInterrupt):
            self.run_in_thread(600, ["sh", "-c", 'echo $$ > "$PIDFILE"; sleep 300'])  # the worker: a shell
        pid = self.worker_pid()
        self.assertTrue(until(lambda: not stream_proc.alive(pid), 15), "the worker outlived the interrupted launcher")

    def test_a_worker_whose_controller_died_without_a_word_exits_on_its_own(self):
        out = subprocess.DEVNULL
        controller = subprocess.Popen(self.argv, env=self.env, cwd=self.root, start_new_session=True, stdout=out, stderr=out)
        self.pids.append(controller.pid)
        self.assertTrue(until(self.pidfile.exists, 90), "the worker never started its test")  # the worker is inside its test
        controller.kill()  # the controller dies at once, no handler: the way a SIGKILLed pytest ends
        controller.wait()
        pid = self.worker_pid()
        self.assertTrue(until(lambda: not stream_proc.alive(pid), 15), "the orphaned worker is still running")


class MemoryLimits(unittest.TestCase):
    def test_a_worker_past_its_address_space_cap_is_red_with_a_memory_error(self):
        """conftest.cap_memory in a forked child (a worker, as xdist starts it, without the interpreter start): past the cap an allocation
        is a MemoryError, not the host's RAM."""
        pid = os.fork()
        if pid == 0:
            code = 3
            try:
                conftest.cap_memory(600)
                bytearray(900 << 20)
            except MemoryError:
                code = 0
            finally:
                os._exit(code)
        self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), 0, "the allocation past the cap was not a MemoryError")


if __name__ == "__main__":
    unittest.main()
