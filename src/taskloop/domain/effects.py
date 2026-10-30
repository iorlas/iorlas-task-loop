"""The close of a run as a list of effects: `plan_close` is pure, `key_of` names each effect once, an interpreter (app/run/interpret.py)
applies them.

What a run does when it ends (save the branch, write the log and trace, raise the ask, file the notes, close or block or free the bead,
release the slot) is one `Effect` each, in one order. The list depends on the outcome and the dry flag only. An effect is applied once
per (bead, run, kind): the interpreter records the key after the effect ran, so a kill between two effects resumes at the first
unapplied one and repeats none. Stdlib only; imports outcome, never app.
"""
from dataclasses import dataclass
from typing import Final, assert_never, final

from taskloop.domain import outcome as oc


@final
@dataclass(frozen=True)
class SaveBranch:
    """The wip commit and the closed checkpoint of an unfinished branch."""


@final
@dataclass(frozen=True)
class RecordRun:
    """The run's log and trace: the close node, the reflection."""


@final
@dataclass(frozen=True)
class NoteDry:
    """A dry run touches no bead: it says so."""


@final
@dataclass(frozen=True)
class NoteWait:
    """An ask is still open: the bead stays as the ask left it, the run says why."""


@final
@dataclass(frozen=True)
class RaiseAsk:
    """The owner's one question."""


@final
@dataclass(frozen=True)
class FileNotes:
    """Landed work leaves its notes; each follow-up is filed as a bead."""


@final
@dataclass(frozen=True)
class Reflect:
    """The engine's reflection comment on the bead."""


@final
@dataclass(frozen=True)
class CloseBead:
    """bd close, under the run's claim (the fenced close)."""
    landed: bool  # merged to the base (else: done with nothing to land)


@final
@dataclass(frozen=True)
class BlockBead:
    """The bead blocked on the owner's question, under the run's claim."""


@final
@dataclass(frozen=True)
class LeaveBead:
    """A machine fault, a pause or the owner's hold: the bead is open and unassigned again."""


@final
@dataclass(frozen=True)
class ReleaseSlot:
    """The slot back at the base, only while this run's slot generation is still the lease's."""
    branch: str
    slot_gen: int


Effect = SaveBranch | RecordRun | NoteDry | NoteWait | RaiseAsk | FileNotes | Reflect | CloseBead | BlockBead | LeaveBead | ReleaseSlot

NAMES: Final = {
    SaveBranch: "save_branch", RecordRun: "record_run", NoteDry: "note_dry", NoteWait: "note_wait", RaiseAsk: "raise_ask",
    FileNotes: "file_notes", Reflect: "reflect", CloseBead: "close_bead", BlockBead: "block_bead", LeaveBead: "leave_bead",
    ReleaseSlot: "release_slot",
}


def name_of(effect: Effect) -> str:
    """The effect kind in a key."""
    match effect:
        case (SaveBranch() | RecordRun() | NoteDry() | NoteWait() | RaiseAsk() | FileNotes() | Reflect() | CloseBead()
              | BlockBead() | LeaveBead() | ReleaseSlot()):
            return NAMES[type(effect)]
        case _:
            assert_never(effect)


def key_of(bead: str, run: str, effect: Effect) -> str:
    """One effect of one run on one bead is applied once: this is its key."""
    return f"{bead}/{run}/{name_of(effect)}"


def settling(done: oc.RunOutcome) -> CloseBead | BlockBead | LeaveBead:
    """What happens to the bead: one effect per Fault variant (None: a finish)."""
    match done.fault:
        case None:
            return CloseBead(landed=done.kind is oc.Kind.LANDED)
        case oc.Infra() | oc.Owner():
            return LeaveBead()
        case oc.Task():
            return BlockBead()
        case fault:
            assert_never(fault)


def plan_close(done: oc.RunOutcome, *, dry: bool, branch: str, slot_gen: int) -> list[Effect]:
    """The effects that end a run, in order. `done` is the final outcome (after POLICY and any escalation)."""
    head: list[Effect] = [SaveBranch(), RecordRun()]
    if dry:
        return [*head, NoteDry()]
    release = ReleaseSlot(branch, slot_gen)
    if done.kind is oc.Kind.WAIT_ASK:
        return [*head, NoteWait(), release]
    ask: list[Effect] = [RaiseAsk()] if done.kind in oc.ASKS and done.spec is not None else []
    return [*head, *ask, FileNotes(), Reflect(), settling(done), release]
