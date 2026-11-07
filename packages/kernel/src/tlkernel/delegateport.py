"""The delegate as the engine sees it: the records it answers with and the one Protocol (`Route`) every caller takes it through.

The real route is `adapters.delegate.DelegateRoute` (delegate.api); a test passes a fake. No app module imports the adapter."""
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tlkernel.delegate import DelegateResult, LiveStart, RunRequest, WorkerStarted
from tlkernel.snapshots import StatusSnapshot

Json = dict[str, Any]


@dataclass(frozen=True)
class Completed:
    """What a seam call answers (the words of subprocess.CompletedProcess the engine reads)."""

    args: Sequence[str]
    returncode: int
    stdout: str
    stderr: str = ""


def completed(cmd: Sequence[str], code: int, out: str, err: str = "") -> Completed:
    return Completed(cmd, code, out, err)


class StopFlag(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class Resolved:
    dir: Path
    route: str
    contract: Json
    source: str  # explicit | pinned | installed


@dataclass(frozen=True)
class Refusal:
    kind: str  # not_installed | pin_unreadable | pin_missing_dir | skew_delegate_newer_no_match | skew_delegate_older
    detail: str = ""


@dataclass(frozen=True)
class Answer:
    """A parsed answer, its checkpoint wire object ({} for a synthesized stop), and the exact call argv and output for diagnostics."""

    res: DelegateResult
    raw: Json
    argv: tuple[str, ...] = ()
    trace: str = ""


class Stopped(Exception):
    """The engine ended the call (its wall limit, its silence watcher). `why` is the engine's own word for it."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class Lane:
    """One lane of delegate's fleet as the engine may ask it: usable now (None: delegate does not know the lane), why not, until when."""

    name: str
    usable: bool | None
    why: str = ""
    until: float = 0.0


@dataclass(frozen=True)
class Account:
    """One lane of the fleet: whether the router may use it, whether this machine can run it, and what fixes it when it cannot."""

    lane: str
    enabled: bool
    ready: bool
    fix: str


def survivors_of(stop: Json, res: DelegateResult | None = None) -> list[int]:
    """The pids the stop itself found alive, and the ones delegate names in the answer (`worker.end` worker_survived), without repeats."""
    pids = [int(p) for p in stop.get("alive") or []]
    pids += [s.pid for s in (res.worker.survivors if res and res.worker else []) if s.pid not in pids]
    return pids


class Seam:
    """What the engine reads off a process seam after a call (stop, obs, secs, worker, live_start): a fake lane's defaults."""

    def __init__(self) -> None:
        self.stop: Json = {}
        self.obs: Json = {}
        self.secs = 0.0
        self.worker: WorkerStarted | None = None
        self.outer: StopFlag | None = None  # the run's stop flag: set, the call is stopped

    def live_start(self) -> LiveStart | None:
        return None

    def survivors(self, res: DelegateResult | None = None) -> list[int]:
        """The pids that outlived the stop of this call (empty: the tree is proven dead). The engine asks this and reads no pid itself."""
        return survivors_of(self.stop, res)


class Probe(Protocol):
    @property
    def hosts(self) -> tuple[str, ...]: ...

    def up(self) -> bool | None: ...


class Route(Protocol):
    """Everything the engine, the loop and the owner's verbs ask of delegate."""

    @property
    def contract_no(self) -> int: ...  # the contract number this engine speaks
    @property
    def library(self) -> str: ...  # what the engine logs as the route of a call

    def resolve(self) -> Resolved | Refusal: ...
    def runner(self, log_path: str | Path, wall: float | None = None, live: str = "",
               on_worker: Callable[[WorkerStarted], None] | None = None) -> Seam | None: ...
    def call(self, resolved: Resolved, req: RunRequest, brief: str, schema: Json, runner: Callable[..., Completed],
             env: Mapping[str, str], delta: str | None = None) -> Answer: ...
    def probe(self, hosts: tuple[str, ...] = ()) -> Probe: ...
    def lane(self, name: str) -> Lane | None: ...
    def status_snapshot(self, claude_usage: object = None) -> StatusSnapshot: ...
    def accounts(self) -> list[Account]: ...
    def set_account(self, lane: str, enabled: bool) -> None: ...
