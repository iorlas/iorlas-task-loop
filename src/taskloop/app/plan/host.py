"""What the plan stage reads and writes of the engine that runs it: one Protocol, so the stage has no hidden reach into the Engine
(docs/design/b-plan.md, slice 1; the same shape as look/host.py and review/host.py). Each part types the members it reads as the
narrow view it needs (`CapHost`, `BriefsHost`, ...), all of them subsets of `PlanHost`."""
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from tlkernel.adrs import AdrStore
from tlkernel.ask import AskAnswer
from tlkernel.asked import Asked
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import BriefSnap, PlanStep
from tlkernel.checks import Check, CheckRun
from tlkernel.config import EngineConfig, HostResources, VisualConfig
from tlkernel.enums import AskClass
from tlkernel.gitport import Git
from tlkernel.ids import BeadId, TreeSha
from tlkernel.plancheck import PlanData
from tlkernel.stagefacts import LeftoverSink
from tlkernel.stop import Stop
from tlkernel.wire import Open

from taskloop.adapters.check_probe import PathProbe
from taskloop.adapters.looks import Methods
from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.state import PlanState
from taskloop.domain.review.ledger import Ledger


class Answered(Protocol):
    """The owner ask this run starts from, once answered."""

    id: str
    ask_class: AskClass
    answer: AskAnswer | None


class PlanLog(Protocol):
    def note(self, text: str) -> int: ...


class ProbeChecker(Protocol):
    """The check runner as the acceptance probe uses it: one registered check, with the round counter put back after."""

    round: int

    def run_items(self, items: Sequence[Check], everything: bool = ..., learn: bool = ..., show_clean: bool = ...,
                  clean: bool = ..., all_files: bool = ...) -> CheckRun: ...


class PlanSteps(Protocol):
    def outcome(self, outcome: str, detail: str = ...) -> None: ...
    def move(self, to: str, cause: str, detail: str = ...) -> None: ...


class PlanCheckpoints(Protocol):
    def amend(self, fn: object) -> bool: ...
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...,
             progress: object = ...) -> None: ...
    def keep_pending(self, origin: str = ...) -> None: ...


class PlanHostResources(Protocol):
    def need(self) -> HostResources | None: ...


class PlanStores(Protocol):
    adrs: Callable[[str], AdrStore]

    @property
    def host(self) -> PlanHostResources: ...


class PlanCheckout(Protocol):
    def task_diff(self) -> str: ...
    def base_sha(self) -> str: ...
    def tree_hash(self) -> TreeSha: ...


class PlanRouting(Protocol):
    def ledger(self) -> Ledger: ...
    def ledger_of(self, plan: PlanData) -> Ledger: ...


class PlanBriefs(Protocol):
    def export(self) -> None: ...
    def text(self) -> str: ...


class PlanAskFlow(Protocol):
    def repo(self) -> str: ...
    def raise_soft(self, question: str, options: object, cause: object, default: str) -> object: ...


class PlanCases(Protocol):
    def rules_text(self) -> str: ...


class PlanPictures(Protocol):
    def visual_cfg(self) -> VisualConfig | None: ...
    def shot_methods(self) -> Methods: ...
    def shot_table(self) -> str: ...


class PlanBriefing(Protocol):
    def where(self, node: str, checks: Sequence[object] = ..., failed: object = ..., listed: Sequence[str] = ...) -> str: ...


class PlanHand(Protocol):
    def rounds_text(self, last: int = ..., each: int = ..., cap: int = ...) -> str: ...


class PlanShared(Protocol):
    def shared_text(self) -> str: ...


class PlanHost(Protocol):

    @property
    def leftover_sink(self) -> LeftoverSink: ...
    bead: BeadId
    wt: str
    cfg: EngineConfig
    dry: bool
    run_id: str
    run_dir: Path
    task_dir: Path
    brief_file: Path
    evidence_dir: Path
    scope: str
    git: Git
    store: Beads
    answered: Answered | None
    verify_answer: str
    landed_sha: str
    planner_ref: str
    kind: object
    plan_data: PlanData | None
    plan_summary: str
    plan_log: list[PlanStep]
    planned: int
    extra: int
    done: list[str]
    leftovers: list[Open]
    brief_hash: str
    snap: BriefSnap | None
    amend: AmendState
    plan_state: PlanState
    log: PlanLog
    steps: PlanSteps
    checkpoints: PlanCheckpoints
    stores: PlanStores
    checkout: PlanCheckout
    routing: PlanRouting
    briefs: PlanBriefs
    ask_flow: PlanAskFlow
    cases: PlanCases
    pictures: PlanPictures
    briefing: PlanBriefing
    hand: PlanHand
    shared: PlanShared
    checker: ProbeChecker

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked: ...
    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def now(self) -> float: ...
    def assumed(self, text: str) -> None: ...
    def publish_plan(self) -> None: ...
    def shell_probe(self) -> PathProbe: ...
    def blocked_for(self, why: str, kind: str, stop: object = None, spec: object = None, fix: bool = False) -> Stop: ...
    def move_host(self, needs: list[str], why: str) -> Stop: ...
