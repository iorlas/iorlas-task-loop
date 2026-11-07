"""Standalone stage capabilities and shared values, bound separately by the root."""
from collections.abc import Iterable
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from tlkernel import fence
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Checkpoint
from tlkernel.checkpoint import RunState as CheckpointState
from tlkernel.checks import CheckRun
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.kinds import Kind
from tlkernel.locator import RunBundle
from tlkernel.plancheck import PlanData, RoundState
from tlkernel.run import RunFinish, RunState
from tlkernel.stagefacts import RunLogPort
from tlkernel.wire import Open

from taskloop.app.pipeline.closing_record import RecordHost, RecordSteps
from taskloop.app.pipeline.crash import CrashHost
from taskloop.app.pipeline.store_ports import StandaloneStores
from taskloop.domain import effects
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec


@runtime_checkable
class Problem(Protocol):
    @property
    def text(self) -> str: ...


class Gate(Protocol):
    def green(self) -> bool: ...
    def run(self) -> object: ...


class Landing(Protocol):
    @property
    def gate(self) -> Gate: ...
    def finish(self, bead: Bead) -> str: ...


class OnceRun(Protocol):
    def go(self) -> int: ...
    def beat(self) -> None: ...
    def beat_died(self, err: BaseException) -> None: ...


class StageResult(Protocol):
    rc: int
    continued: bool
    reason: str
    terminal: RunState | None
    answer: RunFinish | None


class StageLifecycle(Protocol):
    def __call__(self, who: Identity, repo: str, mode: str, *, bundle: RunBundle,
                 events: bool, stores: StandaloneStores, log: RunLogPort) -> AbstractContextManager[StageResult]: ...


class Checkpoints(Protocol):
    def read(self) -> Checkpoint | None: ...
    def drop(self) -> None: ...
    def drop_unless_fenced(self) -> None: ...
    def save(self, *, step: str, stage: int) -> None: ...


class Resume(Protocol):
    def restore(self, ck: Checkpoint, *, late: bool) -> None: ...
    def point(self) -> tuple[PlanData | None, int, RoundState | None]: ...


class AskFlow(Protocol):
    def check(self) -> None: ...
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object: ...


class Briefs(Protocol):
    def export(self) -> None: ...


class Closer(Protocol):
    def pause(self, done: oc.RunOutcome) -> None: ...
    def apply(self, eff: effects.RaiseAsk, done: oc.RunOutcome, stats: str) -> None: ...


class Budget(Protocol):
    labels: list[str]


class Planner[T](Protocol):
    def plan(self, again: bool = False) -> T: ...
    def take(self, p: T) -> PlanData: ...


class Tree(Protocol):
    def reset(self, bead: Bead) -> object: ...


class Verifier(Protocol):
    def run(self, gaps: list[Open]) -> list[Open]: ...


class Review(Protocol):
    unchecked: list[Open]


class Steps(RecordSteps, Protocol):
    only: str | None


class Sessions(Protocol):
    def extend(self, values: Iterable[dict[str, object]], /) -> None: ...


class Context(Protocol):
    @property
    def who(self) -> Identity: ...
    @property
    def stores(self) -> StandaloneStores: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def fresh(self) -> bool: ...
    @property
    def moved(self) -> bool: ...
    @property
    def store(self) -> Beads: ...
    @property
    def claim(self) -> fence.Claim | None: ...
    @property
    def dry(self) -> bool: ...


class Cursor(Protocol):
    prev_ck: str
    last_run: CheckRun | None
    @property
    def state(self) -> CheckpointState: ...
    @property
    def checkpoints(self) -> Checkpoints: ...
    @property
    def steps(self) -> Steps: ...
    @property
    def resume(self) -> Resume: ...
    @property
    def replan_first(self) -> bool: ...


class Operations[T](Protocol):
    @property
    def budget(self) -> Budget: ...
    @property
    def ask_flow(self) -> AskFlow: ...
    @property
    def briefs(self) -> Briefs: ...
    @property
    def closer(self) -> Closer: ...
    @property
    def lander(self) -> Landing: ...
    @property
    def tree(self) -> Tree: ...
    @property
    def planner(self) -> Planner[T]: ...
    @property
    def verifier(self) -> Verifier: ...
    @property
    def review(self) -> Review: ...


class Values(Protocol):
    fenced: str
    bead_title: str
    bead_parent: str
    scope: str
    asked: bool
    landed_sha: str
    @property
    def sessions(self) -> Sessions: ...


class Journalling(RecordHost, CrashHost, Protocol):
    """Recording and crash capabilities used by standalone stages."""
