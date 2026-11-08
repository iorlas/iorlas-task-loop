"""Supervisor: run one worker to its end. It spawns the harness's launch in a session of its own, pumps each output line into the
harness parser ONCE, routes the parsed events (the turn rules, the live file, the vendor ref, the secret policy), ticks the watchers about
every half second and stops the worker's tree when one fires, on the call's timeout, or when the caller dies. What the caller wants to
hear comes in a `RunHooks` for this run (no process-wide callback lists); what happened comes back as a `RunOutcome`.

Watchers (each `poll() -> Stop | None`): the lane marked out under the worker, the harness's own log (OpenCode retries a limit forever
without exiting), the silence/first-event deadlines, the turn rules (answer then grace, stall), the wait for the network (one probe past a
grace).
"""

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import field
from pathlib import Path
from typing import IO, Literal, Protocol

from any_agent import events as ev
from any_agent import procs, watch
from any_agent._json import mutable
from any_agent.protocol import Harness, LaunchSpec, Summary
from any_agent.watch import Limits

LANE_GONE_EVERY = 10  # seconds between looks at whether the lane was marked out by someone else
NET_GRACE_S = 15  # how long a worker may say "waiting for network" before one probe decides whether to stop it
POLL_S = 0.5


type EndStatus = Literal["done", "error", "killed", "timeout"]


class LiveSink(Protocol):
    """Where a run reports what the worker is doing right now (a live file, a dashboard). Every call is from the supervisor's threads
    and may not raise."""

    def started(self, pid: int) -> None: ...

    def feed(self, e: ev.HarnessEvent) -> None: ...

    def poll(self, idle_s: float) -> None: ...

    def end(self, status: EndStatus, cost_usd: float | None = None) -> None: ...


class NullSink:
    """The sink of a caller that watches nothing."""

    def started(self, pid: int) -> None:
        pass

    def feed(self, e: ev.HarnessEvent) -> None:
        pass

    def poll(self, idle_s: float) -> None:
        pass

    def end(self, status: EndStatus, cost_usd: float | None = None) -> None:
        pass


def end_status(timed_out: bool, hung: str | None, stop: str | None, rc: int | None) -> EndStatus:
    """A run's outcome as its end status."""
    if timed_out:
        return "timeout"
    if hung or stop == "stall":
        return "killed"
    return "done" if stop == "answer" or rc == 0 else "error"


@mutable
class RunHooks:
    """What the caller of a run wants to hear, for this run only."""

    started: Callable[[procs.Worker], None] | None = None  # the process exists: its pid, group and start token
    ref: Callable[[str], None] | None = None  # the vendor named its session
    beat: Callable[[float], None] | None = None  # the worker printed something (wall time, at most every 30 s)
    idle_s: float | None = None  # seconds of silence before the worker is hung (None = the harness's limit)
    unattended: bool = False  # the caller is an engine: stop when it dies
    stops: list[procs.StopReport] = field(default_factory=list)  # one report per tree stop made for this run


@mutable
class Stop:
    """Why a watcher stopped the worker: "limit" | "credit" | "logged_out" (the lane is out) or "hung" (a deadline), the deadline's kind and
    words, the vendor's line."""

    why: str | None = None
    msg: str = ""
    kind: str | None = None
    words: str = ""


@mutable
class RunOutcome:
    rc: int | None = None
    out: str = ""
    err: str = ""
    timed_out: bool = False
    stop: str | None = None  # the turn rules' verdict: "answer" | "stall"
    watch: Stop = field(default_factory=Stop)
    secret: str | None = None  # the secret path a command named (the worker was stopped before it could use what it read)
    net: bool = False  # stopped because the network is down
    summary: Summary = field(default_factory=Summary)
    stream_tail: list[str] = field(default_factory=list)
    worker: procs.Worker | None = None


class AccountGoneWatcher:
    """Stops a worker whose lane another process marked out for a limit, credit or login reason: it is burning an exhausted lane."""

    def __init__(self, gone: Callable[[], tuple[str, str] | None], every: float = LANE_GONE_EVERY) -> None:
        self.gone, self.every = gone, every
        self.last: float | None = None

    def poll(self) -> Stop | None:
        if self.last is not None and time.monotonic() - self.last < self.every:
            return None
        self.last = time.monotonic()
        mark = self.gone()
        return Stop(why=mark[0], msg=mark[1]) if mark is not None else None  # the mark's own reason


