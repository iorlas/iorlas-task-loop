"""Files other readers build their view from: the delegate status snapshot, the indexes, pins and the release result."""
from typing import ClassVar

import msgspec

from taskloop.contracts.wire import Rec


class WindowStatus(Rec):
    name: str
    used_pct: float | None = None
    resets_at: float | None = None


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


class NeedInput(Rec):
    what: str
    why: str = ""
    how: str = ""


class StatusSnapshot(Rec):
    """snapshots/delegate.status.json: delegate's `route.py status --json` read once by `tl lanes` / `tl usage`; the dashboard reads
    this and never runs delegate. `at` is delegate's own clock."""

    V: ClassVar[int] = 1
    at: float
    lanes: list[LaneStatus] = msgspec.field(default_factory=list)
    needs_input: list[NeedInput] = msgspec.field(default_factory=list)


class SessionIndex(Rec):
    """sessions/<id>.json: a Claude session id -> its transcript."""

    V: ClassVar[int] = 1
    session: str
    transcript: str
    cwd: str = ""
    t: float = 0.0


class RepoEntry(Rec):
    added: float


class ReposIndex(Rec):
    V: ClassVar[int] = 1
    repos: dict[str, RepoEntry] = msgspec.field(default_factory=dict)


class SharedNotes(Rec):
    """shared/<repo_key>.json: what runs of one repo tell each other (flaky tests, facts)."""

    V: ClassVar[int] = 1
    flakes: dict[str, float] = msgspec.field(default_factory=dict)
    notes: list[str] = msgspec.field(default_factory=list)


class Pin(Rec):
    """pinned.json: the install a loop and run-task use; each key optional."""

    V: ClassVar[int] = 1
    task_loop: str | None = msgspec.field(default=None, name="task-loop")
    delegate: str | None = None


class ReleaseResult(Rec):
    """releases/last.json: what the last dev/release.py run did."""

    V: ClassVar[int] = 1
    version: str
    ok: bool
    t: float
    why: str = ""
    sha: str = ""


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


class SlotSetupMarker(Rec):
    """slots/<repo_key>.setup.json: the hash of the setup command a slot last ran, so a changed command runs again."""

    V: ClassVar[int] = 1
    cmd_hash: str
    t: float
