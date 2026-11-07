"""Bead close and block verbs bound to an actor, store and close guard."""
from collections.abc import Callable

from tlkernel import fence
from tlkernel.beadsport import Beads
from tlkernel.identity import Identity

from taskloop.app.track import verbs
from taskloop.app.track.verbs import Guard


class ClosingBeads:
    def __init__(self, who: Identity, store: Beads, guard: Guard) -> None:
        self.who, self.store, self.guard = who, store, guard

    def close(self, claim: fence.Claim, reason: str | None) -> int:
        return verbs.close_as(self.who, claim, reason, self.store, self.guard)

    def block(self, claim: fence.Claim, why: str, say: Callable[[str], None] | None = None) -> int:
        return verbs.block_as(self.who, claim, why, self.store, say)
