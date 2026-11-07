"""The write tests' named collaborators and fail-fast process boundary."""
import threading
from collections.abc import Mapping
from typing import IO, Literal

from tlgate.api import WriterSplit
from tlkernel.config import EngineConfig
from tlkernel.procport import Child, Hold, Ran, RanBytes, Streamed
from tlkernel.wire import Open


class FakeWriterChecks:
    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self.secs: dict[str, float] = {}

    def split(self) -> WriterSplit:
        return WriterSplit(self.cfg, self.secs)


class FakeWriteHooks:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def review_cap(self, n: int) -> None:
        self.calls.append(("review_cap", n))

    def link_judged(self, review: Open) -> None:
        self.calls.append(("link_judged", review))

    def safe_point(self, step: str) -> None:
        self.calls.append(("safe_point", step))


class FakeNewFiles:
    def __init__(self) -> None:
        self.kinds: dict[str, list[str]] = {"ignored": [], "meant": [], "unexplained": []}
        self.calls: list[tuple[object, ...]] = []

    def new_by_kind(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self.kinds.items()}

    def stage_work(self, unexplained: list[str], ignored: list[str]) -> str:
        self.calls.append((list(unexplained), list(ignored)))
        return ""

    def new_files_brief(self, unexplained: list[str]) -> str:
        self.calls.append((list(unexplained),))
        return ""

    def undecided_new(self, unexplained: list[str], review: Open) -> list[str]:
        self.calls.append((list(unexplained), review))
        return list(unexplained)


class NoProcesses:
    """Work refuses every process operation; gate's FakeSpawner runs real processes."""
    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
            extra: Mapping[str, str] | None = None, timeout_s: float | None = None, capture: bool = True,
            input: str | None = None) -> Ran:
        raise AssertionError("work fake must not run a process")

    def stream(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
               extra: Mapping[str, str] | None = None, on_output: object, timeout_s: float | None = None,
               stop: threading.Event | None = None, grace: float = 5.0) -> Streamed:
        raise AssertionError("work fake must not stream a process")

    def run_bytes(self, argv: list[str], *, cwd: str | None = None, extra: Mapping[str, str] | None = None) -> RanBytes:
        raise AssertionError("work fake must not run bytes")

    def start(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
              extra: Mapping[str, str] | None = None, stdin: Literal["null", "pipe"] = "null",
              out: IO[bytes] | Literal["null", "inherit"] = "null") -> Child:
        raise AssertionError("work fake must not start a process")

    def start_held(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
                   extra: Mapping[str, str] | None = None, out: IO[bytes]) -> tuple[Child, Hold]:
        raise AssertionError("work fake must not start a held process")

    def stop_pid(self, pid: int, start: str | None = None, grace: float = 5.0) -> tuple[int, ...]:
        raise AssertionError("work fake must not stop a process")


class FakeWriteLook:
    def __init__(self) -> None:
        self.done = 0
