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

import stream_proc
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.procsim import real_proc
from support.waits import until

from taskloop.adapters import landlock, procs
from taskloop.app.release import suite
from taskloop.app.release.shell import Abort

pytestmark = real_proc("the suite runner leaves no orphan: real pytest and worker processes are started and reaped")
ROOT = Path(__file__).resolve().parent.parent
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
            self.run_in_thread(600, self.argv)
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


class OneSuitePerHost(unittest.TestCase):
    def test_a_second_suite_waits_for_the_first_and_says_who_holds_it(self):
        said, ran = [], threading.Event()
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / "suite-host.lock"
            with mock.patch.object(suite, "suite_lock_path", return_value=lock), mock.patch.object(suite, "say", said.append), \
                    mock.patch.object(suite, "_host_suite", side_effect=lambda *a: ran.set()):
                with landlock.os_lock(lock, "pid 1 since 10:00:00: the first suite"):
                    t = threading.Thread(target=suite.host_suite, args=(ROOT, ROOT))
                    t.start()
                    self.assertTrue(until(lambda: any("held by pid 1 since 10:00:00: the first suite" in m for m in said), 15))
                    self.assertFalse(ran.is_set())
                t.join(30)
                self.assertTrue(ran.is_set())
        self.assertTrue(any("waiting for the suite lock" in m for m in said))


class MemoryLimits(unittest.TestCase):
    def test_a_worker_past_its_address_space_cap_is_red_with_a_memory_error(self):
        with tempfile.TemporaryDirectory() as d:
            hog = "import unittest\nclass H(unittest.TestCase):\n    def test_1(self): bytearray(900 << 20)\n"
            (Path(d) / "test_hog.py").write_text(hog)
            path = os.pathsep.join([str(ROOT / "tests"), os.environ.get("PYTHONPATH", "")])
            env = dict(os.environ, TL_WORKER_MB="600", PYTHONPATH=path)
            argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest", "-n", "1", "test_hog.py"]
            part = suite.run_pytest(argv, d, env, "parallel")
        self.assertEqual(part.code, 1, part.out)
        self.assertIn("MemoryError", part.out)

    def test_a_host_with_less_free_memory_than_the_budgets_is_refused_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "meminfo"
            info.write_text("MemTotal: 99999999 kB\nMemAvailable:     3145728 kB\nMemFree: 1 kB\n")
            with mock.patch.object(suite, "MEMINFO", info), mock.patch.object(suite, "PROC_CGROUP", Path(d) / "no-cgroup"):
                self.assertEqual(suite.available_mb(), 3072)
                suite.refuse_if_short(1, suite.available_mb())  # 3072 MB covers one worker
                with self.assertRaises(Abort) as raised:
                    suite.refuse_if_short(3, suite.available_mb())
            line = str(raised.exception)
            self.assertEqual(len(line.splitlines()), 1)
            self.assertIn("3072 MB available", line)
            self.assertIn(f"{3 * suite.WORKER_BUDGET_MB} MB needed", line)

    def test_the_suite_refuses_before_running_when_memory_is_short(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "meminfo"
            info.write_text("MemAvailable:     1024 kB\n")
            with mock.patch.object(suite, "MEMINFO", info), mock.patch.object(suite, "PROC_CGROUP", Path(d) / "no-cgroup"), \
                    mock.patch.object(suite, "suite_lock_path", return_value=Path(d) / "l.lock"), \
                    mock.patch.object(suite, "run_parts") as ran, mock.patch.dict(os.environ, {"TASK_LOOP_SUITE_WORKERS": "2"}), \
                    self.assertRaises(Abort):
                suite.host_suite(ROOT, ROOT)
            ran.assert_not_called()


if __name__ == "__main__":
    unittest.main()
