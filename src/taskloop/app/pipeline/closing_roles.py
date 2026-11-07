"""Roles used by the close flow; steps declare their own protocols."""
import threading
from collections.abc import Mapping
from typing import Protocol

from tlkernel import fence
from tlkernel import runoutcome as oc
from tlkernel.askspec import AskSpec
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Checkpoint, CloseIntent
from tlkernel.delegate import Permanence
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.ports import Clock
from tlkernel.stagefacts import RunLogPort

from taskloop.app.pipeline.closing_record import RecordRecords
from taskloop.domain.lanes.pause_reasons import Producer


class CloseCheckpoints(Protocol):
    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...
    def keep_end(self, intent: CloseIntent) -> None: ...
    def drop_unless_fenced(self) -> None: ...

class CloseAskFlow(Protocol):
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object: ...

class CloseState(Protocol):
    """Mutable decision and pause facts shared with the close steps."""

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

class CloseResources(Protocol):
    """Run resources used to persist and apply the close."""

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
    def halt(self) -> threading.Event: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...




class CloseReport(Protocol):
    """Statistics and diagnostics for the close."""

    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def cost(self) -> float: ...
    @property
    def t0(self) -> float: ...
    def warn(self, text: str) -> None: ...
