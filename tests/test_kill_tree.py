"""tl-7y6.2.17: stream-proc's stop_tree stops the whole tree of a fake worker shim: a child in the shim's group and a child that
called setsid. Only PIDs this test starts are stopped; no pattern kills, no real codex. No signal is sent from here: a stop is stop_tree."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401

from taskloop.adapters import procs  # noqa: E402

SHIM = r"""
import os, subprocess, sys, time
out = sys.argv[1]
kid = (
    "import os,signal,sys,time\nif os.environ.get('IGNORE_TERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "open(sys.argv[1],'w').write(str(os.getpid()))\ntime.sleep(300)\n"
)
subprocess.Popen([sys.executable, "-c", kid, out + ".same"])                           # same group as the shim
subprocess.Popen([sys.executable, "-c", kid, out + ".setsid"], start_new_session=True)  # the native child, own session
open(out + ".shim", "w").write(str(os.getpid()))
time.sleep(300)
"""


def read_pid(path, wait=15):
    end = time.time() + wait
    while time.time() < end:
        try:
            text = Path(path).read_text()
            if text:
                return int(text)
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"no pid in {path}")


def alive(pid):
    """Running, not a zombie: a stopped grandchild is reparented and reaped by init, but give a zombie no credit."""
    state = procs.proc_start(pid)
    return state is not None and procs.alive(pid, state)


class KillTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.started = []

    def tearDown(self):  # only PIDs this test started
        for pid in self.started:
            procs.stop_pid(pid, grace=0.2)

    def run_shim(self):
        out = os.path.join(self.tmp, "pid")
        p = subprocess.Popen([sys.executable, "-c", SHIM, out], start_new_session=True)
        self.started.append(p.pid)
        pids = {k: read_pid(f"{out}.{k}") for k in ("shim", "same", "setsid")}
        self.started += list(pids.values())
        return p, pids

    def test_kills_same_group_and_setsid_child(self):
        p, pids = self.run_shim()
        self.assertEqual(os.getpgid(pids["same"]), p.pid)
        self.assertNotEqual(os.getpgid(pids["setsid"]), p.pid)
        self.assertEqual(procs.stop_tree(p, grace=2.0), ())
        deadline = time.time() + 60
        while time.time() < deadline and (alive(pids["same"]) or alive(pids["setsid"])):
            time.sleep(0.1)
        self.assertFalse(alive(pids["same"]), "same-group child survived")
        self.assertFalse(alive(pids["setsid"]), "setsid'd child survived")

    def test_kills_children_that_ignore_sigterm(self):
        os.environ["IGNORE_TERM"] = "1"
        try:
            p, pids = self.run_shim()
        finally:
            del os.environ["IGNORE_TERM"]
        self.assertEqual(procs.stop_tree(p, grace=2.0), ())
        deadline = time.time() + 60
        while time.time() < deadline and (alive(pids["same"]) or alive(pids["setsid"])):
            time.sleep(0.1)
        self.assertFalse(alive(pids["same"]), "same-group child survived")
        self.assertFalse(alive(pids["setsid"]), "setsid'd child survived")


if __name__ == "__main__":
    unittest.main()
