"""What the Closer reads of the engine that is closing. CloseHost holds only what the Closer's own flow reads (the order of the steps, the
ledger of applied effects, the stop flag); every step it composes (the decision, the branch and the slot, the record, the notes and the
reflection, the settling of the bead) has its own host Protocol next to it, with just the members it calls. CloserHost is only their sum:
the Closer hands each step the host typed as that step's Protocol and never a wider one."""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from taskloop.app.run.closer_branch import BranchCheckpoints, BranchTree, LeaveTree, ReleaseSlotHost, SaveBranchHost
from taskloop.app.run.closer_decide import DecideHost
from taskloop.app.run.closer_notes import FileNotesHost, NotesCheckpoints, ReflectCheckpoints, ReflectHost
from taskloop.app.run.closer_record import RecordHost
from taskloop.app.run.closer_settle import SettleHost
from taskloop.contracts import fence
from taskloop.contracts.checkpoint import Checkpoint, EndRec
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec
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

    @property
    def bead(self) -> BeadId: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def stats(self) -> Mapping[str, int]: ...
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def dry(self) -> bool: ...
    @property
    def claim(self) -> fence.Claim: ...
    @property
    def log_path(self) -> Path: ...
    @property
    def checkpoints(self) -> CloseCheckpoints: ...
    @property
    def ask_flow(self) -> CloseAskFlow: ...
    @property
    def cost(self) -> float: ...
    @property
    def t0(self) -> float: ...
    @property
    def halt(self) -> threading.Event: ...
    def git(self, *args: str) -> str: ...
    def warn(self, text: str) -> None: ...


class CloseAllCheckpoints(CloseCheckpoints, BranchCheckpoints, NotesCheckpoints, ReflectCheckpoints, Protocol):
    pass


class CloseTree(BranchTree, LeaveTree, Protocol):
    pass


class CloserHost(CloseHost, DecideHost, SaveBranchHost, ReleaseSlotHost, RecordHost, FileNotesHost, ReflectHost, SettleHost, Protocol):
    """The engine, as the close reads it: the sum of the parts above (no member of its own but the one that joins them)."""

    @property
    def checkpoints(self) -> CloseAllCheckpoints: ...
    @property
    def tree(self) -> CloseTree: ...
