"""Files other readers build their view from: the task snapshot, the indexes, pins and the release result."""
from dataclasses import field
from typing import ClassVar

from taskloop.contracts.codec import record
from taskloop.contracts.locks import EngineLock


@record
class TaskRow:
    bead: str
    title: str
    status: str
    labels: list[str] = field(default_factory=list)
    parent: str = ""
    slot: str | None = None
    worktree: str = ""
    lock: EngineLock | None = None
    run: str | None = None
    ask: str | None = None
    blocker: str = ""


@record
class TasksSnapshot:
    """snapshots/<repo_key>.tasks.json: written by the loop each pass; the dashboard reads it instead of asking bd."""

    V: ClassVar[int] = 1
    t: float
    repo: str
    beads: list[TaskRow] = field(default_factory=list)


@record
class WindowStatus:
    name: str
    used_pct: float | None = None
    resets_at: float | None = None


@record
class LaneStatus:
    """One lane as the lane cards and the banner show it: delegate's `cockpit.lanes` row joined with its top-level `lanes` entry."""

    id: str
    label: str = ""
    family: str = ""
    kind: str = ""
    model: str = ""
    state: str = ""
    emoji: str = ""
    reason: str = ""
    unlock_at: float | None = None
    warnings: list[str] = field(default_factory=list)
    windows: list[WindowStatus] = field(default_factory=list)
    out: bool = False
    out_until: float | None = None
    out_reason: str | None = None
    notes: list[str] = field(default_factory=list)


@record
class NeedInput:
    what: str
    why: str = ""
    how: str = ""


@record
class StatusSnapshot:
    """snapshots/delegate.status.json: delegate's `route.py status --json` read once by `tl lanes` / `tl usage`; the dashboard reads
    this and never runs delegate. `at` is delegate's own clock."""

    V: ClassVar[int] = 1
    at: float
    lanes: list[LaneStatus] = field(default_factory=list)
    needs_input: list[NeedInput] = field(default_factory=list)


@record
class SessionIndex:
    """sessions/<id>.json: a Claude session id -> its transcript."""

    V: ClassVar[int] = 1
    session: str
    transcript: str
    cwd: str = ""
    t: float = 0.0


@record
class RepoEntry:
    added: float


@record
class ReposIndex:
    V: ClassVar[int] = 1
    repos: dict[str, RepoEntry] = field(default_factory=dict)


@record
class SharedNotes:
    """shared/<repo_key>.json: what runs of one repo tell each other (flaky tests, facts)."""

    V: ClassVar[int] = 1
    flakes: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@record
class Pin:
    """pinned.json: the install a loop and run-task use; each key optional."""

    V: ClassVar[int] = 1
    task_loop: str | None = field(default=None, metadata={"name": "task-loop"})
    delegate: str | None = None


@record
class ReleaseResult:
    """releases/last.json: what the last dev/release.py run did."""

    V: ClassVar[int] = 1
    version: str
    ok: bool
    t: float
    why: str = ""
    sha: str = ""


@record
class DashState:
    """dash.json: the one dashboard server of this machine."""

    V: ClassVar[int] = 1
    pid: int
    port: int
    bind: str
    token: str
    version: str
    started: float
    pid_start: float | None = None
    idle_until: float | None = None


@record
class SlotSetupMarker:
    """slots/<repo_key>.setup.json: the hash of the setup command a slot last ran, so a changed command runs again."""

    V: ClassVar[int] = 1
    cmd_hash: str
    t: float
