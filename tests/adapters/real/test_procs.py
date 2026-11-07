"""The process seam (adapters/procs.py): the child env a worker gets, a captured run, a stopped tree, and the SIGTERM that lands while a
child is being spawned (the engine's handler raises: the child must not be left running, owned by nobody)."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
import support.paths  # noqa: F401

from taskloop.adapters import procs
from tlkernel import childenv
from tlkernel.env import snapshot
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

POSIX = os.name != "nt"


class Interrupted(Exception):
    """What the engine's SIGTERM handler raises."""


class ChildEnv(Case):

    def test_a_worker_process_really_sees_it(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/home/u/.claude-alt", "CLAUDE_CODE_SESSION_ID": "s"}):
            ran = procs.capture(
                ["sh", "-c", 'echo "${CLAUDE_CONFIG_DIR:-None} ${CLAUDE_CODE_SESSION_ID:-None}"'],
                None,
                childenv.current_env(snapshot()),
                30,
            )
        assert ran.out.split() == ["/home/u/.claude-alt", "None"]


@pytest.mark.skipif(not (POSIX), reason="process groups")
class Capture(Case):
    def test_it_collects_output_and_the_exit_code(self):
        ran = procs.capture(["sh", "-c", "echo out; echo err >&2; exit 3"], None, None, 30)
        assert (ran.exit, ran.out.strip(), ran.err.strip(), ran.timed_out) == (3, "out", "err", False)

    def test_a_timeout_stops_the_child_and_everything_it_started(self):
        with TemporaryDirectory() as d:
            code = ("import subprocess, sys, time\n"
                    "w = subprocess.Popen(['sleep', '60'], start_new_session=True)\n"
                    "open(sys.argv[1], 'w').write(str(w.pid)); time.sleep(60)\n")
            ran = procs.capture([sys.executable, "-c", code, str(Path(d) / "pid")], None, None, 1.5)
            assert (ran.exit, ran.timed_out) == (124, True)
            assert not procs.alive(int((Path(d) / "pid").read_text()))


@pytest.mark.skipif(not (POSIX), reason="process groups")
class SigtermWhileSpawning(Case):
    """A SIGTERM during `Popen()` runs the engine's raising handler inside the constructor: the caller never gets the Popen object. The
    stream-proc spawn holds the signal until the child is in hand and stops it."""

    def setup_method(self):
        self.pids = []
        outer = self

        class SignalledPopen(subprocess.Popen):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                outer.pids.append(self.pid)
                handler = signal.getsignal(signal.SIGTERM)
                assert callable(handler)
                handler(signal.SIGTERM, None)  # the signal lands here, between fork and the return
        self.old = signal.signal(signal.SIGTERM, self.handler)
        self.addCleanup(signal.signal, signal.SIGTERM, self.old)
        self.addCleanup(lambda: [procs.stop_pid(p, grace=0.2) for p in self.pids])
        patch = mock.patch.object(subprocess, "Popen", SignalledPopen)
        patch.start()
        self.addCleanup(patch.stop)

    @staticmethod
    def handler(_signum, _frame):
        raise Interrupted()

    def gone(self, pid):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            if not procs.alive(pid):
                return True
            time.sleep(0.05)
        return False

    def test_a_detached_spawn_leaves_no_child_alive(self):
        with pytest.raises(Interrupted):
            procs.spawn(["sleep", "60"])
        assert len(self.pids) == 1
        assert self.gone(self.pids[0])

    def test_a_captured_run_leaves_no_child_alive(self):
        with pytest.raises(Interrupted):
            procs.capture(["sleep", "60"], None, None, 60)
        assert len(self.pids) == 1
        assert self.gone(self.pids[0])

    def test_the_held_spawn_the_loop_uses_stops_the_child_when_the_signal_is_replayed(self):
        p, hold = procs.popen_held(["sleep", "60"], start_new_session=True)
        try:
            with pytest.raises(Interrupted):
                hold.replay()
        finally:
            procs.stop_tree(p, grace=0.5)
        assert self.gone(p.pid)
