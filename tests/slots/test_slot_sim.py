"""tl-bxk.10.33.12 (c): a deterministic simulation of the slot line. Random interleavings of waiters, crashes, a waiter hung with its ticket
at the head of the line, setup failures and stale claims run the real SlotPool, ticket line and watchdog on a fake clock and fake
processes; fixed seeds. After every step: a grantable slot never sits beside a live waiter beyond the watchdog's window, a slot is never
held by a process that is not running beyond its window, and a slot set aside long enough has been flagged."""
import random
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import support.paths  # noqa: F401

from slots.test_slot_pool import Rig
from taskloop.app.slots import aside, watchdog
from taskloop.app.slots.env import stamp
from taskloop.app.slots.line import order
from taskloop.app.slots.pool import Slot
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BeadPatch
from taskloop.contracts.slots import SlotFail
from taskloop.domain.slot_liveness import LIMITS, Kind

STEP = 45.0
SLACK = watchdog.EVERY + 2 * STEP  # a look every EVERY s, a step of up to STEP s before it, one more before the check
SEEDS = range(10)
STEPS = 180


class Broken(AssertionError):
    pass


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


class Sim(Rig):
    def setUp(self):
        super().setUp()
        self.bd.beads[BeadId("sl-s3")] = Bead(id=BeadId("sl-s3"), title="slot h s3", status="open", labels=["slot"])
        Path(self.env.dir_of("s3")).mkdir(parents=True)
        self.env.cfg = self.env.cfg.replace(count=3)
        real_put = type(self.bd)._put
        self.bd._put = lambda b, **ch: real_put(self.bd, b, updated_at=iso(self.t[0]), **ch)
        for b in list(self.bd.beads.values()):
            self.bd.beads[b.id] = b.replace(updated_at=iso(self.t[0]))

    def start(self, seed):
        self.rng, self.pid, self.alive = random.Random(seed), 100, set()
        self.waiters, self.holders, self.broken, self.aside_at, self.flagged = [], {}, set(), {}, set()
        self.watch, self.watches, self.free_since = watchdog.Watch(), {}, {}
        self.events.clear()
        self.tickets.rows.clear()
        self.t[0] = 1_800_000_000.0
        for b in list(self.bd.beads.values()):
            self.bd.beads[b.id] = b.replace(status="open", assignee="", metadata={}, updated_at=iso(self.t[0]))
        self.busy_at.clear()

    def proc(self):
        self.pid += 1
        self.alive.add(self.pid)
        return self.pid

    def note(self, found):
        self.flagged |= {v.slot for v in found if v.kind is Kind.ASIDE_TOO_LONG}

    def names(self):
        return [s.name for s in self.pool.slots()]

    # ---- the world's moves ---------------------------------------------------------------------------------------------
    def join(self):
        pid = self.proc()
        ticket = self.env.tickets.take("r-1", "tl loop", self.rng.choice([0, 2, 2, 2]), pid=pid, now=self.t[0])
        self.waiters.append({"pid": pid, "ticket": ticket})

    def finish(self):
        if self.holders:
            name = self.rng.choice(sorted(self.holders))
            self.holders.pop(name)
            self.busy_at.pop(self.env.dir_of(name), None)
            self.pool.slot(name).release(mine=True)

    def crash_holder(self):
        if self.holders:
            name = self.rng.choice(sorted(self.holders))
            self.alive.discard(self.holders.pop(name))  # the process is gone; its claim and marks stay
            self.busy_at.pop(self.env.dir_of(name), None)

    def crash_waiter(self):
        if self.waiters:
            self.alive.discard(self.waiters.pop(self.rng.randrange(len(self.waiters)))["pid"])

    def hang(self):
        """A waiter hangs (a stuck bd call, a stopped process): its pid lives, its ticket heads the line, and it never takes."""
        if self.waiters:
            self.waiters.pop(self.rng.randrange(len(self.waiters)))

    def break_slot(self):
        name = self.rng.choice(self.names())
        b = self.pool.bead(name)
        if b and b.status == "open":
            self.broken.add(name)
            self.bd.update(b.id, BeadPatch(set_metadata={"aside_probe": "pending"}))
            self.aside_at.setdefault(name, self.t[0])

    def fix_slot(self):
        self.broken.discard(self.rng.choice(self.names()))

    def stale_claim(self):
        """A claim of a dead loop: held, marked, no process, no engine lock."""
        name = self.rng.choice(self.names())
        b = self.pool.bead(name)
        if b and b.status == "open" and name not in self.holders:
            held = {"held_by": "tl-dead", "held_why": "tl loop", "held_since": stamp(self.t[0] - self.rng.randrange(0, 800))}
            self.bd.beads[b.id] = b.replace(status="in_progress", assignee="tl-dead", metadata={**b.metadata, **held})

    MOVES = ("join", "join", "join", "finish", "finish", "crash_holder", "crash_waiter", "hang", "break_slot", "fix_slot", "stale_claim")

    # ---- what the waiters do every step (wait_slot's body, without the sleep) -----------------------------------------------
    def poll(self):
        for w in self.rng.sample(self.waiters, len(self.waiters)):
            line = self.env.tickets.line("r-1")
            if w["ticket"].pid not in self.alive:
                continue
            got = None if [x for x in line if order(x) < order(w["ticket"])] else self.pool.take_any("tl loop", "", w["ticket"].seq)
            if not got:  # wait_slot: a waiter that did not get a slot looks at the invariants before it sleeps
                self.note(watchdog.tick(self.env, self.watches.setdefault(w["pid"], watchdog.Watch()), own=w["ticket"]))
            if got:
                name = got[0]
                if name in self.holders and self.holders[name] in self.alive:
                    raise Broken(f"slot {name} granted to {w['pid']} while {self.holders[name]} runs in it")
                self.holders[name] = w["pid"]
                self.busy_at[self.env.dir_of(name)] = f"engine pid {w['pid']}"
                self.env.tickets.drop("r-1", w["ticket"].seq)
                self.waiters.remove(w)
                self.aside_at.pop(name, None)
        for name in list(self.aside_at):
            b = self.pool.bead(name)
            if b and b.metadata.get("aside_probe") != "pending":
                self.aside_at.pop(name)
                self.broken.discard(name)

    # ---- the invariants -----------------------------------------------------------------------------------------------------
    def check(self):
        now, line = self.t[0], self.env.tickets.line("r-1")
        grantable = [s for s in self.pool.slots() if s.bead and s.bead.status == "open" and s.bead.metadata.get("aside_probe") != "pending"
                     and not s.free_reason()]
        besides = {(s.name, t.seq): self.free_since.get((s.name, t.seq), now) for s in grantable for t in line}
        self.free_since = besides  # per slot and waiter: since when the slot is grantable and that waiter is in line
        for (name, seq), since in besides.items():
            if now - since > LIMITS.grant_s + SLACK:
                raise Broken(f"t+{now - 1_800_000_000:.0f}: slot {name} free beside live waiter #{seq} for {now - since:.0f} s")
        for s in self.pool.slots():
            b = s.bead
            assert b is not None
            if b.status == "in_progress" and b.metadata.get("held_why") == "tl loop" and s.name not in self.holders:
                held = watchdog._held_since(b)
                if held is not None and now - held > LIMITS.orphan_s + SLACK:
                    raise Broken(f"t+{now - 1_800_000_000:.0f}: slot {s.name} held {now - held:.0f} s by a process that does not run")
        for name, since in self.aside_at.items():
            if now - since > LIMITS.aside_s + SLACK and name not in self.flagged:
                raise Broken(f"t+{now - 1_800_000_000:.0f}: slot {name} set aside {now - since:.0f} s and never flagged")

    def run_seed(self, seed):
        self.start(seed)

        def setup(slot, force=False):
            if slot.name in self.broken:
                raise SlotFail("slot_broken", "setup failed")

        with patch("taskloop.contracts.locks.pid_alive", side_effect=lambda p: p in self.alive), \
                patch.object(Slot, "ready_for"), patch.object(aside, "setup", side_effect=setup):
            for _ in range(STEPS):
                self.t[0] += self.rng.uniform(1, STEP)
                getattr(self, self.rng.choice(self.MOVES))()
                self.poll()
                self.note(watchdog.tick(self.env, self.watch))  # the loop's pass
                self.check()

    def test_fixed_seeds_hold_every_invariant(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.run_seed(seed)

    def test_without_the_watchdog_the_same_seeds_find_the_stall(self):
        """The control: the invariants bite. Without the heal, a hung waiter or a dead holder keeps a slot out of use for good."""
        failures = []
        with patch.object(watchdog, "heal", return_value=False):
            for seed in SEEDS:
                try:
                    self.run_seed(seed)
                except Broken as err:
                    failures.append(str(err))
        self.assertTrue(failures)
        self.assertTrue(any("free beside" in f for f in failures), failures)
        self.assertTrue(any("does not run" in f for f in failures), failures)


if __name__ == "__main__":
    unittest.main()
