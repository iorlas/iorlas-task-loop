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
