"""A worker that is a script, not a process: what the supervisor sees of a CLI (stdin, stdout and stderr lines, a wait that times out, a
tree stop), played from a list. Nothing is spawned, so a silence, a stall or a grace costs the fake clock (SteppingClock), not seconds.

A script is a list of steps: a str is a stdout line, `Err(text)` a stderr line, `Jump(s)` moves the fake clock `s` seconds before the next
step, `Exit(rc)` ends the process. Without an `Exit` the worker hangs after its last line until it is stopped, which is the point of
most tests. `install` puts it where the supervisor spawns and stops (any_agent.supervisor.procs)."""
import contextlib
import dataclasses
import queue
import subprocess
import threading
from collections.abc import Iterator
from unittest import mock

from any_agent import supervisor
from any_agent.procs import StopReport, Worker

from support.fake_clock import SteppingClock


@dataclasses.dataclass(frozen=True)
class Err:
    text: str


@dataclasses.dataclass(frozen=True)
class Jump:
    seconds: float


@dataclasses.dataclass(frozen=True)
class Exit:
    rc: int = 0


Step = str | Err | Jump | Exit

EOF_ = object()


class Stream:
    """A blocking line source, like a pipe: readline waits for the next line and returns b"" at the end."""

    def __init__(self) -> None:
        self.q: queue.Queue[object] = queue.Queue()

    def put(self, line: str) -> None:
        self.q.put(line.rstrip("\n").encode("utf-8") + b"\n")

    def end(self) -> None:
        self.q.put(EOF_)

    def readline(self) -> bytes:
        item = self.q.get()
        if item is EOF_:
            self.q.put(EOF_)
            return b""
        assert isinstance(item, bytes)
        return item

    def close(self) -> None:
        pass


class Sink:
    """The worker's stdin: takes the prompt and keeps it."""

    def __init__(self) -> None:
        self.data = b""

    def write(self, b: bytes) -> int:
        self.data += b
        return len(b)

    def close(self) -> None:
        pass


class FakePopen:
    """The part of subprocess.Popen the supervisor uses."""

    def __init__(self, script: list[Step], clock: SteppingClock, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.stdin, self.stdout, self.stderr = Sink(), Stream(), Stream()
        self.dead = threading.Event()
        self.stopped = False
        self.thread = threading.Thread(target=self.play, args=(script, clock), daemon=True)

    def play(self, script: list[Step], clock: SteppingClock) -> None:
        for step in script:
            if self.dead.is_set():
                return
            match step:
                case str():
                    self.stdout.put(step)
                case Err():
                    self.stderr.put(step.text)
                case Jump():
                    with clock.lock:
                        clock.t += step.seconds
                case Exit():
                    self.finish(step.rc)
                    return

    def finish(self, rc: int) -> None:
        if self.returncode is None:
            self.returncode = rc
        self.stdout.end()
        self.stderr.end()
        self.dead.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self.dead.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        assert self.returncode is not None
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode


@contextlib.contextmanager
def install(*scripts: list[Step], clock: SteppingClock) -> Iterator[list[FakePopen]]:
    """The next spawns of the supervisor are these scripts, in order; yields the workers started (`stopped`: a tree stop came)."""
    started: list[FakePopen] = []
    todo = list(scripts)

    def spawn(argv: list[str], cwd: str | None = None, env: object = None, **_: object) -> tuple[FakePopen, Worker]:
        p = FakePopen(todo.pop(0), clock, pid=40_000 + len(started))
        started.append(p)
        p.thread.start()
        return p, Worker(pid=p.pid, pgid=p.pid, start=None)

    def kill_tree(p: FakePopen, grace: float | None = None) -> StopReport:
        p.stopped = True
        p.finish(-9)
        return StopReport(kill_sent=True)

    def run_capture(argv: list[str], timeout: float, **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "")  # the CLI's side commands (export, status) answer nothing

    with (
        mock.patch.object(supervisor.procs, "spawn", spawn),
        mock.patch.object(supervisor.procs, "kill_tree", kill_tree),
        mock.patch.object(supervisor.procs, "run_capture", run_capture),
    ):
        yield started
