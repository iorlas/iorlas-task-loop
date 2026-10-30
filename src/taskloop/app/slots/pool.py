"""The slots of one repo on this machine: a slot is a worktree plus its bd bead, which is the lease. `Slot.take`, `ready_for`
and `release` fail with a SlotFail (slot_broken, bead_pinned or busy); the pool takes the first free one."""
from pathlib import Path

from taskloop.app.slots.env import SlotEnv, peek, stamp
from taskloop.app.slots.marks import clear_marks, held_by, hold_of, hold_until, mark_held, next_gen
from taskloop.app.slots.reset import ready_for
from taskloop.contracts.bead import Bead
from taskloop.contracts.fence import SLOT_GEN, gen_of
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.contracts.slots import Hold, SlotFail


class Slot:
    def __init__(self, pool: SlotPool, name: str, bead: Bead | None) -> None:
        self.pool, self.name, self.bead = pool, name, bead
        self.env = pool.env
        self.dir = pool.env.dir_of(name)

    def slot_bead(self) -> Bead:
        """The slot's bead; a slot reached by name for its worktree only (`SlotPool.named`) has none, and no bd call is made for it."""
        if self.bead is None:
            raise SlotFail("slot_broken", f"no slot {self.name} on {self.env.host} (tl slot list)")
        return self.bead

    def hold(self) -> Hold | None:
        return hold_of(self.bead, self.env.now()) if self.bead is not None else None

    def free_reason(self) -> str:
        """Why this slot cannot be taken now, "" when it can: a hold, a claim, or a live engine in its worktree."""
        hold = self.hold()
        if hold:
            return f"held by {hold.by} since {hold.since} until {stamp(hold.until)}: {hold.why} (tl slot release {self.name} ends it)"
        if self.bead is not None and self.bead.status != "open":
            return f"held by {held_by(self.bead)}"
        busy = self.env.busy(self.dir)
        return f"busy: {busy}" if busy else ""

    def claimed(self) -> bool:
        """True when this session won the slot bead's claim."""
        st, sb = self.env.store, self.slot_bead()
        return st.claim(sb.id) and ((peek(st, sb.id) or Bead(id=sb.id, title="", status="")).assignee
                                           or self.env.actor) == self.env.actor

    def take_locked(self, why: str, bead: str = "", ticket: int | None = None) -> BeadId:
        """The slot bead's id once this session holds the slot; the caller holds the repo's take lock. Fails busy."""
        sb = self.slot_bead()
        why_not = self.free_reason()
        if why_not:
            raise SlotFail("busy", f"slot {self.name} {why_not}")
        if not self.claimed():
            raise SlotFail("busy", f"slot {self.name} held by {held_by(peek(self.env.store, sb.id) or sb)}")
        mark_held(self.env, sb.id, why, bead=bead, gen=next_gen(sb))
        self.env.event("slot_take", "", slot=self.name, slot_bead=sb.id, worktree=self.dir, repo=self.env.repo,
                       **({"ticket": ticket} if ticket is not None else {}))
        return sb.id

    def take(self, why: str, bead: str = "") -> BeadId:
        """Take this slot by name. A held slot bead is refused even when this session's actor holds it (two hand runs of
        one session share its actor, and bd lets an actor re-claim its own bead); a hold too, its holder's own included."""
        with self.env.take_lock():
            self.pool.free_expired()
            fresh = self.pool.bead(self.name)
            if fresh is None:
                raise SlotFail("slot_broken", f"no slot {self.name} on {self.env.host} (tl slot list)")
            return Slot(self.pool, self.name, fresh).take_locked(why, bead)

    def ready_for(self, bead: str, *, force: bool = False) -> None:
        """A clean tree on the bead's branch, leftover work committed (never wiped); see reset.py."""
        ready_for(self, bead, force=force)

    def release(self, bead: str | None = None, *, mine: bool = False, force: bool = False, gen: int | None = None) -> bool:
        """Free the slot; fails busy while an engine runs in it (force drops the engine's lock and frees it). mine=True (a run
        ending): only while the slot's marks still name this actor (and `bead`, when it is marked): a slot reclaimed and
        retaken is the new holder's, left alone; so is a slot whose generation is no longer `gen` (the lease this run took: the same
        actor retaking it is another take). False when the slot bead is gone."""
        if not mine:  # a person or the loop ending a slot by name: never under a live engine, unless forced (which drops its lock)
            holder = self.env.lock_pid(self.dir)  # read before the busy look: the lock dropped below is the one judged busy
            busy = self.env.busy(self.dir)
            if busy and not force:
                raise SlotFail("busy", f"slot {self.name}: {busy}; it frees itself when that run ends (--force: release and drop the lock)")
            if busy:
                self.env.drop_engine_lock(self.dir, holder)
        with self.env.take_lock():
            return self.release_locked(bead, mine, force, gen)

    def release_locked(self, bead: str | None, mine: bool, force: bool, gen: int | None = None) -> bool:
        b = self.pool.bead(self.name)
        if b is None:
            return False
        if mine:
            m = b.metadata
            retaken = gen is not None and gen_of(b, SLOT_GEN) != gen
            if retaken or m.get("held_by") != self.env.actor or (bead is not None and m.get("held_bead") not in (None, "", bead)):
                self.env.warn("tl: slot {} is no longer held by {}{} (now {}): left alone".format(
                    self.name, self.env.actor, " for " + bead if bead else "", held_by(b) if b.status != "open" else "free"))
                return True
        # the holder's marks go first, while the bead is still claimed: unclaimed first, a hold taken in between would lose
        # its marks to this clean-up (race test, tl-bxk.11.1)
        clear_marks(self.env, b.id)
        self.pool.unclaim(b, force)
        self.env.event("slot_release", "", slot=self.name, slot_bead=b.id, repo=self.env.repo)
        return True


