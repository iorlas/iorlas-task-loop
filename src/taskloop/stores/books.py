"""Logic over a DocSet that real and fake share, so the two cannot differ: asks and checkpoints."""
import dataclasses

from taskloop.contracts.ask import Ask, AskAnswer
from taskloop.contracts.checkpoint import Checkpoint, Unfiled
from taskloop.contracts.enums import AskStatus
from taskloop.stores.api import Doc, DocSet

LIVE = (AskStatus.OPEN, AskStatus.PARKED)


class AskBook:
    """asks/<bead>: the engine raises, tl sweeps, the dashboard answers; one record per bead."""

    def __init__(self, docs: DocSet[Ask]) -> None:
        self.docs = docs

    def of(self, bead: str) -> Doc[Ask]:
        return self.docs.of(bead)

    def live(self) -> list[Ask]:
        """Asks still waiting for an owner (open or parked), oldest first."""
        out = [a for a in (self.docs.of(k).read() for k in self.docs.keys()) if a is not None and a.status in LIVE]
        return sorted(out, key=lambda a: a.t)

    def answer(self, bead: str, answer: AskAnswer) -> Ask | None:
        """Record the owner's answer on a live ask; None when there is none to answer. The one write the dashboard makes."""
        doc = self.docs.of(bead)
        ask = doc.read()
        if ask is None or ask.status not in LIVE:
            return None
        done = dataclasses.replace(ask, status=AskStatus.ANSWERED, answer=answer, answered=answer.t)  # pyrefly: ignore[bad-specialization]
        doc.write(done)
        return done

    def withdraw(self, bead: str) -> bool:
        doc = self.docs.of(bead)
        ask = doc.read()
        if ask is None or ask.status not in LIVE:
            return False
        doc.write(dataclasses.replace(ask, status=AskStatus.WITHDRAWN))  # pyrefly: ignore[bad-specialization]
        return True


class CheckpointBook:
    """checkpoints/<bead>: RunState is the one writer; the dashboard and resume read."""

    def __init__(self, docs: DocSet[Checkpoint]) -> None:
        self.docs = docs

    def of(self, bead: str) -> Doc[Checkpoint]:
        return self.docs.of(bead)

    def close(self, bead: str) -> Checkpoint | None:
        """The close step committed everything: mark the checkpoint closed. None when there is none."""
        doc = self.docs.of(bead)
        ck = doc.read()
        if ck is None:
            return None
        done = dataclasses.replace(ck, closed=True)  # pyrefly: ignore[bad-specialization]
        doc.write(done)
        return done

    def add_unfiled(self, bead: str, lost: list[Unfiled], filed: list[str]) -> Checkpoint | None:
        """Follow-ups bd refused are kept next to the ones it took, none lost or counted twice."""
        doc = self.docs.of(bead)
        ck = doc.read()
        if ck is None:
            return None
        done = dataclasses.replace(ck, filed=list(filed), unfiled=[*ck.unfiled, *lost])  # pyrefly: ignore[bad-specialization]
        doc.write(done)
        return done

    def open_beads(self) -> list[str]:
        """Beads whose checkpoint is not closed: the runs that can resume."""
        return sorted(k for k in self.docs.keys() if (c := self.docs.of(k).read()) is not None and not c.closed)
