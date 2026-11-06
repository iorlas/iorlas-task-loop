"""RunFacts: what every stage of a run reads and nobody writes after the engine opens (docs/design/facts.md, tl-e5t0.28), and the small
ports the stages share. A stage takes the Protocol it needs (named for the capability), never the engine; the root builds `RunFacts` and
`RunPorts` once and hands them over. The ports are live objects, the facts are frozen data: `bead_title` and `bead_parent` are not
facts (bd names them at the first step), they travel as `BeadInfo`; `artifact_repo` is a lazy cache, so it is the `RepoKey` port.
RunPorts, which holds the Stores bundle, is stores/runports.py: contracts cannot import the stores layer."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from taskloop.contracts.checkpoint import Checkpoint, StageProgress
from taskloop.contracts.checks import Check, CheckResult, CheckRun
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.fence import Claim
from taskloop.contracts.ids import BeadId, CheckId
from taskloop.contracts.log import EngineLog
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.plancheck import PlanCheck


@dataclass(frozen=True, slots=True)
class RunFacts:
    bead: BeadId
    wt: str
    cfg: EngineConfig
    home: ConfigDir
    run_id: str  # TL_RUN_ID in every check, run_id in every row
    run_dir: Path
    task_dir: Path
    brief_file: Path
    evidence_dir: Path
    repo: str  # the repo's id, from the slot's main checkout
    dry: bool
    fresh: bool  # --fresh: ignore the checkpoint
    claim: Claim  # the run's right to act on its bead


@dataclass(frozen=True, slots=True)
class BeadInfo:
    """What bd says about the bead, known at the first step and handed to the steps after it."""

    title: str
    parent: str


class Narrate(Protocol):
    """The two verbs of the run log a stage uses; `emit` stays with the pipeline."""

    def note(self, text: str) -> int: ...
    def warn(self, text: str) -> int: ...


class RunLogPort(Narrate, Protocol):
    """The run log as a stage that writes typed records sees it (the checks): Narrate plus `emit` and `next_id`."""

    def emit(self, rec: EngineLog) -> int: ...
    def next_id(self, prefix: str) -> str: ...


class StepBook(Protocol):
    @property
    def id(self) -> str: ...
    def begin(self, step: str, text: str, **meta: object) -> int: ...
    def outcome(self, outcome: str, detail: str = ...) -> None: ...
    def end(self, outcome: str = ...) -> None: ...
    def move(self, to: str, cause: str, detail: str = ...) -> None: ...


class RepoKey(Protocol):
    """The repo's store key (adapters.check_files.repo_key): taken at the first call, the same string after."""

    def key(self) -> str: ...


class CheckpointsPort(Protocol):
    def read(self) -> Checkpoint | None: ...
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...,
             progress: StageProgress | None = ...) -> None: ...
    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool: ...
    def keep_look(self) -> None: ...
    def keep_pending(self, origin: str = ...) -> None: ...
    def keep_filed(self, lost: list[dict[str, str]] | None = ...) -> None: ...
    def mark_applied(self, key: str) -> None: ...
    def applied(self) -> frozenset[str]: ...


class CheckLogPort(Protocol):
    env: dict[str, str]  # the environment the checks of this run were given, kept for the record
    logged: set[CheckId]  # the checks whose start is already in the log

    def start(self, c: Check, rnd: int, log: str = ...) -> str: ...
    def close(self, c: Check, res: CheckResult, cid: str | None, rnd: int) -> None: ...
    def round(self, node_id: str, run: CheckRun) -> None: ...


class CheckerPort(Protocol):
    def run(self, stage_checks: Sequence[PlanCheck], name: str, markers: str = ..., acceptance_first: bool = ...,
            groups: Sequence[str] | None = ..., conflict_fix: Sequence[str] | None = ..., **meta: object) -> CheckRun: ...
    def run_items(self, items: Sequence[Check], everything: bool = ..., learn: bool = ..., show_clean: bool = ...,
                  clean: bool = ..., all_files: bool = ...) -> CheckRun: ...
    def gate_green(self, clean: bool = ...) -> bool: ...
