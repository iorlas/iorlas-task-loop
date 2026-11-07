"""tl-bxk.10.33.12: the slot liveness invariants (domain/slot_liveness.py) and the watchdog that logs and heals them
(app/slots/watchdog.py)."""
import os
from datetime import UTC, datetime
from unittest.mock import patch

from slots.test_slot_pool import Rig
from tlkernel.beadsport import BeadPatch
from tlkernel.slots import SlotFail
from tlslots import aside, watchdog
from tlslots.line import wait_slot
from tlslots.liveness import Kind, Limits, SlotFact, Waiter, violations
from tlslots.pool import Slot
from tltestkit.case import Case

L = Limits(grant_s=100, idle_s=600, aside_s=1800, orphan_s=900)


def kinds(found):
    return [(v.kind, v.slot) for v in found]


class Pure(Case):
    def test_a_free_slot_beside_a_live_waiter_is_a_violation_only_after_the_grant_window(self):
        free, line = [SlotFact("s1", free_since=1000)], [Waiter(1, since=900)]
        assert violations(free, line, 1100, limits=L) == []
        assert kinds(violations(free, line, 1101, limits=L)) == [(Kind.FREE_BESIDE_WAITER, "s1")]

    def test_the_window_starts_when_both_the_slot_and_the_waiter_exist(self):
        assert violations([SlotFact("s1", free_since=0)], [Waiter(1, since=5000)], 5050, limits=L) == []  # the waiter is new
        assert violations([SlotFact("s1", free_since=5000)], [Waiter(1, since=0)], 5050, limits=L) == []  # the slot just freed

    def test_no_live_waiter_no_violation(self):
        assert violations([SlotFact("s1", free_since=0)], [], 9999, limits=L) == []
        assert violations([SlotFact("s1", free_since=0)], [Waiter(1, 0, live=False)], 9999, limits=L) == []

    def test_a_ready_bead_an_idle_lane_and_a_free_slot_for_too_long(self):
        free = [SlotFact("s1", free_since=0)]
        assert violations(free, [], 5000, ready_since=4500, idle_lanes=1, limits=L) == []
        assert kinds(violations(free, [], 5000, ready_since=4000, idle_lanes=1, limits=L)) == [(Kind.READY_IDLE_FREE, "s1")]
        assert violations(free, [], 5000, ready_since=4000, idle_lanes=0, limits=L) == []
        assert violations(free, [], 5000, ready_since=None, idle_lanes=1, limits=L) == []

    def test_a_slot_set_aside_for_too_long(self):
        aside_ = [SlotFact("s2", aside_since=0)]
        assert violations(aside_, [], 1800, limits=L) == []
        assert kinds(violations(aside_, [], 1801, limits=L)) == [(Kind.ASIDE_TOO_LONG, "s2")]

    def test_a_slot_held_with_no_engine_lock_for_too_long(self):
        held = lambda locked: [SlotFact("s1", held_since=0, locked=locked)]  # noqa: E731
        assert violations(held(True), [], 99999, limits=L) == []
        assert violations(held(False), [], 900, limits=L) == []
        assert kinds(violations(held(False), [], 901, limits=L)) == [(Kind.ORPHAN_HELD, "s1")]

    def test_the_2026_11_03_state_is_flagged(self):
        """Two slots, one set aside for hours and one busy, seven waiters: the aside is the violation the stall hid."""
        slots = [SlotFact("s1", held_since=0, locked=True), SlotFact("s2", aside_since=0)]
        line = [Waiter(i, since=i) for i in range(7)]
        assert kinds(violations(slots, line, 7200, limits=L)) == [(Kind.ASIDE_TOO_LONG, "s2")]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


