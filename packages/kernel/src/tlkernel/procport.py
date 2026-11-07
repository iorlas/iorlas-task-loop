"""The process port: spawn, stream, hold and wait, with the typed results; implemented by adapters.spawner and the process simulator."""
import threading  # noqa: TID251  only the type of a stop flag (Spawner.stream); contracts starts no thread
from collections.abc import Callable, Mapping
from typing import IO, Literal, Protocol, final

from tlkernel.wire import Rec


class WaitTimeout(Exception):
    """`Child.wait(timeout)` ran out; the child lives on."""


class Child(Protocol):
    """A process the engine started and does not wait for in `Spawner.run`: pid, an optional stdin pipe, a wait, and its stop."""

    pid: int
    stdin: IO[bytes] | None

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int:
        """-> the exit code; raises WaitTimeout when `timeout` seconds pass first."""
        ...
    def stop(self, grace: float) -> None:
        """Stop the child's whole tree (SIGTERM, `grace` seconds, SIGKILL) and wait until it is gone."""
        ...
    def stop_async(self, grace: float) -> None:
        """The same on a thread of its own, so the caller's loop goes on while the tree ends."""
        ...


class Hold(Protocol):
    """The signals that arrived while a child was being spawned: replayed first inside the try that stops the child."""

    def replay(self) -> None: ...


@final
class Ran(Rec):
    """What a child printed and how it ended, when `Spawner.run` waited for it. Exit 124 and `timed_out` when `timeout_s` ran out."""
    exit: int
    out: str = ""
    err: str = ""
    timed_out: bool = False


@final
class RanBytes(Rec):
    exit: int
    out: bytes = b""
    err: bytes = b""


@final
class Streamed(Rec):
    """How `Spawner.stream` ended. `returncode` is None when a signal ended the child (then `signal` is its number). `timed_out` is why
    the engine stopped it ("wall", "stopped"), None when it ended by itself. `survivors`: pids of its tree still alive after the stop."""
    returncode: int | None
    signal: int | None
    timed_out: str | None
    secs: float
    survivors: tuple[int, ...] = ()


class Spawner(Protocol):
    """Starting a process, as a capability: the only way app/ and cli/ run a child (RealSpawner in adapters/spawner.py; the logic tests
    run the same adapter over tests/support/procsim). The child's environment is built by tlkernel/childenv.py: `env` is the base (the
    process's own when None), `extra` goes over it. A program that is not there raises OSError."""

    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None, capture: bool = True, input: str | None = None) -> Ran:
        """Run to the end. `input` is the child's stdin; None inherits it. `capture` False shares stdout and stderr."""
        ...

    def run_bytes(self, argv: list[str], *, cwd: str | None = None, extra: Mapping[str, str] | None = None) -> RanBytes: ...

    def stream(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
               extra: Mapping[str, str] | None = None,
               on_output: Callable[[str], None], timeout_s: float | None = None, stop: threading.Event | None = None,
               grace: float = 5.0) -> Streamed:
        """Run in a session of its own, each line of stdout and stderr to `on_output` as it comes. It ends by itself, at `timeout_s` of wall
        time or when `stop` is set; then its whole tree is stopped (SIGTERM, `grace` seconds, SIGKILL) and proven dead. Any exception
        raised while it runs (an interrupt, a raising SIGTERM handler) stops the tree first."""
        ...

    def start(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
              extra: Mapping[str, str] | None = None, stdin: Literal["null", "pipe"] = "null",
              out: IO[bytes] | Literal["null", "inherit"] = "null") -> Child:
        """A child that outlives this call, in a session of its own. `out`: a log both its streams go to, or nothing, or ours."""
        ...

    def start_held(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
                   extra: Mapping[str, str] | None = None, out: IO[bytes]) -> tuple[Child, Hold]:
        """`start` with stdin null and the log `out`, but the SIGTERM that arrived during the spawn is not replayed: the caller does it."""
        ...

    def stop_pid(self, pid: int, start: str | None = None, grace: float = 5.0) -> tuple[int, ...]:
        """Stop a process this program did not start (the dashboard server) and its tree: SIGTERM, `grace` seconds, SIGKILL. `start` is its
        start token (a pid that is another process now reads as gone). -> the pids still alive afterwards."""
        ...
