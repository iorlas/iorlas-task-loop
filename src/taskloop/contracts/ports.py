"""The three seams the engine reaches the world through: delegate, bd, and the workflow's checks.

A port is a Protocol plus the typed requests and results that cross it. Adapters implement it against the real thing
(`route.py`, `bd`, an exec); fakes implement it in memory, so a test needs no process, no files and no bash."""
from collections.abc import Callable
from dataclasses import field
from typing import Any, Protocol

from taskloop.contracts.argv import text_of
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.bead import BdError, Bead, Comment
from taskloop.contracts.codec import record
from taskloop.contracts.delegate import DelegateResult, LiveEvent, RunRequest

EventSink = Callable[[LiveEvent], None]


class AnswerAsk(Protocol):
    """The owner's answer to an ask: the one intake `tl answer` uses (typed record, bead opened, receipt comment). The dashboard calls
    it with the ask's repo and bead; -> (the ask, "" or why: answered, withdrawn, closed, consumed, superseded, gone)."""

    def __call__(self, repo: str, bead: str, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]: ...


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
    if_assignee: str = ""  # apply only while this actor still holds the bead (bd checks it atomically)
    assignee: str | None = None
    description: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None  # the whole metadata object replaced (set_metadata changes single keys)
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
    """bd as the code uses it. Reads of an unknown bead answer None or []; `show` of a bead when bd itself fails (down, locked)
    raises BdFailure, so "no such bead" is never confused with "could not ask". A refused write raises BdFailure,
    except `claim`/`unclaim`, which answer whether the bead changed hands."""

    def show(self, bead: str) -> Bead | None: ...
    def comments(self, bead: str) -> list[Comment]: ...
    def find(self, query: BeadQuery) -> list[Bead]: ...
    def ready(self, label: str = "") -> list[Bead]: ...
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
    def reclaim(self, older_than: str, assignees: list[str]) -> None:
        """Free the claims whose lease ran out (of these assignees, else of all)."""
        ...
    def provenance(self, bead: str, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "", payload: str = "") -> None: ...
    def at(self, cwd: str) -> "Beads":
        """The same store asked about the tracker in `cwd`."""
        ...


@record
class CheckSpec:
    argv: list[str]
    cwd: str
    timeout_s: float = 3600.0
    env: dict[str, str] = field(default_factory=dict)

    @property
    def cmd(self) -> str:
        return text_of(self.argv)


@record
class CheckResult:
    exit: int
    out: str = ""
    secs: float = 0.0
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit == 0 and not self.timed_out


class TreeProbe(Protocol):
    """What the plan-check lint may ask of the tree and the machine a check will run on."""

    def has_command(self, word: str) -> bool:
        """True when the word resolves to an executable on the tree's PATH (shutil.which)."""
        ...
    def recipes(self) -> set[str] | None:
        """The recipe and alias names of the tree's justfile, None when there is no just or no justfile."""
        ...
    def exists(self, path: str) -> bool:
        """The path (relative to the tree, or absolute) exists."""
        ...
    def is_dir(self, path: str) -> bool: ...


class Checks(Protocol):
    def run(self, spec: CheckSpec) -> CheckResult:
        """Run one command (an argv, no shell). Exit 124 and `timed_out` when the time ran out."""
        ...
