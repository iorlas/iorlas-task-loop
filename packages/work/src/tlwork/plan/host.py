"""Plan capabilities and shared hand-offs, separate from run facts and the stage's owned state."""
from collections.abc import Callable, Sequence
from typing import Protocol

from tlkernel.adrs import AdrStore
from tlkernel.ask import AskAnswer
from tlkernel.asked import Asked
from tlkernel.askenums import AskClass
from tlkernel.askspec import AskSpec
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import BriefSnap, Checkpoint, PlanStep, StageProgress
from tlkernel.checks import Check, CheckRun
from tlkernel.checksport import TreeProbe
from tlkernel.config import HostResources, VisualConfig
from tlkernel.gitport import Git
from tlkernel.ids import TreeSha
from tlkernel.looks import Methods
from tlkernel.plancheck import PlanData
from tlkernel.stagefacts import LeftoverSink
from tlkernel.stop import Stop
from tlkernel.wire import Open

from tlwork.work.ledger import Ledger


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
    def amend(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool: ...
    def save(self, *, step: str = ..., stage: int = ..., rounds: int = ..., n: int = ..., feedback: str = ...,
             progress: StageProgress | None = ...) -> None: ...
    def keep_pending(self, origin: str = ...) -> None: ...


class PlanResources(Protocol):
    def need(self) -> HostResources | None: ...


class PlanStores(Protocol):
    @property
    def adrs(self) -> Callable[[str], AdrStore]: ...

    @property
    def host(self) -> PlanResources: ...


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
    def raise_soft(self, question: str, options: Sequence[dict[str, object]] | None, cause: object, default: str) -> object: ...


class PlanCases(Protocol):
    def rules_text(self) -> str: ...


class PlanPictures(Protocol):
    def visual_cfg(self) -> VisualConfig | None: ...
    def shot_methods(self) -> Methods: ...
    def shot_table(self) -> str: ...


class PlanBriefing(Protocol):
    def where(self, node: str, checks: Sequence[object] = ..., failed: object = ..., listed: Sequence[str] = ...) -> str: ...


class PlanRounds(Protocol):
    def rounds_text(self, last: int = ..., each: int = ..., cap: int = ...) -> str: ...


class PlanShared(Protocol):
    def shared_text(self) -> str: ...


class PlanHand(Protocol):
    """Plain run fields shared with plan; PlanKeeper writes the plan fields here."""
    scope: str
    answered: Answered | None
    verify_answer: str
    landed_sha: str
    planner_ref: str
    plan_data: PlanData | None
    plan_summary: str
    plan_log: list[PlanStep]
    planned: int
    extra: int
    done: list[str]
    leftovers: list[Open]
    brief_hash: str
    snap: BriefSnap | None


class PlanPorts(Protocol):
    """Capabilities the plan stage calls on the rest of the run."""

    @property
    def leftover_sink(self) -> LeftoverSink: ...

    @property
    def git(self) -> Git: ...
    @property
    def store(self) -> Beads: ...
    @property
    def log(self) -> PlanLog: ...
    @property
    def steps(self) -> PlanSteps: ...
    @property
    def checkpoints(self) -> PlanCheckpoints: ...
    @property
    def stores(self) -> PlanStores: ...
    @property
    def checkout(self) -> PlanCheckout: ...
    @property
    def routing(self) -> PlanRouting: ...
    @property
    def briefs(self) -> PlanBriefs: ...
    @property
    def ask_flow(self) -> PlanAskFlow: ...
    @property
    def cases(self) -> PlanCases: ...
    @property
    def pictures(self) -> PlanPictures: ...
    @property
    def briefing(self) -> PlanBriefing: ...
    @property
    def hand(self) -> PlanRounds: ...
    @property
    def shared(self) -> PlanShared: ...
    @property
    def checker(self) -> ProbeChecker: ...

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked: ...
    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...
    def now(self) -> float: ...
    def assumed(self, text: str) -> None: ...
    def publish_plan(self) -> None: ...
    def shell_probe(self) -> TreeProbe: ...
    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Stop: ...
    def move_host(self, needs: list[str], why: str) -> Stop: ...
