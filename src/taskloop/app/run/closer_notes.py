"""What a close leaves behind: the follow-ups filed and the landed work's notes (FileNotes), and the reflection comment."""
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from taskloop.adapters import beadtools
from taskloop.app.land.followups import FollowUpCheckpoints, FollowUpHost, file_follow_ups
from taskloop.app.run import outcomes
from taskloop.app.run.closer_branch import DONE
from taskloop.contracts.answers import VERDICTS
from taskloop.contracts.checkpoint import Notes
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.domain.review import followups as fu
from taskloop.stores.bundle import Stores


class NotesCheckpoints(FollowUpCheckpoints, Protocol):
    def keep_notes(self, notes: Notes) -> None: ...


class NotesOwnerLook(Protocol):
    def unverified_text(self) -> str: ...
    def file_owner_look(self) -> None: ...


class NotesJudge(Protocol):
    def is_look(self, u: Mapping[str, str]) -> bool: ...


class NotesPictures(Protocol):
    def keep_evidence(self) -> list[Path]: ...


class FileNotesHost(FollowUpHost, Protocol):
    """What filing the notes reads of the engine: what filing follow-ups reads (FollowUpHost), the asks, the unverified and unchecked
    items, the owner look, the judge and the pictures."""

    @property
    def stores(self) -> Stores: ...
    @property
    def unverified(self) -> Sequence[object]: ...
    @property
    def unchecked(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def owner_look(self) -> NotesOwnerLook: ...
    @property
    def judge(self) -> NotesJudge: ...
    @property
    def pictures(self) -> NotesPictures: ...
    @property
    def checkpoints(self) -> NotesCheckpoints: ...


class FileNotes:
    def __init__(self, host: FileNotesHost) -> None:
        self.e = host

    def run(self, outcome: Outcome) -> Notes:
        """The follow-ups filed; what was filed and what bd refused is kept in the checkpoint, where Reflect reads it."""
        e = self.e
        todo = len(fu.batch(e.bead, e.leftovers, e.filed).file)  # one per typed key, at most the cap
        lost = self.follow_ups(outcome)
        noted = Notes(filed=todo - len(lost), unfiled=len(lost))
        e.checkpoints.keep_notes(noted)
        return noted

    def follow_ups(self, outcome: Outcome) -> list[dict[str, str]]:
        """Landed work leaves its notes: the ask closed, the unverified items and the unchecked look items said, evidence kept, and each
        follow-up filed as a bead (what bd refuses is kept in the checkpoint, none lost)."""
        e = self.e
        if outcome in DONE:
            old = e.stores.asks.get(e.bead)
            if old:
                e.stores.asks.close(e.bead, old.id, "the run landed", time.time())
            if e.unverified:
                e.comment("Land (engine): " + e.owner_look.unverified_text())
            look = [u for u in e.unchecked if u["kind"] == "other" and not e.judge.is_look(u)]
            if look:
                beadtools.attempt(e.store.add_label, e.bead, "needs-owner-check")
                e.comment("Look (engine): landed, but nobody checked: " + "; ".join(u["what"] for u in look))
        shots = e.pictures.keep_evidence()
        if shots:
            e.comment("Evidence (engine): " + ", ".join(str(p) for p in shots))
        lost = file_follow_ups(e)
        if outcome is Outcome.LANDED:
            e.owner_look.file_owner_look()
        return lost


class ReflectCheckpoints(Protocol):
    def notes(self) -> Notes | None: ...


class ReflectHost(Protocol):
    """What the reflection comment reads of the engine: the bead, the reflection and the self-verified items, the checkpoint's notes,
    the run's id (its log path) and the comment."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def reflection(self) -> Mapping[str, object] | None: ...
    @property
    def verified(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def run_id(self) -> str: ...
    @property
    def checkpoints(self) -> ReflectCheckpoints: ...
    def comment(self, text: str) -> None: ...


class Reflect:
    def __init__(self, host: ReflectHost) -> None:
        self.e = host

    def comment(self, outcome: Outcome, why: str, stats: str, noted: Notes | None) -> None:
        e = self.e
        notes = e.checkpoints.notes() or noted or Notes(filed=0, unfiled=0)  # the checkpoint's: a restart has no memory of FileNotes
        verified = ""
        if e.verified:
            verified = "; self-verified=" + ", ".join("{} {}".format(sum(x["verdict"] == k for x in e.verified), k) for k in VERDICTS)
        unfiled = f" unfiled={notes.unfiled};" if notes.unfiled else ""
        text = outcomes.reflection_text(e.reflection)
        e.comment(f"Reflect (engine): outcome={outcome};{text} filed={notes.filed};{unfiled} {stats}"
                  f"{verified}{('; why=' + why) if why else ''}; trace={e.run_id} (tl trace {e.bead})")
