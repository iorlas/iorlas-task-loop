"""No shard outlives the launcher that started it: a wall limit, a stop, an interrupt and a dead launcher each end every shard process."""
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
    import sys, signal, threading, _thread, tempfile
    signal.signal(signal.SIGINT, signal.default_int_handler)  # a background shell starts us with SIGINT ignored
    from pathlib import Path
    sys.path[:0] = [{src!r}, {vendor!r}]
    from taskloop.app.release import suite
    suite.SHARD_WALL_S = {wall}
    root = Path({root!r})
    work = Path(tempfile.mkdtemp())
    if {interrupt}:
        threading.Timer(3, _thread.interrupt_main).start()
    try:
        parts = suite.run_shards([sys.executable, {shard!r}], str(root), root, work, [("shard1", ["test_sleep.S.test_sleep"])])
        print("exit", parts[0].code, parts[0].out.strip().splitlines()[-1], flush=True)
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
        self.env = dict(os.environ, PIDFILE=str(self.pidfile))
        self.shard = str(ROOT / "tests" / "shard.py")
        self.pids: list[int] = []
        self.addCleanup(self.reap)

    def reap(self):
        for pid in self.pids:  # a failing test must not leave its sleeper behind
            if stream_proc.alive(pid):
                procs.stop_pid(pid)

    def shard_pid(self) -> int:
        text = until(lambda: self.pidfile.exists() and self.pidfile.read_text().strip(), 30)
        self.assertTrue(text, "the shard never started its test")
        pid = int(text or 0)
        self.pids.append(pid)
        return pid

    def launcher(self, wall, interrupt):
        code = LAUNCH.format(src=str(ROOT / "src"), vendor=str(ROOT / "skills" / "task-loop" / "_vendor"), wall=wall, root=str(self.root),
                             shard=self.shard, interrupt=interrupt)
        p = subprocess.Popen([sys.executable, "-c", code], env=self.env, stdout=subprocess.PIPE, text=True)
        self.pids.append(p.pid)
        return p

    def test_a_shard_past_its_wall_limit_is_stopped_and_red(self):
        p = self.launcher(wall=4, interrupt=False)
        out, _ = p.communicate(timeout=60)
        pid = self.shard_pid()
        self.assertIn("exit 124", out)
        self.assertIn("its process tree was killed", out)
        self.assertFalse(stream_proc.alive(pid))

    def test_an_interrupted_launcher_stops_its_shards_before_it_exits(self):
        p = self.launcher(wall=600, interrupt=True)
        pid = self.shard_pid()
        out, _ = p.communicate(timeout=60)
        self.assertIn("interrupted", out)
        self.assertFalse(stream_proc.alive(pid))

    def test_a_shard_whose_launcher_died_without_a_word_exits_on_its_own(self):
        starter = ("import os, subprocess, sys, time\n"
                   "p = subprocess.Popen([sys.executable, sys.argv[1], 'ids', sys.argv[2], '--root', sys.argv[3],"
                   " '--parent', str(os.getpid())],"
                   " start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                   "while not os.path.exists(os.environ['PIDFILE']): time.sleep(0.05)\n"  # the shard is inside its test
                   "os._exit(0)\n")  # no finally, no handler: the way a SIGKILLed launcher ends
        ids = self.root / "ids"
        ids.write_text("test_sleep.S.test_sleep\n")
        subprocess.run([sys.executable, "-c", starter, self.shard, str(ids), str(self.root)], env=self.env, timeout=60, check=True)
        pid = self.shard_pid()
        self.assertTrue(until(lambda: not stream_proc.alive(pid), 15), "the orphaned shard is still running")


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
    def test_a_shard_past_its_address_space_cap_is_red_with_a_memory_error_and_the_other_shard_is_green(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "tests"
            root.mkdir()
            (root / "test_ok.py").write_text("import unittest\nclass A(unittest.TestCase):\n    def test_1(self): pass\n")
            (root / "test_hog.py").write_text("import unittest\nclass H(unittest.TestCase):\n    def test_1(self): bytearray(900 << 20)\n")
            todo = [("shard1", ["test_ok.A.test_1"]), ("shard2", ["test_hog.H.test_1"])]
            with mock.patch.object(suite, "SHARD_BUDGET_MB", 300):
                parts = suite.run_shards([sys.executable, str(ROOT / "tests" / "shard.py")], str(root), Path(d), Path(d), todo)
        self.assertEqual([p.code for p in parts], [0, 1], [p.out for p in parts])
        self.assertIn("MemoryError", parts[1].out)
        self.assertIn("OK", parts[0].out)

    def test_a_host_with_less_free_memory_than_the_budgets_is_refused_in_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "meminfo"
            info.write_text("MemTotal: 99999999 kB\nMemAvailable:     3145728 kB\nMemFree: 1 kB\n")
            with mock.patch.object(suite, "MEMINFO", info):
                self.assertEqual(suite.available_mb(), 3072)
                suite.refuse_if_short(1, suite.available_mb())  # 3072 MB covers one shard
                with self.assertRaises(Abort) as raised:
                    suite.refuse_if_short(3, suite.available_mb())
            line = str(raised.exception)
            self.assertEqual(len(line.splitlines()), 1)
            self.assertIn("3072 MB available", line)
            self.assertIn(f"{3 * suite.SHARD_BUDGET_MB} MB needed", line)

    def test_the_suite_refuses_before_planning_when_memory_is_short(self):
        with tempfile.TemporaryDirectory() as d:
            info = Path(d) / "meminfo"
            info.write_text("MemAvailable:     1024 kB\n")
            with mock.patch.object(suite, "MEMINFO", info), mock.patch.object(suite, "suite_lock_path", return_value=Path(d) / "l.lock"), \
                    mock.patch.object(suite, "run") as planned, mock.patch.dict(os.environ, {"TASK_LOOP_SUITE_WORKERS": "2"}), \
                    self.assertRaises(Abort):
                suite.host_suite(ROOT, ROOT)
            planned.assert_not_called()


if __name__ == "__main__":
    unittest.main()
