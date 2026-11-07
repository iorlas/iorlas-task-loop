"""The slot code (src/taskloop/app/slots) on fakes: bd in memory, git in memory with injected faults, the ticket line in a dict.
Every test here runs in milliseconds; the real git and the real files are in test_tl (SlotReset) and test_slots."""
import time
from pathlib import Path
from unittest import mock

import pytest
from tlkernel.bead import Bead
from tlkernel.ids import BeadId
from tlkernel.slots import BranchPinned, Checkout, DirtyTree, IndexLocked, RefRace, SlotFail, SlotGitError
from tltestkit.membeads import MemBeads as FakeBeads
from tltestkit.tmpdir import TemporaryDirectory

from tlslots.lease import Lease
from tlslots.line import wait_slot, waiting_line
from tlslots.testing import LIVE_PID, ME, Rig


class BeadlessNamedSlot(Rig):
    def test_a_slot_with_no_bead_resets_and_is_never_taken_and_no_bead_id_reaches_the_beads_port(self):
        self.bd.beads.clear()  # bd has no slot bead
        calls = []
        for name in ("show", "update", "claim", "heartbeat", "close", "add_comment", "add_label", "remove_label", "provenance"):
            setattr(self.bd, name, lambda *a, _n=name, **k: calls.append((_n, a)))
        slot = self.pool.named("s1")
        assert slot.bead is None
        assert slot.hold() is None
        slot.ready_for("x-1")  # the worktree work needs no slot bead
        assert self.git.tree(self.d1).branch == "task/x-1"
        assert self.code(lambda: slot.take_locked("why")) == "slot_broken"
        assert calls == []




class Reset(Rig):
    def test_a_missing_slot_is_recreated_before_fetch_and_checkout(self):
        Path(self.d1).rmdir()
        with mock.patch("tlslots.reset.setup"):
            self.slot().ready_for("x-1")
        assert self.git.added == [(self.d1, "origin/main")]
        ops = [call[0] for call in self.git.calls]
        assert ops.index("prune_worktrees") < ops.index("add_worktree")
        assert ops.index("add_worktree") < ops.index("rebasing")
        assert self.git.tree(self.d1).branch == "task/x-1"

    def test_a_git_infrastructure_failure_is_transient(self):
        self.git.fail("checkout_new", SlotGitError("missing object or network unavailable"))
        assert self.code(lambda: self.slot().ready_for("x-1")) == "transient"

    def test_a_bead_gets_a_fresh_branch_off_the_base_and_ignored_output_is_kept(self):
        self.slot().ready_for("x-1")
        assert (self.git.tree(self.d1).branch, self.git.tree(self.d1).head) == ("task/x-1", "origin/main")
        assert self.git.tree(self.d1).cleaned == ["ignored"]

    def test_leftover_work_is_committed_where_it_was_and_a_detached_head_gets_a_wip_branch(self):
        self.git.tree(self.d1).dirty = True
        self.slot().ready_for("x-1")
        assert ("commit_all", self.d1, "wip/s1/1000", "wip: left in slot s1") in self.git.calls
        assert "WIP committed on wip/s1/1000" in self.out
        assert self.git.tree(self.d1).branch == "task/x-1"

    def test_a_bead_with_a_branch_gets_it_as_it_is(self):
        self.git.branches.add("task/x-1")
        self.slot().ready_for("x-1")
        assert self.git.tree(self.d1).branch == "task/x-1"
        assert "checkout_new" not in [c[0] for c in self.git.calls]

    def test_a_live_run_holding_the_beads_branch_pins_the_bead(self):
        self.git.branches.add("task/x-1")
        self.git.elsewhere["task/x-1"] = Checkout(path="/w/old", branch="task/x-1", main=False)
        self.busy_at["/w/old"] = "engine pid 7 runs x-1"
        assert self.code(lambda: self.slot().ready_for("x-1")) == "bead_pinned"
        assert "checkout" not in [c[0] for c in self.git.calls]

    def test_a_dead_runs_worktree_holding_the_branch_is_freed(self):
        self.git.branches.add("task/x-1")
        self.git.elsewhere["task/x-1"] = Checkout(path="/w/old", branch="task/x-1", main=False)
        self.git.tree("/w/old").branch = "task/x-1"
        self.slot().ready_for("x-1")
        assert self.git.removed == ["/w/old"]
        assert self.git.tree(self.d1).branch == "task/x-1"

    def test_git_saying_the_branch_is_taken_pins_the_bead(self):
        self.git.fail("checkout_new", BranchPinned("fatal: already used by worktree at '/w'", "/w"))
        assert self.code(lambda: self.slot().ready_for("x-1")) == "bead_pinned"

    def test_a_lock_that_clears_is_waited_for_and_one_that_stays_breaks_the_slot(self):
        self.git.fail("checkout_new", IndexLocked("index.lock exists"))
        self.git.fail("clean", RefRace("cannot lock ref"), times=2)
        self.slot().ready_for("x-1")
        assert len(self.sleeps) == 3
        self.git.fail("checkout_new", IndexLocked("index.lock exists"), times=3)
        assert self.code(lambda: self.slot().ready_for("x-2")) == "slot_broken"

    def test_work_git_will_not_commit_breaks_the_slot_and_nothing_is_checked_out(self):
        self.git.tree(self.d1).dirty = True
        self.git.fail("commit_all", DirtyTree("fatal: cannot commit"))
        with pytest.raises(SlotFail) as cm:
            self.slot().ready_for("x-1")
        assert cm.value.code == "slot_broken"
        assert "could not commit the leftover work on wip/s1/1000" in cm.value.why
        assert "checkout_new" not in [c[0] for c in self.git.calls]

    def test_a_failed_fetch_is_a_warning_not_a_failure(self):
        self.git.fail("fetch", SlotGitError("fatal: no network"))
        self.slot().ready_for("x-1")
        assert "fetch in slot s1 failed" in self.err[0]

    def test_a_busy_slot_is_left_alone_unless_forced(self):
        self.busy_at[self.d1] = "engine pid 7 runs x-0"
        assert self.code(lambda: self.slot().ready_for("x-1")) == "busy"
        assert self.git.calls == []  # not one git call
        self.slot().ready_for("x-1", force=True)
        assert self.busy_at == {}


