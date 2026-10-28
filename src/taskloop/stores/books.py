"""Logic over a DocSet that real and fake share, so the two cannot differ: checkpoints (read here; app/run/state.py writes)."""
from taskloop.contracts.checkpoint import Checkpoint
from taskloop.stores.api import Doc, DocSet


class CheckpointBook:
    """checkpoints/<bead>: `Checkpoints` (app/run/state.py) is the one writer; the dashboard and resume read."""

    def __init__(self, docs: DocSet[Checkpoint]) -> None:
        self.docs = docs

    def of(self, bead: str) -> Doc[Checkpoint]:
        return self.docs.of(bead)

    def open_beads(self) -> list[str]:
        """Beads whose checkpoint is not closed: the runs that can resume."""
        return sorted(k for k in self.docs.keys() if (c := self.docs.of(k).read()) is not None and not c.closed)
