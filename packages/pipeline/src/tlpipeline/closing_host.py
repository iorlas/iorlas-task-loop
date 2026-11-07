"""What the Closer reads of the engine that is closing. CloseHost holds only what the Closer's own flow reads (the order of the steps, the
ledger of applied effects, the stop flag); every step it composes (the decision, the branch and the slot, the record, the notes and the
reflection, the settling of the bead) has its own host Protocol next to it, with just the members it calls. CloserHost is only their sum:
the Closer hands each step the host typed as that step's Protocol and never a wider one."""
import threading
from collections.abc import Mapping, Sequence
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
from tlkernel.pausereasons import Producer
from tlkernel.ports import Clock
from tlkernel.stagefacts import RunLogPort
from tlpipeline.closing_branch import BranchCheckpoints, BranchTree, ReleaseSlotHost, SaveBranchHost
from tlpipeline.closing_decide import DecideHost
from tlpipeline.closing_notes import FileNotesHost, NotesCheckpoints, ReflectCheckpoints, ReflectHost
from tlpipeline.closing_record import RecordHost, RecordRecords
from tlpipeline.closing_settle import SettleHost
from tlpipeline.ports import Slotting


class CloseCheckpoints(Protocol):
    def applied(self) -> frozenset[str]: ...
    def mark_applied(self, key: str) -> None: ...
    def keep_end(self, intent: CloseIntent) -> None: ...
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

    crash_fingerprint: str
    crash_site: str

    @property
    def store(self) -> Beads: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def bead(self) -> BeadId: ...
    plan_summary: str
    @property
    def log(self) -> RunLogPort: ...
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


class CloseAllCheckpoints(CloseCheckpoints, BranchCheckpoints, NotesCheckpoints, ReflectCheckpoints, Protocol):
    pass


class CloseTree(BranchTree, Slotting, Protocol):
    pass


class CloserHost(CloseHost, DecideHost, SaveBranchHost, ReleaseSlotHost, RecordHost,
                 FileNotesHost, ReflectHost, SettleHost, Protocol):
    """The engine, as the close reads it: the sum of the parts above (no member of its own but the one that joins them)."""

    @property
    def checkpoints(self) -> CloseAllCheckpoints: ...
    @property
    def tree(self) -> CloseTree: ...
