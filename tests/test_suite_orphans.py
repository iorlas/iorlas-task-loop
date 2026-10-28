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

import support.paths  # noqa: F401  (ROOT/src on sys.path)
import stream_proc
from taskloop.adapters import landlock, procs
from taskloop.app.release import suite
from support.waits import until

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
                   "p = subprocess.Popen([sys.executable, sys.argv[1], 'ids', sys.argv[2], '--root', sys.argv[3], '--parent', str(os.getpid())],"
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


if __name__ == "__main__":
    unittest.main()
