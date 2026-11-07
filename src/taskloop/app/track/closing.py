"""Bead close and block verbs bound to an actor, store and close guard."""
from collections.abc import Callable

from taskloop.app.track import trail, verbs
from taskloop.app.track.verbs import Guard
from taskloop.contracts import fence
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.identity import Identity


class ClosingBeads:
    def __init__(self, who: Identity, store: Beads, guard: Guard) -> None:
        self.who, self.store, self.guard = who, store, guard

    def close(self, claim: fence.Claim, reason: str | None) -> int:
        return verbs.close_as(self.who, claim, reason, self.store, self.guard)

    def block(self, claim: fence.Claim, why: str, say: Callable[[str], None] | None = None) -> int:
        return verbs.block_as(self.who, claim, why, self.store, say)


class TrailEvents:
    def event(self, by: Identity, kind: str, bead: str, **fields: str) -> None:
        trail.event(by, kind, bead, **fields)
