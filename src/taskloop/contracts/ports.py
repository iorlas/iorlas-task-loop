"""The seams the engine reaches the world through: delegate, bd, git, and the workflow's checks.

A port is a Protocol plus the typed requests and results that cross it. Adapters implement it against the real thing
(`route.py`, `bd`, an exec); fakes implement it in memory, so a test needs no process, no files and no bash."""
from collections.abc import Callable
from typing import Any, NamedTuple, Protocol, final

import msgspec

from taskloop.contracts.argv import text_of
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.bead import BdError, Bead, Comment
from taskloop.contracts.delegate import DelegateResult, LiveEvent, RunRequest
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import Checkout
from taskloop.contracts.wire import Rec

EventSink = Callable[[LiveEvent], None]


class AnswerAsk(Protocol):
    """The owner's answer to an ask: the one intake `tl answer` uses (typed record, bead opened, receipt comment). The dashboard calls
    it with the ask's repo and bead; -> (the ask, "" or why: answered, withdrawn, closed, consumed, superseded, gone)."""

    def __call__(self, repo: str, bead: BeadId, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]: ...


class Delegate(Protocol):
    def speaks(self) -> int:
        """The contract number delegate answers with (`route.py contract --json`); the caller gates on 3."""
        ...

    def run(self, req: RunRequest, brief: str, schema: dict[str, Any], on_event: EventSink | None = None) -> DelegateResult:
        """One AI step. `brief` and `schema` travel as values (an adapter that needs files makes them; `req.brief_path` and
        `req.schema_path` are ignored here). Never raises for a worker's failure: that is a result with `stop` set.
        `on_event` gets the worker's live events, in order, before `run` returns."""
        ...


@final
class NewBead(Rec):
    title: str
    issue_type: str = "task"
    priority: int | None = None
    description: str = ""
    acceptance_criteria: str = ""
    labels: list[str] = msgspec.field(default_factory=list)
    parent: str = ""
    deps: list[str] = msgspec.field(default_factory=list)
    no_inherit_labels: bool = False


@final
class BeadPatch(Rec):
    """What `update` changes; a field left at its default is not touched. assignee "" clears it."""

    status: str = ""
    if_assignee: str = ""  # apply only while this actor still holds the bead (bd checks it atomically)
    assignee: str | None = None
    description: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None  # the whole metadata object replaced (set_metadata changes single keys)
    set_metadata: dict[str, str] = msgspec.field(default_factory=dict)
    unset_metadata: list[str] = msgspec.field(default_factory=list)


@final
class BeadQuery(Rec):
    status: str = ""
    label: str = ""
    include_closed: bool = False


class BdFailure(Exception):
    """bd refused or failed. `error.kind`: lint (missing sections), not_found, not_claimable, other."""

    def __init__(self, error: BdError) -> None:
        super().__init__(f"{error.kind}: {error.text}")
        self.error = error


class DoltPush(NamedTuple):
    """The outcome of a Dolt sync: code 0 synced; 1 error or a rejected push; 2 merge conflict; 3 retries exhausted; 4 stuck."""
    code: int
    text: str


class Beads(Protocol):
    """bd as the code uses it. Reads of an unknown bead answer None or []; `show` of a bead when bd itself fails (down, locked)
    raises BdFailure, so "no such bead" is never confused with "could not ask". A refused write raises BdFailure,
    except `claim`/`unclaim`, which answer whether the bead changed hands."""

    def show(self, bead: BeadId) -> Bead | None: ...
    def comments(self, bead: BeadId) -> list[Comment]: ...
    def find(self, query: BeadQuery) -> list[Bead]: ...
    def ready(self, label: str = "") -> list[Bead]: ...
    def create(self, new: NewBead) -> BeadId:
        """-> the new bead's id."""
        ...
    def update(self, bead: BeadId, patch: BeadPatch) -> None: ...
    def claim(self, bead: BeadId) -> bool: ...
    def unclaim(self, bead: BeadId, force: bool = False) -> bool: ...
    def heartbeat(self, bead: BeadId) -> None: ...
    def close(self, bead: BeadId, reason: str, if_assignee: str = "") -> None:
        """Close the bead. `if_assignee`: only while that actor still holds it (bd close has no such guard, so a same-value assignee
        update fences first, then bd close records the reason); a mismatch raises BdFailure and changes nothing."""
        ...
    def add_comment(self, bead: BeadId, text: str) -> None: ...
    def add_label(self, bead: BeadId, label: str) -> None: ...
    def remove_label(self, bead: BeadId, label: str) -> None: ...
    def reclaim(self, older_than: str, assignees: list[str]) -> None:
        """Free the claims whose lease ran out (of these assignees, else of all)."""
        ...
    def provenance(self, bead: BeadId, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "",
                   payload: str = "") -> None: ...
    def dolt_push(self) -> DoltPush:
        """Sync bd's Dolt data with its remote (pull, then push). -> DoltPush; never raises for bd's refusal."""
        ...
    def at(self, cwd: str) -> Beads:
        """The same store asked about the tracker in `cwd`."""
        ...


class Git(Protocol):
    """git, the one port every git call goes through (RealGit on the binary; logic tests run the same
    adapter over tests/support/gitsim). Every method takes the worktree it acts in and raises a SlotGitError subclass."""

    def fetch(self, d: str) -> None: ...
    def rebasing(self, d: str) -> bool: ...
    def rebase_abort(self, d: str) -> None: ...
    def dirty(self, d: str) -> bool: ...
    def branch(self, d: str) -> str:
        """The branch checked out in `d`, empty when HEAD is detached."""
        ...

    def commit_all(self, d: str, branch: str, message: str) -> None:
        """Commit every change on `branch`, created at HEAD when HEAD is detached."""
        ...

    def has_branch(self, d: str, branch: str) -> bool: ...
    def checkout(self, d: str, branch: str) -> None: ...
    def checkout_new(self, d: str, branch: str, start: str) -> None: ...
    def checkout_detached(self, d: str, ref: str) -> None: ...
    def clean(self, d: str, keep: list[str]) -> None: ...
    def checkouts(self, d: str) -> list[Checkout]: ...
    def remove_worktree(self, repo: str, path: str) -> bool: ...
    def add_worktree(self, repo: str, path: str, ref: str) -> None: ...


@final
class CheckSpec(Rec):
    argv: list[str]
    cwd: str
    timeout_s: float = 3600.0
    env: dict[str, str] = msgspec.field(default_factory=dict)

    @property
    def cmd(self) -> str:
        return text_of(self.argv)


@final
class CheckResult(Rec):
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
