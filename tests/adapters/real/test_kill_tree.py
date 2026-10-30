"""tl-7y6.2.17: stream-proc's stop_tree stops the whole tree of a fake worker shim: a child in the shim's group and a child that
called setsid. Only PIDs this test starts are stopped; no pattern kills, no real codex. No signal is sent from here: a stop is stop_tree."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
from support.procsim import real_proc  # noqa: E402

from taskloop.adapters import procs  # noqa: E402

SHIM = r"""
import os, subprocess, sys, time
out = sys.argv[1]
plain = ["sh", "-c", "exec sleep 300"]                      # sleepers, not interpreters
stubborn = ["sh", "-c", "trap '' TERM; exec sleep 300"]    # a child that ignores SIGTERM
kids = {"same": subprocess.Popen(plain),                    # same group as the shim
        "setsid": subprocess.Popen(plain, start_new_session=True),  # the native child, own session
        "same_stubborn": subprocess.Popen(stubborn),
        "setsid_stubborn": subprocess.Popen(stubborn, start_new_session=True)}
time.sleep(0.3)  # the shells have set their trap and exec'd the sleep
for name, kid in kids.items():
    open(out + "." + name, "w").write(str(kid.pid))
open(out + ".shim", "w").write(str(os.getpid()))
time.sleep(300)
"""


pytestmark = real_proc("a stop reaches a whole real process tree: the same group, a setsid child, a shim")


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
        pids = {k: read_pid(f"{out}.{k}") for k in ("shim", "same", "setsid", "same_stubborn", "setsid_stubborn")}
        self.started += list(pids.values())
        return p, pids

    def test_kills_same_group_and_setsid_children_and_those_that_ignore_sigterm(self):
        p, pids = self.run_shim()
        for name in ("same", "same_stubborn"):
            self.assertEqual(os.getpgid(pids[name]), p.pid)
        for name in ("setsid", "setsid_stubborn"):
            self.assertNotEqual(os.getpgid(pids[name]), p.pid)
        self.assertEqual(procs.stop_tree(p, grace=0.3), ())
        kids = [pids[k] for k in ("same", "setsid", "same_stubborn", "setsid_stubborn")]
        deadline = time.time() + 60
        while time.time() < deadline and any(alive(pid) for pid in kids):
            time.sleep(0.1)
        for name in ("same", "setsid", "same_stubborn", "setsid_stubborn"):
            self.assertFalse(alive(pids[name]), f"{name} child survived")


if __name__ == "__main__":
    unittest.main()
