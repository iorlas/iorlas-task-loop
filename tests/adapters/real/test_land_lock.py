"""The land lock around a command: exit code passes through, a second caller waits, the lock is released after a failure.

flock belongs to the open file description, so two descriptors in one process conflict like two processes: the waits run on threads. The
wrapped command is a fake (`procs.popen_held`); the one test that needs a real process is the kernel dropping the lock of a
holder that dies."""
import contextlib
import fcntl
import os
import signal
import subprocess
import threading
from pathlib import Path
from unittest import mock

import pytest
from support import homes
from support.case import Case
from support.procsim import real_proc
from support.tlmain import tl_main
from support.tmpdir import TemporaryDirectory
from support.waits import until

from taskloop.adapters import landlock, procs

NO_FCNTL = pytest.mark.skipif(os.name == "nt", reason="the lock is fcntl; tl has none on Windows (documented no-op)")


class Held:
    def replay(self) -> None:
        pass


class Child:
    """The wrapped command as run_locked sees it: `wait` runs `body` and returns its exit code."""

    def __init__(self, body) -> None:
        self.body, self.rc = body, None

    def poll(self):
        return self.rc

    def wait(self):
        self.rc = self.body()
        return self.rc


@NO_FCNTL
class LandLockTests(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = str(Path(self.tmp.name).resolve())  # tl land-lock resolves --repo: /var is /private/var on macOS
        self.env = {"XDG_CONFIG_HOME": str(Path(self.tmp.name) / "cfg")}
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.cmds = []
        self.real_popen_held = procs.popen_held
        patched = mock.patch.object(procs, "popen_held", self.start)
        patched.start()
        self.addCleanup(patched.stop)
        self.body = lambda: 0

    def start(self, cmd, **kw):
        if cmd[0] == "git":  # git reads go through the captured runner, which spawns by the same call: only the land command is faked
            return self.real_popen_held(cmd, **kw)
        self.cmds.append(cmd)
        return Child(self.body), Held()

    def run_ll(self, *args):
        return tl_main("land-lock", "--repo", self.repo, *args, cwd=self.repo, env=self.env)

    @contextlib.contextmanager
    def holder(self):
        """Another taker of the same lock (its own descriptor) until the block ends."""
        got, release = threading.Event(), threading.Event()

        def hold():
            with mock.patch.dict(os.environ, self.env), landlock.os_lock(self.path(), "the holder"):
                got.set()
                release.wait(30)
        t = threading.Thread(target=hold, daemon=True)
        t.start()
        assert got.wait(10), "the holder never took the lock"
        try:
            yield release
        finally:
            release.set()
            t.join(10)

    def path(self):
        with mock.patch.dict(os.environ, self.env):
            return landlock.land_lock_path(homes.cfg(), self.repo)

    def held_now(self):
        """True when another descriptor cannot take the lock right now."""
        with open(self.path(), "a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            return False

    def test_exit_code_passes_through_and_the_lock_is_held_while_it_runs(self):
        seen = []

        def body():
            seen.append(self.held_now())
            print("hi")
            return 3
        self.body = body
        r = self.run_ll("--", "wrapped")
        assert r.returncode == 3
        assert "hi" in r.stdout
        assert (seen, self.cmds) == ([True], [["wrapped"]])
        self.body = lambda: 0
        assert self.run_ll("--", "wrapped").returncode == 0
        assert not self.held_now()

    def test_second_waits_while_first_holds(self):
        told, ran = [], []

        def second():
            with mock.patch.dict(os.environ, self.env), landlock.os_lock(self.path(), "second", told.append):
                ran.append(1)
        with self.holder() as release:
            t = threading.Thread(target=second, daemon=True)
            t.start()
            assert until(lambda: told), "the second taker was never told it waits"
            assert (told, ran) == (["the holder"], [])  # it waits until the holder lets go
            release.set()
            t.join(10)
        assert ran == [1]

    def test_released_after_failing_command(self):
        self.body = lambda: 7
        assert self.run_ll("--", "wrapped").returncode == 7
        self.body = lambda: 0
        r = self.run_ll("--", "wrapped")
        assert r.returncode == 0
        assert "waiting" not in r.stdout  # a lock still held would print "waiting"; no timing needed

    def test_wait_min_times_out_with_75(self):
        with self.holder():
            r = self.run_ll("--wait-min", "0.002", "--", "wrapped")
        assert r.returncode == 75
        assert self.cmds == []  # the command never ran
        assert "land lock" in r.stderr

    @real_proc("the kernel drops the flock of a holder that is SIGKILLed (a forked child), so the next taker is not stuck")
    def test_a_holder_that_dies_frees_the_lock(self):
        ready = Path(self.tmp.name, "ready")
        pid = os.fork()
        if pid == 0:  # the holder
            try:
                with mock.patch.dict(os.environ, self.env), landlock.os_lock(self.path(), "doomed"):
                    ready.write_text("x")
                    signal.pause()
            finally:
                os._exit(0)
        try:
            assert until(ready.exists), "the holder never took the lock"
            assert self.held_now()
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
        assert self.run_ll("--wait-min", "0.05", "--", "wrapped").returncode == 0