class LogWatcher:
    """Stops a worker whose harness log gained a limit line since launch (OpenCode retries a limit forever without exiting). A line that
    only
    echoes the worker's own tool input is never one."""

    def __init__(self, log_dir: Path, is_limit: Callable[[str], object], echoes: Callable[[str], bool]) -> None:
        self.dir, self.is_limit, self.echoes = log_dir, is_limit, echoes
        self.offs: dict[Path, int] = {}
        with contextlib.suppress(OSError):
            self.offs = {f: f.stat().st_size for f in log_dir.glob("*.log")}

    def poll(self) -> Stop | None:
        with contextlib.suppress(OSError):
            for f in self.dir.glob("*.log"):
                size, off = f.stat().st_size, self.offs.get(f, 0)
                if size > off:
                    with f.open("rb") as fh:
                        fh.seek(off)
                        new = fh.read(size - off).decode("utf-8", "replace")
                    self.offs[f] = size
                    hit = next((ln for ln in new.splitlines() if self.is_limit(ln) and not self.echoes(ln)), None)
                    if hit:
                        return Stop(why="limit", msg=hit.strip())
        return None


class Supervisor:
    def __init__(
        self,
        harness: Harness,
        hooks: RunHooks | None = None,
        live: LiveSink | None = None,
        *,
        limits: Limits | None = None,
        gone: Callable[[], tuple[str, str] | None] | None = None,
        log: LogWatcher | None = None,
        policy: Callable[[ev.HarnessEvent], str | None] | None = None,
        net_up: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        lim, hooks = limits or harness.limits, hooks or RunHooks()
        self.hx, self.hooks, self.live, self.policy, self.net_up, self.clock = harness, hooks, live or NullSink(), policy, net_up, clock
        self.dog = watch.Watchdog(lim.first_event_s, hooks.idle_s or lim.silence_s, clock=clock, beat=hooks.beat)
        self.turn = watch.Turn(lim.grace_s, clock=clock)
        self.gone = AccountGoneWatcher(gone) if gone else None
        self.log, self.lock, self.out = log, threading.RLock(), RunOutcome()
        self.now = Stop()
        self.asked = False

    # -- the lines of the worker ----------------------------------------------------------------------------------------------------------
    def feed(self, events: list[ev.HarnessEvent]) -> bool:
        """Route one parsed line: the turn rules, the live file, the vendor ref, the secret policy. -> True when the worker must stop
        now."""
        stop = False
        with self.lock:
            self.turn.apply(events)
            for e in events:
                self.live.feed(e)
                if isinstance(e, ev.Started) and self.hooks.ref:
                    self.hooks.ref(e.ref)
                hit = self.policy(e) if self.policy and self.hx.secret_event and isinstance(e, self.hx.secret_event) else None
                if hit and not self.out.secret:
                    self.out.secret = hit
                    self.hx.evidence.denials.append(
                        ev.Denied(tool="Bash", input={"command": hit}, kind="secret", reason="the command names a secret path")
                    )
                    stop = True
        return stop

    def _on_out(self, line: str) -> bool:
        with self.lock:  # both streams feed one harness: its state (open rows, evidence) is touched by one line at a time
            return self.feed(self.hx.parse_line(line))

    def _on_err(self, line: str) -> bool:
        with self.lock:
            return self.feed(self.hx.parse_log_line(line))

    # -- the watchers --------------------------------------------------------------------------------------------------------------------
    def poll(self) -> bool:
        """True when the worker must be stopped: lane gone, harness log, hung, the turn's answer or stall, the network down for good."""
        for w in (self.gone, self.log):
            s = w.poll() if w else None
            if s:
                self.now = s
                return True
        if self.dog.poll():
            self.now = Stop(why="hung", kind=self.dog.why, words=self.dog.describe())
            return True
        self.live.poll(self.dog.idle_s)
        verdict = self.turn.verdict(self.dog)
        if verdict == "stall":
            self.now = Stop(why="hung", kind="stall", words=self.turn.stall_words())
        if verdict:
            return True
        e = self.hx.evidence
        if e.net_at is not None and self.clock() - e.net_at >= NET_GRACE_S and self.net_up:
            e.net_at = None
            if not self.net_up():
                self.out.net = True
                return True
        return False

    # -- the run -------------------------------------------------------------------------------------------------------------------------
    def _pump(
        self,
        stream: IO[bytes],
        sink: list[str],
        cb: Callable[[str], bool],
        p: subprocess.Popen[bytes],
        killed: list[int],
        tick: Callable[[], None],
    ) -> None:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace")
            sink.append(line)
            with contextlib.suppress(Exception):
                tick()
            if cb(line):  # the policy asks to stop the worker now
                killed.append(1)
                self.hooks.stops.append(procs.kill_tree(p))

    def _stop(self, p: subprocess.Popen[bytes], killed: list[int]) -> None:
        killed.append(1)
        self.hooks.stops.append(procs.kill_tree(p))
        p.wait()

    def run(self, spec: LaunchSpec, timeout: float) -> RunOutcome:
        """-> RunOutcome. Own process group; the timeout kills the group; stdin carries the prompt then closes; UTF-8, errors replaced."""
        p, worker = procs.spawn(spec.argv, spec.cwd, spec.env)
        self.out.worker = worker
        self.live.started(worker.pid)
        if self.hooks.started:
            try:
                self.hooks.started(worker)
            except Exception:  # an unregistered worker could never be reaped: stop its tree now and let the caller see the failure
                self.hooks.stops.append(procs.kill_tree(p))
                raise
        out: list[str] = []
        err: list[str] = []
        killed: list[int] = []

        def feed_stdin() -> None:
            with contextlib.suppress(OSError):
                if p.stdin is None:
                    return
                p.stdin.write(spec.stdin.encode("utf-8"))
                p.stdin.close()

        threads = [
            threading.Thread(target=self._pump, args=(p.stdout, out, self._on_out, p, killed, self.dog.touch), daemon=True),
            threading.Thread(target=self._pump, args=(p.stderr, err, self._on_err, p, killed, self.dog.touch), daemon=True),
            threading.Thread(target=feed_stdin, daemon=True),
        ]
        for th in threads:
            th.start()
        self._wait(p, killed, timeout)
        for th in threads:
            th.join(5)
        for f in (p.stdin, p.stdout, p.stderr):
            with contextlib.suppress(OSError):
                f and f.close()
        return self.finish(p.returncode, "".join(out), "".join(err), bool(killed))

    def _wait(self, p: subprocess.Popen[bytes], killed: list[int], timeout: float) -> None:
        ppid, end = os.getppid(), time.time() + timeout if timeout else None

        def bye(signum: int, frame: object) -> None:
            raise SystemExit(128 + signum)

        mine = threading.current_thread() is threading.main_thread()  # a library caller runs on any thread; only the main one takes signals
        old = {g: signal.signal(g, bye) for g in (signal.SIGTERM, signal.SIGHUP)} if mine else {}
        try:
            while True:
                try:
                    p.wait(timeout=POLL_S if end is None else max(0.01, min(POLL_S, end - time.time())))
                    break
                except subprocess.TimeoutExpired:
                    if end is not None and time.time() >= end:
                        self.out.timed_out = True
                        self._stop(p, killed)
                        break
                    if self.poll():
                        self._stop(p, killed)
                        break
                    if (
                        self.hooks.unattended and os.getppid() != ppid
                    ):  # SIGKILL on the engine cannot be caught: the parent changing is the only sign
                        raise SystemExit(1) from None
        except (
            BaseException
        ):  # SIGTERM, SIGHUP, Ctrl-C, parent gone: the worker is in its own group, so stop it here or it keeps burning the plan
            self.hooks.stops.append(procs.kill_tree(p))
            p.wait()
            raise
        finally:
            for g, h in old.items():
                signal.signal(g, h)

    def finish(self, rc: int | None, out: str, err: str, killed: bool = False) -> RunOutcome:
        """The run is over: fold what the worker printed and how it ended into the outcome (the harness's summary), and close the live
        file."""
        o = self.out
        if (
            killed and rc == 0
        ):  # we stopped it, but a shell wrapper can exit 0 in the instant its child dies, before our kill lands: it was killed all the same
            rc = -signal.SIGKILL
        o.rc, o.out, o.err, o.stop, o.watch = rc, out, err, self.turn.stop, self.now
        o.summary = self.hx.summary(rc, out, err, self.turn.stop, o.timed_out)
        if (
            self.now.why or self.turn.stop or o.timed_out
        ):  # the raw tail of the stream, so the call record shows what the CLI last said before it was stopped
            o.stream_tail = watch.tail(out)
        self.live.end(end_status(o.timed_out, self.now.why if self.now.why == "hung" else None, self.turn.stop, rc), o.summary.cost or None)
        return o


def run(
    harness: Harness,
    spec: LaunchSpec,
    timeout: float,
    hooks: RunHooks | None = None,
    *,
    live: LiveSink | None = None,
    limits: Limits | None = None,
    gone: Callable[[], tuple[str, str] | None] | None = None,
    log: LogWatcher | None = None,
    policy: Callable[[ev.HarnessEvent], str | None] | None = None,
    net_up: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RunOutcome:
    """Run `spec` under `harness` to its end -> RunOutcome. `timeout` of 0 = none. What the caller wants to hear comes in `hooks`, `live`,
    `gone` (the lane marked out: its reason and message), `log` (the harness's own log),
    `policy` (a secret path a command names: its words) and
    `net_up` (one probe once the worker has waited for the network past the grace)."""
    sup = Supervisor(harness, hooks, live, limits=limits, gone=gone, log=log, policy=policy, net_up=net_up, clock=clock)
    return sup.run(spec, timeout)
