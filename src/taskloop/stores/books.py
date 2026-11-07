"""Logic over a DocSet that real and fake share, so the two cannot differ: checkpoints (read here; app/run/state.py writes)."""
from taskloop.stores.api import AmendDoc, AmendSet
from tlkernel.checkpoint import Checkpoint


class CheckpointBook:
    """checkpoints/<bead>: `Checkpoints` (app/run/state.py) is the one writer; the dashboard and resume read."""

    def __init__(self, docs: AmendSet[Checkpoint]) -> None:
        self.docs = docs

    def of(self, bead: str) -> AmendDoc[Checkpoint]:
        return self.docs.of(bead)

    def open_beads(self) -> list[str]:
        """Beads whose checkpoint is not closed: the runs that can resume."""
        keys = self.docs.keys()  # a DocSet is not iterable: it has keys()
        return sorted(k for k in keys if (c := self.docs.of(k).get()) is not None and not c.closed)
