"""Files other readers build their view from: the delegate status snapshot, the indexes, pins and the release result."""
from typing import Any, ClassVar, final

import msgspec

from taskloop.contracts.wire import Rec


@final
class WindowStatus(Rec):
    name: str
    used_pct: float | None = None
    resets_at: float | None = None


@final
class LaneStatus(Rec):
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
    warnings: list[str] = msgspec.field(default_factory=list)
    windows: list[WindowStatus] = msgspec.field(default_factory=list)
    five: float | None = None  # the contract's typed 5-hour window, percent used (the top-level `lanes[id].five`); windows[] names are free
    week: float | None = None  # the contract's typed weekly window, percent used (`lanes[id].week`)
    out: bool = False
    out_until: float | None = None
    out_reason: str | None = None
    notes: list[str] = msgspec.field(default_factory=list)


@final
class NeedInput(Rec):
    what: str
    why: str = ""
    how: str = ""


@final
class StatusSnapshot(Rec):
    """snapshots/delegate.status.json: delegate's `route.py status --json` read once by `tl lanes` / `tl usage`; the dashboard reads
    this and never runs delegate. `at` is delegate's own clock."""

    V: ClassVar[int] = 1
    at: float
    lanes: list[LaneStatus] = msgspec.field(default_factory=list)
    needs_input: list[NeedInput] = msgspec.field(default_factory=list)


@final
class SessionIndex(Rec):
    """sessions/<id>.json: a Claude session id -> its transcript."""

    V: ClassVar[int] = 1
    session: str
    transcript: str
    cwd: str = ""
    source: str = ""
    t: float = 0.0


@final
class RepoEntry(Rec):
    added: float


@final
class ReposIndex(Rec):
    V: ClassVar[int] = 1
    repos: dict[str, RepoEntry] = msgspec.field(default_factory=dict)


@final
class SharedNotes(Rec):
    """shared/<repo_key>.json: what runs of one repo tell each other (flaky tests, facts)."""

    V: ClassVar[int] = 1
    flakes: dict[str, float] = msgspec.field(default_factory=dict)
    notes: list[str] = msgspec.field(default_factory=list)


@final
class Pin(Rec):
    """pinned.json: the install a loop and run-task use; each key optional."""

    V: ClassVar[int] = 1
    task_loop: str | None = msgspec.field(default=None, name="task-loop")
    delegate: str | None = None
    pinned_at: float | None = None


@final
class ReleaseResult(Rec):
    """releases/last.json: what the last dev/release.py run did (a later success replaces a failure)."""

    V: ClassVar[int] = 1
    ok: bool
    version: str
    summary: str
    at: float
    branch: str = "main"
    message: str = ""
    tests: list[str] = msgspec.field(default_factory=list)
    log: str = ""


@final
class DashState(Rec):
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


@final
class SlotSetupMarker(Rec):
    """slots/<repo_key>.setup.json: the hash of the setup command a slot last ran, so a changed command runs again."""

    V: ClassVar[int] = 1
    cmd_hash: str
    t: float


@final
class GreenRun(Rec):
    """One green suite run: the tree it ran on and the exact command."""

    tree: str
    command: str
    at: float


@final
class SuiteGreens(Rec):
    """releases/suite-green.json: the newest green runs of the release suite (a hit needs the same tree and command)."""

    V: ClassVar[int] = 1
    greens: list[GreenRun] = msgspec.field(default_factory=list)


@final
class ReflectState(Rec):
    """reflect-digest.json: where the daily reflection digest stands: the end of the last one, the last try, and the beads it filed
    (each: cause, repo, bead, tokens, runs...; the digest edits them as plain dicts)."""

    V: ClassVar[int] = 1
    until: float = 0.0
    tried: float = 0.0
    filed: list[dict[str, Any]] = msgspec.field(default_factory=list)


@final
class StatusTried(Rec):
    """snapshots/delegate.tried.json: when `tl lanes` last tried to file delegate's status (a failed try leaves it, so the loop waits)."""

    V: ClassVar[int] = 1
    t: float
