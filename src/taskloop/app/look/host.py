"""What the look stage reads and writes of the engine that runs it: one Protocol, so the stage has no hidden reach into the Engine."""
import threading
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from taskloop.adapters.looks import Methods
from taskloop.contracts.artifact import ArtifactMeta
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.config import EngineConfig, VisualConfig
from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.plancheck import StageData
from taskloop.contracts.wire import Open
from taskloop.stores.runlog import RunLog


class LookSteps(Protocol):
    def begin(self, step: str, text: str, **meta: object) -> int: ...
    def outcome(self, outcome: str, detail: str = ...) -> None: ...
    def move(self, to: str, cause: str, detail: str = ...) -> None: ...


class LookBudget(Protocol):
    @property
    def labels(self) -> list[str]: ...


class PictureBook(Protocol):
    """The look stage's own picture keeper (shots.Pictures), as the judge and the owner-look read it."""

    def visual_cfg(self) -> VisualConfig | None: ...
    def shots(self) -> list[str]: ...
    def stage_visual(self, st: StageData) -> bool: ...
    def shot_methods(self) -> Methods: ...
    def look_ready(self, st: StageData) -> bool: ...
    def show_pictures(self) -> list[tuple[str, ArtifactMeta]]: ...
    def before_pictures(self) -> list[tuple[Path, ArtifactMeta]]: ...
    def render_shots(self, reqs: Sequence[Open], rnd: int) -> tuple[list[str], list[str]]: ...
    def persist_look(self) -> None: ...


class CaseBook(Protocol):
    def cases_of(self, cls: str) -> list[str]: ...


class StageChecksView(Protocol):
    def stoppable(self, st: StageData, name: str, acceptance_first: bool = ..., groups: Sequence[str] | None = ...,
                  conflict_fix: Sequence[str] | None = ..., **meta: object) -> CheckRun: ...


class CheckoutPaths(Protocol):
    def changed_paths(self) -> list[str]: ...


class PendingKeeper(Protocol):
    def keep_pending(self, origin: str = ...) -> None: ...
    def keep_look(self) -> None: ...


class LockWaits(Protocol):
    def locked(self, what: str, path: Path | str, holder: str | None = ...) -> AbstractContextManager[Path | str]: ...


class LookHost(Protocol):
    """The engine, as the look stage sees it. The look-owned state (look_*, rendered_names, shots_skipped, shot_cache, artifact_repo,
    last_reqs, render_stale) lives on the engine because the checkpoint saves it."""

    Blocked: type[Exception]
    bead: BeadId
    bead_parent: str
    bead_title: str
    wt: str
    run_id: str
    run_dir: Path
    evidence_dir: Path
    home: ConfigDir
    cfg: EngineConfig
    dry: bool
    log: RunLog
    steps: LookSteps
    budget: LookBudget
    store: Beads
    pictures: PictureBook
    cases: CaseBook
    stage_checks: StageChecksView
    checkout: CheckoutPaths
    checkpoints: PendingKeeper
    waits: LockWaits
    at_stage: int
    last_flag: str
    writer_family: str
    retry_after: float
    pause_role: str
    pause_lane: str
    leftovers: list[dict[str, str]]
    unverified: list[Open]
    look_done: int
    look_notes: list[str]
    look_filed: bool
    look_retried: set[str]
    look_unjudged: dict[str, str]
    rendered_names: list[str]
    shots_skipped: set[str]
    shot_cache: Methods | None
    artifact_repo: str
    last_reqs: list[Open]
    render_stale: bool

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> tuple[dict[str, Any], object]: ...
    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def now(self) -> float: ...
    def sh(self, cmd: Sequence[str], timeout: float = ..., check: bool = ..., save: Path | None = ..., env: Mapping[str, str] | None = ...,
           pin: bool = ..., what: str = ..., cwd: Path | None = ..., stop: threading.Event | None = ...) -> tuple[int, str]: ...
