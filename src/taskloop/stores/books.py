"""Logic over a DocSet that real and fake share, so the two cannot differ: checkpoints."""
import dataclasses

from taskloop.contracts.checkpoint import Checkpoint, Unfiled
from taskloop.stores.api import Doc, DocSet


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
