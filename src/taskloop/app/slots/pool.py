"""The slots of one repo on this machine: a slot is a worktree plus its bd bead, which is the lease. `Slot.take`, `ready_for`
and `release` fail with a SlotFail (slot_broken, bead_pinned or busy); the pool takes the first free one."""
from pathlib import Path

from taskloop.app.slots.env import SlotEnv, peek, stamp
from taskloop.app.slots.marks import clear_marks, held_by, hold_of, hold_until, mark_held
from taskloop.app.slots.reset import ready_for
from taskloop.contracts.bead import Bead
from taskloop.contracts.ports import BdFailure, BeadQuery
from taskloop.contracts.slots import Hold, SlotFail


class Slot:
    def __init__(self, pool: "SlotPool", name: str, bead: Bead) -> None:
        self.pool, self.name, self.bead = pool, name, bead
        self.env = pool.env
        self.dir = pool.env.dir_of(name)

    def hold(self) -> Hold | None:
        return hold_of(self.bead, self.env.now())

    def free_reason(self) -> str:
        """Why this slot cannot be taken now, "" when it can: a hold, a claim, or a live engine in its worktree."""
        hold = self.hold()
        if hold:
            return "held by %s since %s until %s: %s (tl slot release %s ends it)" % (
                hold.by, hold.since, stamp(hold.until), hold.why, self.name)
        if self.bead.status != "open":
            return "held by %s" % held_by(self.bead)
        busy = self.env.busy(self.dir)
        return "busy: %s" % busy if busy else ""

    def claimed(self) -> bool:
        """True when this session won the slot bead's claim."""
        st = self.env.store
        return st.claim(self.bead.id) and ((peek(st, self.bead.id) or Bead(id=self.bead.id, title="", status="")).assignee
                                           or self.env.actor) == self.env.actor

    def take_locked(self, why: str, bead: str = "", ticket: int | None = None) -> str:
        """The slot bead's id once this session holds the slot; the caller holds the repo's take lock. Fails busy."""
        why_not = self.free_reason()
        if why_not:
            raise SlotFail("busy", "slot %s %s" % (self.name, why_not))
        if not self.claimed():
            raise SlotFail("busy", "slot %s held by %s" % (self.name, held_by(peek(self.env.store, self.bead.id) or self.bead)))
        mark_held(self.env, self.bead.id, why, bead=bead)
        self.env.event("slot-take", "", slot=self.name, slot_bead=self.bead.id, worktree=self.dir, repo=self.env.repo,
                       **({"ticket": ticket} if ticket is not None else {}))
        return self.bead.id

    def take(self, why: str, bead: str = "") -> str:
        """Take this slot by name. A held slot bead is refused even when this session's actor holds it (two hand runs of
        one session share its actor, and bd lets an actor re-claim its own bead); a hold too, its holder's own included."""
        with self.env.take_lock():
            self.pool.free_expired()
            fresh = self.pool.bead(self.name)
            if fresh is None:
                raise SlotFail("slot_broken", "no slot %s on %s (tl slot list)" % (self.name, self.env.host))
            return Slot(self.pool, self.name, fresh).take_locked(why, bead)

    def ready_for(self, bead: str, *, force: bool = False) -> None:
        """A clean tree on the bead's branch, leftover work committed (never wiped); see reset.py."""
        ready_for(self, bead, force=force)

    def release(self, bead: str | None = None, *, mine: bool = False, force: bool = False) -> bool:
        """Free the slot. mine=True (a run ending): only while the slot's marks still name this actor (and `bead`, when it
        is marked): a slot reclaimed and retaken is the new holder's, left alone. False when there is no such slot."""
        with self.env.take_lock():
            return self.release_locked(bead, mine, force)

    def release_locked(self, bead: str | None, mine: bool, force: bool) -> bool:
        b = self.pool.bead(self.name)
        if b is None:
            return False
        if mine:
            m = b.metadata
            if m.get("held_by") != self.env.actor or (bead is not None and m.get("held_bead") not in (None, "", bead)):
                self.env.warn("tl: slot %s is no longer held by %s%s (now %s): left alone" % (
                    self.name, self.env.actor, " for " + bead if bead else "", held_by(b) if b.status != "open" else "free"))
                return True
        # the holder's marks go first, while the bead is still claimed: unclaimed first, a hold taken in between would lose
        # its marks to this clean-up (race test, tl-bxk.11.1)
        clear_marks(self.env, b.id)
        self.pool.unclaim(b, force)
        self.env.event("slot-release", "", slot=self.name, slot_bead=b.id, repo=self.env.repo)
        return True


class SlotPool:
    def __init__(self, env: SlotEnv) -> None:
        self.env = env

    def beads(self) -> list[Bead]:
        """This machine's slot beads (title `slot <host> <name>`): a lease is local to one machine's bd."""
        try:
            found = self.env.store.find(BeadQuery(label="slot", include_closed=True))
        except BdFailure:
            return []
        return sorted((b for b in found if b.status != "closed" and b.title.split()[1:2] == [self.env.host]), key=lambda b: b.title)

    def slots(self) -> list[Slot]:
        return [Slot(self, b.title.split()[-1], b) for b in self.beads()]

    def bead(self, name: str) -> Bead | None:
        return next((b for b in self.beads() if b.title.split()[-1] == name), None)

    def slot(self, name: str) -> Slot:
        b = self.bead(name)
        if b is None:
            raise SlotFail("slot_broken", "no slot %s on %s (tl slot list)" % (name, self.env.host))
        return Slot(self, name, b)

    def named(self, name: str) -> Slot:
        """The slot `name` for a reset or a setup, which need only its worktree: no bead (id "") when bd has none."""
        b = self.bead(name)
        return Slot(self, name, b or Bead(id="", title="slot %s %s" % (self.env.host, name), status=""))

    def name_of(self, wt: str) -> str:
        """The slot whose worktree `wt` is, or ""."""
        here = Path(wt).resolve()
        return next((s.name for s in self.slots() if Path(s.dir).resolve() == here), "")

    def unclaim(self, b: Bead, force: bool = False) -> None:
        """Give a slot bead back. `bd unclaim` frees only the caller's own claim: a slot claimed by a loop's actor and held
        by one of its runs (or a dead loop's) stayed in_progress after `slot release --force` / an expired hold (0.23.34)."""
        if not self.env.store.unclaim(b.id) and force:
            self.env.store.unclaim(b.id, force=True)

    def take_any(self, why: str, bead: str = "", ticket: int | None = None) -> tuple[str, str, str] | None:
        """(name, dir, slot bead) of the first free slot this session could claim, or None. A waiter goes through
        TicketQueue.wait, which takes its turn in the line first; `ticket` is its number, kept on the take's event."""
        with self.env.take_lock():
            self.free_expired()
            for slot in self.slots():
                try:
                    return slot.name, slot.dir, slot.take_locked(why, bead, ticket)
                except SlotFail:
                    continue
        return None

    def free_expired(self) -> None:
        """An expired hold gives its slot bead back (the holder's claim with it), so the slot is free at once. Takes no lock:
        the caller holds the take lock, so a stale look never wipes a slot another session took meanwhile."""
        for b in self.beads():
            if hold_until(b) and not hold_of(b, self.env.now()):
                clear_marks(self.env, b.id)  # first: see Slot.release_locked
                if b.status == "in_progress" and (b.assignee in ("", b.metadata.get("held_by")) or b.assignee.startswith("tl-")):
                    self.unclaim(b, force=True)
                self.env.event("slot-hold-expired", "", slot=b.title.split()[-1], slot_bead=b.id, repo=self.env.repo)

