"""Roles used by the close flow; each is passed independently by the root binder."""
from collections.abc import Mapping
from typing import Protocol

from tlkernel import fence
from tlkernel import runoutcome as oc
from tlkernel.askspec import AskSpec
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Checkpoint
from tlkernel.delegate import Permanence
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.pausereasons import Producer
from tlkernel.ports import Clock
from tlkernel.stagefacts import RunLogPort
from tlpipeline.closing_record import RecordRecords


class CloseStop(Protocol):
    def clear(self) -> None: ...


class CloseCheckpoints(Protocol):
    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...
    def drop_unless_fenced(self) -> None: ...


class CloseAskFlow(Protocol):
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object: ...


class CloseState(Protocol):
    disp: oc.Disposition | None
    kind: Kind
    fp: str
    asked: bool
    dead: Checkpoint | None  # the checkpoint of a run that died inside its close (its outcome kept, a key unapplied), else None
    retry_after: float
    pause_reason: str
    pause_producer: Producer
    pause_permanence: Permanence | None
    why: str
    crash_fingerprint: str
    crash_site: str
    plan_summary: str


class CloseRuntime(Protocol):
    @property
    def store(self) -> Beads: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def bead(self) -> BeadId: ...
    @property
    def log(self) -> RunLogPort: ...
    @property
    def dry(self) -> bool: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def run_id(self) -> str: ...
    @property
    def checkpoints(self) -> CloseCheckpoints: ...
    @property
    def records(self) -> RecordRecords: ...
    @property
    def ask_flow(self) -> CloseAskFlow: ...
    @property
    def halt(self) -> CloseStop: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def warn(self, text: str) -> None: ...


class CloseStats(Protocol):
    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def cost(self) -> float: ...
    @property
    def t0(self) -> float: ...
