"""What a close leaves behind: the follow-ups filed and the landed work's notes (FileNotes), and the reflection comment."""
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from tlkernel import followkeys as fu
from tlkernel.answers import VERDICTS
from tlkernel.beadsport import Beads
from tlkernel.checkpoint import Notes
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlpipeline import outcomes
from tlpipeline.adapter_ports import Attempt
from tlpipeline.outcomes import DONE
from tlpipeline.ports import FollowUps
from tlpipeline.store_ports import NotesStores


class NotesCheckpoints(Protocol):
    def keep_pending(self, origin: str = ...) -> None: ...
    def keep_notes(self, notes: Notes) -> None: ...


class NotesOwnerLook(Protocol):
    def unverified_text(self) -> str: ...
    def file_owner_look(self) -> None: ...


class NotesJudge(Protocol):
    def is_look(self, u: Mapping[str, str]) -> bool: ...


class NotesPictures(Protocol):
    def keep_evidence(self) -> list[Path]: ...


class NotesReview(Protocol):
    """The engine's `review` as the notes read it: what is left for the owner, what nobody checked, what the verifier answered."""

    @property
    def unverified(self) -> Sequence[object]: ...
    @property
    def unchecked(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def verified(self) -> Sequence[Mapping[str, str]]: ...


class FileNotesHost(Protocol):
    """What filing the notes reads of the engine: the follow-up batch, the asks, the unverified and unchecked
    items, the owner look, the judge and the pictures."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def leftovers(self) -> Sequence[Mapping[str, str]]: ...
    @property
    def filed(self) -> list[str]: ...
    @property
    def store(self) -> Beads: ...
    def comment(self, text: str) -> None: ...
    def warn(self, text: str) -> None: ...

    @property
    def stores(self) -> NotesStores: ...
    @property
    def review(self) -> NotesReview: ...
    @property
    def owner_look(self) -> NotesOwnerLook: ...
    @property
    def judge(self) -> NotesJudge: ...
    @property
    def pictures(self) -> NotesPictures: ...
    @property
    def checkpoints(self) -> NotesCheckpoints: ...


class FileNotes:
    def __init__(self, context: FileNotesHost, follow_ups: FollowUps, attempt: Attempt) -> None:
        self.host = context
        self.attempt = attempt
        self.follow_ups_port = follow_ups

    def run(self, outcome: Outcome) -> Notes:
        """File from the durable queue; Reflect reads the counts from the checkpoint and refused work stays in the outbox."""
        host = self.host
        host.checkpoints.keep_pending()
        todo = len(fu.batch(host.bead, host.leftovers, host.filed).file)  # one per typed key, at most the cap
        lost = self.follow_ups(outcome)
        if lost:
            host.warn(f"required follow-up filing incomplete: {len(lost)} item(s) remain in the durable outbox for retry")
        noted = Notes(filed=todo - len(lost), unfiled=len(lost))
        host.checkpoints.keep_notes(noted)
        return noted

    def follow_ups(self, outcome: Outcome) -> list[dict[str, str]]:
        """Landed work leaves its notes: the ask closed, the unverified items and the unchecked look items said, evidence kept, and each
        follow-up filed as a bead (what bd refuses stays in the bead's durable outbox)."""
        host = self.host
        if outcome in DONE:
            old = host.stores.asks.get(host.bead)
            if old:
                host.stores.asks.close(host.bead, old.id, "the run landed", time.time())
            if host.review.unverified:
                host.comment("Land (engine): " + host.owner_look.unverified_text())
            look = [u for u in host.review.unchecked if u["kind"] == "other" and not host.judge.is_look(u)]
            if look:
                self.attempt(host.store.add_label, host.bead, "needs-owner-check")
                host.comment("Look (engine): landed, but nobody checked: " + "; ".join(u["what"] for u in look))
        shots = host.pictures.keep_evidence()
        if shots:
            host.comment("Evidence (engine): " + ", ".join(str(p) for p in shots))
        lost = self.follow_ups_port.file()
        if outcome is Outcome.LANDED:
            host.owner_look.file_owner_look()
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
    def review(self) -> NotesReview: ...
    @property
    def run_id(self) -> str: ...
    @property
    def checkpoints(self) -> ReflectCheckpoints: ...
    def comment(self, text: str) -> None: ...


class Reflect:
    def __init__(self, host: ReflectHost) -> None:
        self.host = host

    def comment(self, outcome: Outcome, why: str, stats: str, noted: Notes | None) -> None:
        host = self.host
        notes = host.checkpoints.notes() or noted or Notes(filed=0, unfiled=0)  # the checkpoint's: a restart has no memory of FileNotes
        verified = ""
        if host.review.verified:
            verified = "; self-verified=" + ", ".join(
                "{} {}".format(sum(x["verdict"] == k for x in host.review.verified), k) for k in VERDICTS)
        unfiled = f" unfiled={notes.unfiled};" if notes.unfiled else ""
        text = outcomes.reflection_text(host.reflection)
        host.comment(f"Reflect (engine): outcome={outcome};{text} filed={notes.filed};{unfiled} {stats}"
                  f"{verified}{('; why=' + why) if why else ''}; trace={host.run_id} (tl trace {host.bead})")