def machine_slots(store: Beads, host: str) -> list[Bead]:
    """The slot beads of `host` (title `slot <host> <name>`): a lease is local to one machine's bd."""
    try:
        found = store.find(BeadQuery(label="slot", include_closed=True))
    except BdFailure:
        return []
    return sorted((b for b in found if b.status != "closed" and b.title.split()[1:2] == [host]), key=lambda b: b.title)


class SlotPool:
    def __init__(self, env: SlotEnv) -> None:
        self.env = env

    def beads(self) -> list[Bead]:
        return machine_slots(self.env.store, self.env.host)

    def slots(self) -> list[Slot]:
        return [Slot(self, b.title.split()[-1], b) for b in self.beads()]

    def bead(self, name: str) -> Bead | None:
        return next((b for b in self.beads() if b.title.split()[-1] == name), None)

    def slot(self, name: str) -> Slot:
        b = self.bead(name)
        if b is None:
            raise SlotFail("slot_broken", f"no slot {name} on {self.env.host} (tl slot list)")
        return Slot(self, name, b)

    def named(self, name: str) -> Slot:
        """The slot `name` for a reset or a setup, which need only its worktree: its bead is None when bd has none."""
        b = self.bead(name)
        return Slot(self, name, b)

    def name_of(self, wt: str) -> str:
        """The slot whose worktree `wt` is, or ""."""
        here = Path(wt).resolve()
        return next((s.name for s in self.slots() if Path(s.dir).resolve() == here), "")

    def unclaim(self, b: Bead, force: bool = False) -> None:
        """Give a slot bead back. `bd unclaim` frees only the caller's own claim: a slot claimed by a loop's actor and held
        by one of its runs (or a dead loop's) stayed in_progress after `slot release --force` / an expired hold (0.23.34)."""
        if not self.env.store.unclaim(b.id) and force:
            self.env.store.unclaim(b.id, force=True)

    def take_any(self, why: str, bead: str = "", ticket: int | None = None) -> tuple[str, str, BeadId] | None:
        """(name, dir, slot bead) of the first free slot this session could claim, or None. A waiter goes through
        TicketQueue.wait, which takes its turn in the line first; `ticket` is its number, kept on the take's event."""
        with self.env.take_lock():
            self.free_expired()
            for slot in self.slots():
                if not self.configured(slot.name):
                    continue
                try:
                    return slot.name, slot.dir, slot.take_locked(why, bead, ticket)
                except SlotFail:
                    continue
        return None

    def configured(self, name: str) -> bool:
        """Whether `name` is within slots.count (read again each tick): a slot beyond it is taken no more, and one a run still
        holds ends with that run. count 0 or unset: every slot there is."""
        n = self.env.cfg.count
        return not n or name in {f"s{i}" for i in range(1, n + 1)}

    def free_expired(self) -> None:
        """An expired hold gives its slot bead back (the holder's claim with it), so the slot is free at once. Takes no lock:
        the caller holds the take lock, so a stale look never wipes a slot another session took meanwhile."""
        for b in self.beads():
            if hold_until(b) and not hold_of(b, self.env.now()):
                clear_marks(self.env, b.id)  # first: see Slot.release_locked
                if b.status == "in_progress" and (b.assignee in ("", b.metadata.get("held_by")) or b.assignee.startswith("tl-")):
                    self.unclaim(b, force=True)
                self.env.event("slot_hold_expired", "", slot=b.title.split()[-1], slot_bead=b.id, repo=self.env.repo)

