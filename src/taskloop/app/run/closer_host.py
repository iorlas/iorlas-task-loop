"""What the Closer reads of the engine that is closing. CloseHost holds only what the Closer's own flow reads (the order of the steps, the
ledger of applied effects, the stop flag); every step it composes (the decision, the branch and the slot, the record, the notes and the
reflection, the settling of the bead) has its own host Protocol next to it, with just the members it calls. CloserHost is only their sum:
the Closer hands each step the host typed as that step's Protocol and never a wider one."""
import threading
from collections.abc import Mapping, Sequence
from typing import Protocol

from taskloop.app.land.followups import FollowUpCheckpoints, FollowUpHost
from taskloop.app.pipeline.closing_decide import DecideHost
from taskloop.app.pipeline.closing_notes import FileNotesHost, NotesCheckpoints, ReflectCheckpoints, ReflectHost
from taskloop.app.pipeline.closing_settle import SettleHost
from taskloop.app.run.closer_branch import BranchCheckpoints, BranchTree, LeaveTree, ReleaseSlotHost, SaveBranchHost
from taskloop.app.run.closer_record import RecordHost, RecordRecords
from taskloop.contracts import fence
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.checkpoint import Checkpoint, EndRec
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.gitport import Git
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Clock
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.lanes.pause_reasons import Producer
from taskloop.stores.runlog import RunLog


class CloseCheckpoints(Protocol):
    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...
    def keep_end(self, end: EndRec) -> None: ...
    def drop_unless_fenced(self) -> None: ...


class CloseAskFlow(Protocol):
    def raise_ask(self, spec: AskSpec, why: str, kind: Kind) -> object: ...


class CloseHost(Protocol):
    """The Closer's own flow: the decision's results it passes on, the checkpoint's ledger and end record, the ask, the stop flag."""

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

    @property
    def crash_fingerprint(self) -> str: ...
    @property
    def crash_site(self) -> str: ...

    @property
    def home(self) -> ConfigDir: ...
    @property
    def store(self) -> Beads: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def bead(self) -> BeadId: ...
    @property
    def plan_summary(self) -> str: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def sessions(self) -> Sequence[Mapping[str, str]]: ...
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
    def cost(self) -> float: ...
    @property
    def t0(self) -> float: ...
    @property
    def halt(self) -> threading.Event: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    def warn(self, text: str) -> None: ...


class CloseAllCheckpoints(CloseCheckpoints, BranchCheckpoints, NotesCheckpoints, ReflectCheckpoints, FollowUpCheckpoints, Protocol):
    pass


class CloseTree(BranchTree, LeaveTree, Protocol):
    pass


class CloserHost(FollowUpHost, CloseHost, DecideHost, SaveBranchHost, ReleaseSlotHost, RecordHost,
                 FileNotesHost, ReflectHost, SettleHost, Protocol):
    """The engine, as the close reads it: the sum of the parts above (no member of its own but the one that joins them)."""

    @property
    def checkpoints(self) -> CloseAllCheckpoints: ...
    @property
    def tree(self) -> CloseTree: ...