class Taking(Rig):
    def test_a_free_slot_is_taken_marked_and_released(self):
        sb = self.slot().take("why", "x-1")
        b = self.bd.beads[sb]
        assert (b.status, b.metadata["held_by"], b.metadata["held_bead"]) == ("in_progress", ME, "x-1")
        assert self.slot().release(mine=True)
        b = self.bd.beads[sb]
        assert (b.status, b.metadata.get("held_by")) == ("open", None)
        assert [e[0] for e in self.events] == ["slot_take", "slot_release"]

    def test_busy_when_held_or_running_and_broken_when_there_is_no_such_slot(self):
        self.slot().take("a")
        assert self.code(lambda: self.slot().take("b")) == "busy"
        self.busy_at[self.env.dir_of("s2")] = "engine pid 7 runs x-0"
        assert self.code(lambda: self.slot("s2").take("b")) == "busy"
        assert self.code(lambda: self.pool.slot("s9")) == "slot_broken"

    def test_the_pool_passes_over_a_busy_slot_and_a_release_by_another_actor_is_left_alone(self):
        self.busy_at[self.d1] = "engine pid 7 runs x-0"
        got = self.pool.take_any("loop")
        assert got is not None
        name, _, sb = got
        assert name == "s2"
        self.bd.beads[sb] = self.bd.beads[sb].replace(metadata={"held_by": "someone-else"})
        self.slot("s2").release(mine=True)
        assert self.bd.beads[sb].status == "in_progress"
        assert "left alone" in self.err[0]

    def test_releasing_by_name_under_a_live_engine_is_busy_unless_forced(self):
        self.slot().take("a")
        self.busy_at[self.d1] = "engine pid 7 runs x-0"
        assert self.code(lambda: self.slot().release()) == "busy"
        assert self.bd.beads[BeadId("sl-s1")].status == "in_progress"
        assert self.slot().release(force=True)
        assert (self.bd.beads[BeadId("sl-s1")].status, self.busy_at) == ("open", {})  # freed, and the engine's lock dropped

    def test_a_forced_release_drops_only_the_lock_it_judged_busy(self):
        """drop_engine_lock without the pid would unlink a lock another engine wrote after the busy look."""
        dropped = []
        self.env.lock_pid = lambda d: 7
        self.env.drop_engine_lock = lambda d, pid=None: dropped.append((d, pid))
        self.slot().take("a")
        self.busy_at[self.d1] = "engine pid 7 runs x-0"
        assert self.slot().release(force=True)
        assert dropped == [(self.d1, 7)]





class Line(Rig):
    def test_a_waiter_behind_a_better_ticket_does_not_take_a_free_slot(self):
        first = self.tickets.take("r-1", "urgent", 0, pid=LIVE_PID, now=1.0)
        assert wait_slot(self.env, "late", stop=lambda: True) is None
        self.tickets.drop("r-1", first.seq)
        assert (wait_slot(self.env, "late", stop=lambda: True) or ("",))[0] == "s1"
        assert self.tickets.line("r-1") == []  # the waiter's own ticket is dropped

    def test_a_waiter_sleeps_with_a_growing_gap_until_a_slot_frees(self):
        self.pool.take_any("a")
        self.pool.take_any("b")
        looks = []
        got = wait_slot(self.env, "late", stop=lambda: len(looks) >= 4 or bool(looks.append(1)), poll=(1, 3))
        assert got is None
        assert self.sleeps == [1, 2, 3, 3]  # a sleep after each of four looks


    def test_the_line_is_first_in_line_first(self):
        self.tickets.take("r-1", "run-task late", 2, pid=LIVE_PID, now=5.0, bead="x-2")
        self.tickets.take("r-1", "run-task urgent", 0, pid=LIVE_PID, now=6.0, bead="x-1")
        assert [(t.bead, t.prio, t.since) for t in waiting_line(self.env)] == [("x-1", 0, 6.0), ("x-2", 2, 5.0)]


class OneLease(Rig):
    def test_a_lease_beats_every_bead_it_holds_and_the_beat_never_raises(self):
        for b in ("x-1", "x-2"):
            self.bd.beads[BeadId(b)] = Bead(id=BeadId(b), title=b, status="open")
        lease = Lease(self.bd, BeadId("x-1"), None, BeadId("sl-s1"))
        lease.add(BeadId("x-2"))
        lease.beat()
        lease.drop(BeadId("x-1"))
        lease.beat()
        assert self.bd.beats == ["x-1", "sl-s1", "x-2", "sl-s1", "x-2"]
        Lease(FakeBeads(), BeadId("nope")).beat()  # bd refuses: nothing changes

    def test_the_thread_beats_until_stopped(self):
        with Lease(self.bd, BeadId("sl-s1"), every=0.01):
            deadline = time.monotonic() + 5
            while len(self.bd.beats) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
        assert len(self.bd.beats) >= 2


class StaleDirs(Rig):
    def test_a_stray_slot_folder_does_not_change_the_slot_count(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env.repo = tmp.name
        Path(self.env.dir_of("s5")).mkdir(parents=True)
        assert [s.name for s in self.pool.slots()] == ["s1", "s2"]
        assert not self.pool.configured("s5")