class Watching(Rig):
    """The watchdog on the fakes: bd that stamps updated_at from the test clock, the line, and engine locks in `busy_at`."""

    def setup_method(self):
        super().setup_method()
        self.env.cfg = self.env.cfg.replace(count=2)
        real_put = type(self.bd)._put
        self.bd._put = lambda b, **ch: real_put(self.bd, b, updated_at=iso(self.t[0]), **ch)
        for b in list(self.bd.beads.values()):
            self.bd.beads[b.id] = b.replace(updated_at=iso(self.t[0]))
        self.watch = watchdog.Watch()
        self.events.clear()

    def tick(self, secs=0.0):
        self.t[0] += secs
        self.watch.looked = None
        return watchdog.tick(self.env, self.watch)

    def stalls(self):
        return [e for e in self.events if e[0] == "slot_stall"]

    def test_a_free_slot_beside_a_head_that_never_takes_costs_the_head_its_ticket_one_per_window(self):
        for _ in range(2):
            self.env.tickets.take("r-1", "tl loop", 2, pid=os.getpid(), now=self.t[0])
        assert self.tick(60) == []
        found = self.tick(100)  # the violation shows (160 s) but this caller saw the head for 100 s only
        assert kinds(found) == [(Kind.FREE_BESIDE_WAITER, "s1"), (Kind.FREE_BESIDE_WAITER, "s2")]
        assert [t.seq for t in self.env.tickets.line("r-1")] == [1, 2]
        assert len(self.stalls()) == 2
        self.tick(30)  # a whole window as head: #1 goes, once for both slots
        assert [t.seq for t in self.env.tickets.line("r-1")] == [2]
        self.tick(30)  # #2 heads the line only now: its own window starts
        assert [t.seq for t in self.env.tickets.line("r-1")] == [2]
        self.tick(130)
        assert [t.seq for t in self.env.tickets.line("r-1")] == []

    def test_a_violation_that_goes_on_is_logged_once_per_episode_and_again_after_the_relog_time(self):
        self.slot("s1").take("a person")
        self.bd.update(self.slot("s2").slot_bead().id, BeadPatch(set_metadata={"aside_probe": "pending"}))
        self.tick(0)
        self.tick(2000)
        self.tick(10)
        assert len(self.stalls()) == 1
        self.tick(watchdog.RELOG)
        assert len(self.stalls()) == 2

    def test_an_automatic_holder_with_no_engine_lock_loses_its_lease(self):
        self.slot("s1").take("tl loop")
        assert self.tick(800) == []
        assert kinds(self.tick(200)) == [(Kind.ORPHAN_HELD, "s1")]
        assert self.slot("s1").slot_bead().status == "open"
        assert self.stalls() == [("slot_stall", "s1")]

    def test_a_held_slot_with_a_live_engine_lock_a_person_or_a_hold_is_left_alone(self):
        self.slot("s1").take("tl loop")
        self.busy_at[self.d1] = "engine pid 7 runs x-1"
        self.slot("s2").take("tl slot take: a person")
        assert self.tick(5000) == []
        assert (self.slot("s1").slot_bead().status, self.slot("s2").slot_bead().status) == ("in_progress", "in_progress")

    def test_a_lock_written_by_the_looking_process_itself_is_a_lock(self):
        """engine_busy calls a lock of the asking process "mine", i.e. not busy: the slot a process holds is not an orphan to it."""
        self.slot("s1").take("tl loop")
        self.env.lock_pid = lambda wt: self.env.pid
        assert self.tick(5000) == []
        assert self.slot("s1").slot_bead().status == "in_progress"

    def test_a_slot_set_aside_is_stamped_once_flagged_when_old_and_cleared_when_it_recovers(self):
        self.slot("s1").take("a person")  # the probe below is the only free slot's
        bid = self.slot("s2").slot_bead().id
        self.bd.update(bid, BeadPatch(set_metadata={"aside_probe": "pending"}))
        self.tick(0)
        assert self.slot("s2").slot_bead().metadata["aside_since"] == f"{self.t[0]:.0f}"
        assert self.tick(1700) == []
        assert kinds(self.tick(200)) == [(Kind.ASIDE_TOO_LONG, "s2")]
        assert self.slot("s2").slot_bead().metadata["aside_probe"] == "pending"  # only said, never cleared
        with patch.object(Slot, "ready_for"), patch.object(aside, "setup"):
            assert self.pool.take_any("work") is not None  # a passing probe: the slot is back
        self.tick(1)
        assert "aside_since" not in self.slot("s2").slot_bead().metadata

    def test_a_slot_whose_probe_fails_is_not_counted_free_beside_a_waiter(self):
        self.bd.update(self.slot("s1").slot_bead().id, BeadPatch(set_metadata={"aside_probe": "pending"}))
        self.bd.update(self.slot("s2").slot_bead().id, BeadPatch(set_metadata={"aside_probe": "pending"}))
        self.env.tickets.take("r-1", "tl loop", 2, pid=os.getpid(), now=self.t[0])
        with patch.object(Slot, "ready_for", side_effect=SlotFail("slot_broken", "setup failed")):
            assert [v.kind for v in self.tick(500)] == []
        assert self.stalls() == []

    def test_a_waiter_behind_a_hung_ticket_heals_the_line_and_takes_the_slot(self):
        """wait_slot runs the watchdog every poll: the hung head (alive, never takes) goes after the window, then the waiter gets in."""
        self.env.tickets.take("r-1", "tl loop", 0, pid=os.getpid(), now=self.t[0] - 10)
        naps = []

        def nap(secs):
            naps.append(secs)
            self.t[0] += 40

        assert wait_slot(self.env, "tl loop", stop=lambda: len(naps) >= 2, sleep=nap, poll=(5, 5)) is None  # 80 s: within the window
        assert self.stalls() == []
        got = wait_slot(self.env, "tl loop", stop=lambda: len(naps) >= 12, sleep=nap, poll=(5, 5))
        assert got is not None
        assert got[0] == "s1"
        assert self.stalls() == [("slot_stall", "s1"), ("slot_stall", "s2")]

    def test_the_doctor_look_writes_nothing(self):
        self.bd.update(self.slot("s2").slot_bead().id, BeadPatch(set_metadata={"aside_probe": "pending"}))
        self.slot("s1").take("tl loop")
        self.t[0] += 5000
        before = dict(self.bd.beads)
        found = watchdog.look(self.env)
        assert kinds(found) == [(Kind.ORPHAN_HELD, "s1")]
        assert dict(self.bd.beads) == before
        assert self.stalls() == []
        assert watchdog.lines(found)[0].startswith("slot stall (orphan_held)")

    def test_a_slot_beyond_the_configured_count_is_skipped(self):
        self.env.cfg = self.env.cfg.replace(count=1)
        self.slot("s1").take("tl loop")
        slots, _ = watchdog.facts(self.env, self.t[0])
        assert [s.name for s in slots] == ["s1"]
