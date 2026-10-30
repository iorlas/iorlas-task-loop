"""The fence: what lets a run act on its bead. A `Claim` is the proof that this run took the bead (and its slot) at a lease generation;
only `take`, `hand` and `offline` below make one. Every take bumps the generation, kept in bd's metadata (the bead's `fence_gen`, the
slot bead's `held_gen`), so a run whose lease lapsed and was retaken, or a second run on the same bead, holds a generation that is
no longer the current one: `check` refuses it with the reason, and close, block, land and the checkpoint writes call `check` first."""
from typing import final

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads

BEAD_GEN = "fence_gen"
SLOT_GEN = "held_gen"  # never cleared with the slot's holder marks: a retake after a release must still be a higher number


def peek(store: Beads, bead_id: BeadId) -> Bead | None:
    """The bead, None when it is not there or bd could not be asked."""
    try:
        return store.show(bead_id)
    except BdFailure:
        return None


class Fenced(Exception):
    """A write by a run that no longer holds its bead or slot. `why` says which and since when."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


class _Key:
    """Held by this module alone: the one argument a Claim's constructor insists on."""


_KEY = _Key()


@final
class Claim:
    """A run's right to act on `bead`: the generation it took, the actor it took it as, and its slot's generation. Made by
    `take` / `hand` / `offline` only (the constructor refuses any other caller)."""

    __slots__ = ("actor", "bead", "gen", "slot_bead", "slot_gen")

    def __init__(self, key: _Key, bead: BeadId, actor: str, gen: int, slot_bead: BeadId | None, slot_gen: int) -> None:
        if key is not _KEY:
            raise TypeError("a Claim is made by fence.take, fence.hand or fence.offline")
        self.bead, self.actor, self.gen, self.slot_bead, self.slot_gen = bead, actor, gen, slot_bead, slot_gen

    def __repr__(self) -> str:
        return f"Claim({self.bead} gen {self.gen} as {self.actor or '-'}, slot {self.slot_bead or '-'} gen {self.slot_gen})"

    @property
    def fenced(self) -> bool:
        """False for `offline`: there is no generation to check."""
        return self.gen >= 0


def gen_of(b: Bead | None, key: str = BEAD_GEN) -> int:
    try:
        return int(b.metadata.get(key) or 0) if b else 0
    except (TypeError, ValueError):
        return 0


def offline(bead: BeadId) -> Claim:
    """A dry run, or a test's engine: nothing in bd to check, so nothing is refused."""
    return Claim(_KEY, bead, "", -1, None, -1)


def take(store: Beads, bead: BeadId, actor: str, slot_bead: BeadId | None = None, slot_gen: int | None = None) -> Claim:
    """The run's claim, made right after bd gave it the bead: the bead's generation is bumped. `slot_gen`: the slot's generation the
    run noted when it took the slot (None: read now)."""
    gen = gen_of(peek(store, bead)) + 1
    store.update(bead, BeadPatch(set_metadata={BEAD_GEN: str(gen)}))
    if slot_gen is None:
        slot_gen = gen_of(peek(store, slot_bead), SLOT_GEN) if slot_bead else 0
    return Claim(_KEY, bead, actor, gen, slot_bead, slot_gen)


def hand(store: Beads, bead: BeadId, actor: str) -> Claim:
    """A person's `tl close` / `tl block`: the bead as it stands (no bump). The assignee guard applies only to a bead this actor holds."""
    b = peek(store, bead)
    return Claim(_KEY, bead, actor if b is not None and b.assignee == actor else "", gen_of(b), None, 0)


def stale(store: Beads, c: Claim) -> str:
    """Why this claim is no longer the current one, "" while it is (or when bd cannot be asked: a bd outage fences nothing)."""
    if not c.fenced:
        return ""
    b = peek(store, c.bead)
    if b is not None and gen_of(b) != c.gen:
        return f"{c.bead} was taken again by another run (generation {gen_of(b)}, this run holds {c.gen})"
    if c.slot_bead:
        sb = peek(store, c.slot_bead)
        if sb is not None and gen_of(sb, SLOT_GEN) != c.slot_gen:
            return f"slot bead {c.slot_bead} was taken again (generation {gen_of(sb, SLOT_GEN)}, this run holds {c.slot_gen})"
    return ""


def check(store: Beads, c: Claim) -> None:
    why = stale(store, c)
    if why:
        raise Fenced(why)


def guard(c: Claim) -> str:
    """The `--if-assignee` for a write under this claim: the actor that took it."""
    return c.actor


