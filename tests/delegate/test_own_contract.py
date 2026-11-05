"""delegate-own, the contract set: REAL processes and signals (a fake agent CLI, no model). The worker is dead when the delegate call ends,
and a survivor is named. Run with `just test-delegate tests/delegate/test_own_contract.py`; no other run starts these."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

from support.case import Case

import hermetic  # noqa: F401
from run_support import short_limits
from test_route import ROOT

sys.path.insert(0, str(ROOT / "skills" / "delegate"))
import stream_proc
from any_agent import procs as shelf
from any_agent.harnesses.codex import CodexHarness
from any_agent.protocol import LaunchSpec
from any_agent.supervisor import RunHooks, Supervisor
from delegate.adapters import procs
from delegate.app import harnesses
from delegate.app.publish import LiveSink
from delegate.contracts import codec, wire
from stream_proc import alive, proc_start
from support.procsim import real_proc

FAKE = str(Path(__file__).resolve().parent / "delegate_fakes" / "fake_agent.py")


def wait_pid(path, secs=10):
    end = time.time() + secs
    while time.time() < end:
        try:
            return int(Path(path).read_text())
        except OSError, ValueError:
            time.sleep(0.05)
    raise AssertionError("the fake never wrote its child's pid")


def dead(pid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


class RealProcesses(Case):
    pid: int

    def setup_method(self):
        self.pidfile = os.path.join(os.environ["TMPDIR"], "child.pid")
        self.procs = []
        self.addCleanup(self.reap_leftovers)

    def reap_leftovers(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
                p.wait()
            for f in (p.stdin, p.stdout, p.stderr):
                if f:
                    f.close()

    def start(self, scenario: str) -> subprocess.Popen[bytes]:
        p = subprocess.Popen(
            [sys.executable, FAKE, scenario, self.pidfile],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        self.procs.append(p)
        assert p.stdin is not None
        assert p.stdout is not None
        p.stdin.write(b"brief")
        p.stdin.close()
        p.stdout.readline()  # its first event: the script is past its signal setup
        return p

    @real_proc("delegate: a worker, git or CLI process")
    def test_process_group_stop_takes_the_sessions_child_too(self):
        p = self.start("spawner")
        child = wait_pid(self.pidfile)
        rep = procs.kill_tree(p, grace=1)
        p.wait()
        assert dead(child), "the child in its own session survived"
        assert (rep.end, rep.survivors, rep.term_sent, rep.kill_sent) == (wire.END_OK, [], True, True)

    @real_proc("delegate: a worker, git or CLI process")
    def test_sigkill_escalation_when_sigterm_is_ignored(self):
        p = self.start("hang")
        t0 = time.time()
        rep = procs.kill_tree(p, grace=1)
        assert p.wait() == -signal.SIGKILL
        assert rep.term_sent and rep.kill_sent
        assert time.time() - t0 >= 1  # it waited the grace before SIGKILL

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_worker_that_obeys_sigterm_is_never_sigkilled(self):
        p = self.start("stall")
        rep = procs.kill_tree(p, grace=5)
        assert p.wait() == -signal.SIGTERM
        assert (rep.term_sent, rep.kill_sent, rep.survivors) == (True, False, [])

    @real_proc("delegate: a worker, git or CLI process")
    def test_worker_survived_names_the_pids_and_ends_the_run_so(self):
        p = self.start("stall")
        pid = p.pid
        with mock.patch.object(stream_proc, "stop_tree", return_value=(pid,)):  # a pid the kernel will not let go
            rep = shelf.stop(p, 0)
        assert [s.pid for s in rep.survivors] == [pid]
        end = procs.worker_end([rep], None)
        assert (end.end, [s.pid for s in end.survivors]) == (wire.END_SURVIVED, [pid])
        assert codec.from_json(wire.WorkerEnd, codec.to_json(end)) == end

    def run_fake(self, scenario, timeout=0, **limits):
        """-> (the outcome, the hooks): a fake agent under the real Supervisor, with the watchdog limits `limits` for the codex CLI."""
        hooks = RunHooks(started=lambda w: self.__dict__.setdefault("pid", w.pid))
        with short_limits("codex", **limits):
            sup = Supervisor(CodexHarness(), hooks, LiveSink("codex", ""), limits=harnesses.LIMITS["codex"])
        spec = LaunchSpec(
            argv=[sys.executable, FAKE, scenario, self.pidfile], env=dict(os.environ), cwd=os.environ["TMPDIR"], stdin="brief"
        )
        return sup.run(spec, timeout), hooks

    @real_proc("delegate: a worker, git or CLI process")
    def test_normal_run_is_ok_and_nothing_was_stopped(self):
        out, hooks = self.run_fake("normal")
        assert (out.rc, out.timed_out) == (0, False)
        assert json.loads(out.out.splitlines()[-1])["result"] == "fake answer"
        end = procs.worker_end(hooks.stops, None)
        assert (end.end, end.stopped) == (wire.END_OK, False)
        assert out.worker is not None
        assert (out.worker.pgid, bool(out.worker.start)) == (out.worker.pid, bool(proc_start(os.getpid())))

    @real_proc("delegate: a worker, git or CLI process")
    def test_call_timeout_stops_a_worker_that_ignores_sigterm(self):
        time.time()
        out, hooks = self.run_fake("spawner", timeout=2)
        assert out.timed_out
        end = procs.worker_end(hooks.stops, "timeout")
        assert (end.end, end.stopped, end.survivors) == (wire.END_TIMEOUT, True, [])
        assert dead(wait_pid(self.pidfile))
        assert dead(self.pid)

    @real_proc("delegate: a worker, git or CLI process")
    def test_idle_worker_is_stopped_by_the_watchdog_not_the_wall_clock(self):
        time.time()
        out, _ = self.run_fake("stall", timeout=60, first_event_s=5, silence_s=1)
        assert (out.timed_out, out.watch.why, out.watch.kind) == (False, "hung", "silence")
        assert dead(self.pid)

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_streaming_worker_is_never_idle(self):
        out, _ = self.run_fake("slow", timeout=60, first_event_s=5, silence_s=1)
        assert (out.rc, out.watch.why) == (0, None)

    @real_proc("delegate: a worker, git or CLI process")
    def test_sigterm_to_the_delegate_stops_the_worker_tree_first(self):
        code = (
            "import os, sys; sys.path.insert(0, {!r}); from any_agent.protocol import LaunchSpec; "
            "from any_agent.harnesses.codex import CodexHarness; "
            "from delegate.app.publish import LiveSink; from any_agent.supervisor import RunHooks, Supervisor; "
            "Supervisor(CodexHarness(), RunHooks(), LiveSink('codex', '')).run("
            "LaunchSpec(argv=[sys.executable, {!r}, 'spawner', {!r}], env=dict(os.environ), cwd='.', stdin='b'), 0)"
        ).format(str(ROOT / "src"), FAKE, self.pidfile)
        h = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(h)
        child = wait_pid(self.pidfile)
        time.sleep(0.3)
        h.send_signal(signal.SIGTERM)
        assert h.wait(timeout=30) == 128 + signal.SIGTERM
        assert dead(child), "SIGTERM to the delegate left the worker's child running"
