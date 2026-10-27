"""The three seams the engine reaches the world through: delegate, bd, and the workflow's checks.

A port is a Protocol plus the typed requests and results that cross it. Adapters implement it against the real thing
(`route.py`, `bd`, a shell); fakes implement it in memory, so a test needs no process, no files and no bash."""
from collections.abc import Callable
from dataclasses import field
from typing import Any, Protocol

from taskloop.contracts.bead import BdError, Bead, Comment
from taskloop.contracts.codec import record
from taskloop.contracts.delegate import DelegateResult, LiveEvent, RunRequest

EventSink = Callable[[LiveEvent], None]


class Delegate(Protocol):
    def speaks(self) -> int:
        """The contract number delegate answers with (`route.py contract --json`); the caller gates on 3."""
        ...

    def run(self, req: RunRequest, brief: str, schema: dict[str, Any], on_event: EventSink | None = None) -> DelegateResult:
        """One AI step. `brief` and `schema` travel as values (an adapter that needs files makes them; `req.brief_path` and
        `req.schema_path` are ignored here). Never raises for a worker's failure: that is a result with `stop` set.
        `on_event` gets the worker's live events, in order, before `run` returns."""
        ...


@record
class NewBead:
    title: str
    issue_type: str = "task"
    priority: int | None = None
    description: str = ""
    acceptance_criteria: str = ""
    labels: list[str] = field(default_factory=list)
    parent: str = ""
    deps: list[str] = field(default_factory=list)
    no_inherit_labels: bool = False


@record
class BeadPatch:
    """What `update` changes; a field left at its default is not touched. assignee "" clears it."""

    status: str = ""
    assignee: str | None = None
    description: str | None = None
    set_metadata: dict[str, str] = field(default_factory=dict)
    unset_metadata: list[str] = field(default_factory=list)


@record
class BeadQuery:
    status: str = ""
    label: str = ""
    include_closed: bool = False


class BdFailure(Exception):
    """bd refused or failed. `error.kind`: lint (missing sections), not_found, not_claimable, other."""

    def __init__(self, error: BdError) -> None:
        super().__init__("%s: %s" % (error.kind, error.text))
        self.error = error


class Beads(Protocol):
    """bd as the code uses it. Reads of an unknown bead answer None or []; a refused write raises BdFailure,
    except `claim`/`unclaim`, which answer whether the bead changed hands."""

    def show(self, bead: str) -> Bead | None: ...
    def comments(self, bead: str) -> list[Comment]: ...
    def find(self, query: BeadQuery) -> list[Bead]: ...
    def ready(self) -> list[Bead]: ...
    def create(self, new: NewBead) -> str:
        """-> the new bead's id."""
        ...
    def update(self, bead: str, patch: BeadPatch) -> None: ...
    def claim(self, bead: str) -> bool: ...
    def unclaim(self, bead: str, force: bool = False) -> bool: ...
    def heartbeat(self, bead: str) -> None: ...
    def close(self, bead: str, reason: str) -> None: ...
    def add_comment(self, bead: str, text: str) -> None: ...
    def add_label(self, bead: str, label: str) -> None: ...
    def remove_label(self, bead: str, label: str) -> None: ...


@record
class CheckSpec:
    cmd: str
    cwd: str
    timeout_s: float = 3600.0
    env: dict[str, str] = field(default_factory=dict)


@record
class CheckResult:
    exit: int
    out: str = ""
    secs: float = 0.0
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit == 0 and not self.timed_out


class Checks(Protocol):
    def run(self, spec: CheckSpec) -> CheckResult:
        """Run one workflow command (bash semantics: `-e`, pipefail). Exit 124 and `timed_out` when the time ran out."""
        ...
