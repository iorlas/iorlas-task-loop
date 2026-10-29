"""Pick-time refusal (tl-7y6.7.2): the first time the loop skips a bead for failing lint, it labels the bead `needs-ac` and leaves one
comment naming the failed rules. A bead that already has the label, or that this loop already told about, gets nothing more."""
from collections.abc import Callable

from taskloop.contracts.bead import Bead
from taskloop.contracts.ports import BdFailure, Beads
from taskloop.domain.beads.rules import NEEDS_AC


class Refuser:
    def __init__(self, store: Beads, say: Callable[[str], None]) -> None:
        self.store, self.say = store, say
        self.told: set[str] = set()

    def refuse(self, bead: Bead, why: str) -> None:
        if bead.id in self.told:
            return
        self.told.add(bead.id)
        self.say(f"skip {bead.id}: {why}")
        if NEEDS_AC in bead.labels:
            return
        try:
            self.store.add_comment(bead.id, f"The loop will not take this bead: {why}. Fix the bead, then remove the {NEEDS_AC} label.")
            self.store.add_label(bead.id, NEEDS_AC)
        except BdFailure as e:
            self.say(f"could not mark {bead.id} {NEEDS_AC}: {e}")
