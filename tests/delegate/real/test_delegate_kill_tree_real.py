"""Tree kill: a worker stopped by timeout, reap or the app-server path leaves no descendant, whatever session it sits in."""

import contextlib
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
import pytest
from any_agent.harnesses.codex import CodexHarness
from any_agent.protocol import LaunchSpec
from any_agent.supervisor import RunHooks, Supervisor
from stream_proc import alive, proc_start
from support.procsim import real_proc

from delegate.adapters import codex_account, procs
from delegate.app import lease, usage
from delegate.app.publish import LiveSink
from delegate.contracts.state import Lease
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

# A fake of the Codex CLI: a node-shim analogue that starts a native child in a session of its own; the child ignores SIGTERM.
CHILD = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)"
SHIM = (
    "import subprocess,sys,time; "
    "c = subprocess.Popen([sys.executable, '-c', %r], start_new_session=True); "
    "open(sys.argv[1], 'w').write(str(c.pid)); time.sleep(300)"
).replace("%r", repr(CHILD))


def wait_for(path, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        with contextlib.suppress(OSError, ValueError):
            return int(Path(path).read_text())
        time.sleep(0.05)
    raise AssertionError("the shim never started its child")


def gone(pid, start, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if proc_start(pid) != start:
            return True
        time.sleep(0.2)
    return False


class RealTrees(Case):
    def setup_method(self):
        self.d = TemporaryDirectory()
        self.pidfile = os.path.join(self.d.name, "child.pid")
        self.addCleanup(self.d.cleanup)

    @real_proc("delegate: a worker, git or CLI process")
    def test_supervisor_timeout_leaves_no_process(self):
        seen: dict[str, Any] = {}
        time.time()

        def watch():  # capture start times while both are alive
            child = wait_for(self.pidfile)
            seen.update(child=child, child_start=proc_start(child), shim_start=proc_start(seen["shim"]))

        th = threading.Thread(target=watch)
        th.start()
        sup = Supervisor(CodexHarness(), RunHooks(started=lambda w: seen.update(shim=w.pid)), LiveSink("codex", ""))
        out = sup.run(LaunchSpec(argv=[sys.executable, "-c", SHIM, self.pidfile], env=dict(os.environ), cwd=self.d.name, stdin=""), 1.5)
        th.join()
        assert out.timed_out
        assert seen["child_start"] and seen["shim_start"]
        assert gone(seen["child"], seen["child_start"]), "the shim's native child survived the timeout"
        assert gone(seen["shim"], seen["shim_start"])

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_worker_that_cannot_be_registered_is_stopped_and_the_run_fails(self):
        seen: dict[str, Any] = {}

        def refuse(w: Any) -> None:
            seen.update(pid=w.pid, start=proc_start(w.pid))
            raise OSError("state is locked")

        sup = Supervisor(CodexHarness(), RunHooks(started=refuse), LiveSink("codex", ""))
        with pytest.raises(OSError, match="state is locked"):
            sup.run(LaunchSpec(argv=[sys.executable, "-c", SHIM, self.pidfile], env=dict(os.environ), cwd=self.d.name, stdin=""), 30)
        assert gone(seen["pid"], seen["start"]), "an unregistered worker was left running"

    @real_proc("delegate: a worker, git or CLI process")
    def test_reap_leaves_no_process(self):
        p = subprocess.Popen([sys.executable, "-c", SHIM, self.pidfile], start_new_session=True)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        child = wait_for(self.pidfile)
        v = Lease(lane="L", pid=1, start=0.0, expires=0.0, worker_pid=p.pid, worker_start=proc_start(p.pid))
        cstart = proc_start(child)
        assert v.worker_start and cstart
        time.time()
        assert lease.reap(v)
        assert gone(child, cstart), "the shim's native child survived reap"

    @real_proc("delegate: a worker, git or CLI process")
    def test_run_tree_timeout_stops_the_tree(self):
        with pytest.raises(subprocess.TimeoutExpired):
            procs.run_capture([sys.executable, "-c", SHIM, self.pidfile], 1.5)
        child = wait_for(self.pidfile)
        end = time.time() + 15
        while alive(child) and time.time() < end:
            time.sleep(0.2)
        assert not alive(child), "the shim's native child survived the run_tree timeout"

    @real_proc("delegate: a worker, git or CLI process")
    def test_stop_tree_grace_sends_term_first(self):
        code = (
            "import signal,sys,time; "
            "signal.signal(signal.SIGTERM, lambda *a: (open(sys.argv[1],'w').write('term'), sys.exit(0))); "
            "open(sys.argv[1]+'.up','w'); time.sleep(300)"
        )
        flag = os.path.join(self.d.name, "flag")
        p = subprocess.Popen([sys.executable, "-c", code, flag], start_new_session=True)
        wait_for_file = time.time() + 10
        while not os.path.exists(flag + ".up") and time.time() < wait_for_file:
            time.sleep(0.05)
        procs.stop(p, 3)
        p.wait(5)
        assert Path(flag).read_text() == "term"


class KillPaths(Case):
    def fake_server(self, body):
        """A `codex` whose app-server runs `body` (python); returns the which() patch."""
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        exe = Path(d.name) / "codex"
        exe.write_text(f"#!{sys.executable}\nimport sys, time\n{body}\n")
        exe.chmod(0o755)
        return mock.patch.object(shutil, "which", return_value=str(exe))

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_silent_app_server_is_cut_at_the_deadline_and_killed_through_the_tree_kill(self):
        with (
            self.fake_server("time.sleep(300)"),
            mock.patch.object(codex_account, "APP_SERVER_S", 1),
            mock.patch.object(procs, "kill_tree", wraps=procs.kill_tree) as kt,
        ):
            time.monotonic()
            res, err = usage.fetch_codex_limits()
        assert (res, err) == (None, "codex app-server did not answer")
        kt.assert_called_once()

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_partial_line_does_not_hang_and_answers_are_read_across_chunks(self):
        body = (
            'sys.stdin.readline(); print(\'{"id":1,"result":{}}\', flush=True); '
            "sys.stdin.readline(); sys.stdin.readline()\n"
            'sys.stdout.write(\'{"id":2,"res\'); sys.stdout.flush(); time.sleep(0.3); '
            'print(\'ult":{"ok":1}}\', flush=True); time.sleep(300)'
        )
        with self.fake_server(body):
            res, err = usage.fetch_codex_limits()
        assert (res, err) == ({"ok": 1}, None)
