"""No pytest worker outlives the launcher that started it: a wall limit, an interrupt and a dead launcher each end every process."""
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

import stream_proc
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.waits import until

from taskloop.adapters import landlock, procs
from taskloop.app.release import suite
from taskloop.app.release.shell import Abort

ROOT = Path(__file__).resolve().parent.parent
SLEEPER = """import os, time, unittest
class S(unittest.TestCase):
    def test_sleep(self):
        open(os.environ["PIDFILE"], "w").write(str(os.getpid()))
        time.sleep(300)
"""
LAUNCH = textwrap.dedent("""\
    import os, sys, signal, threading, time, _thread
    signal.signal(signal.SIGINT, signal.default_int_handler)  # a background shell starts us with SIGINT ignored
    sys.path[:0] = [{src!r}, {vendor!r}]
    from taskloop.app.release import suite
    suite.RUN_WALL_S = {wall}
    if {interrupt}:
        def interrupt():  # once the worker is inside its test
            while not os.path.exists(os.environ["PIDFILE"]):
                time.sleep(0.02)
            _thread.interrupt_main()
        threading.Thread(target=interrupt, daemon=True).start()
    try:
        part = suite.run_pytest({argv!r}, {root!r}, dict(os.environ), "parallel")
        print("exit", part.code, part.out.strip().splitlines()[-1], flush=True)
    except KeyboardInterrupt:
        print("interrupted", flush=True)
""")


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

    def launcher(self, wall, interrupt, argv=None):
        code = LAUNCH.format(src=str(ROOT / "src"), vendor=str(ROOT / "skills" / "task-loop" / "_vendor"), wall=wall,
                             root=str(self.root), argv=argv or self.argv, interrupt=interrupt)
        p = subprocess.Popen([sys.executable, "-c", code], env=self.env, stdout=subprocess.PIPE, text=True)
        self.pids.append(p.pid)
        return p

    def test_a_run_past_its_wall_limit_is_stopped_and_red(self):
        sleeper = "import os, time; open(os.environ['PIDFILE'], 'w').write(str(os.getpid())); time.sleep(300)"
        p = self.launcher(wall=1.5, interrupt=False, argv=[sys.executable, "-c", sleeper])  # room to start under load
        out, _ = p.communicate(timeout=90)
        pid = self.worker_pid()
        self.assertIn("exit 124", out)
        self.assertIn("its process tree was killed", out)
        self.assertFalse(stream_proc.alive(pid))

    def test_an_interrupted_launcher_stops_its_workers_before_it_exits(self):
        p = self.launcher(wall=600, interrupt=True)
        pid = self.worker_pid()
        out, _ = p.communicate(timeout=60)
        self.assertIn("interrupted", out)
        self.assertFalse(stream_proc.alive(pid))

    def test_a_worker_whose_controller_died_without_a_word_exits_on_its_own(self):
        starter = ("import os, subprocess, sys, time\n"
                   "p = subprocess.Popen(sys.argv[1:], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                   "while not os.path.exists(os.environ['PIDFILE']): time.sleep(0.05)\n"  # the worker is inside its test
                   "os.kill(p.pid, 9)\n")  # the controller dies at once, no handler: the way a SIGKILLed pytest ends
        subprocess.run([sys.executable, "-c", starter, *self.argv], env=self.env, cwd=self.root, timeout=90, check=True)
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
