"""The slot code (src/taskloop/app/slots) on fakes: bd in memory, git in memory with injected faults, the ticket line in a dict.
Every test here runs in milliseconds; the real git and the real files are in test_tl (SlotReset) and test_slots."""
import contextlib
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.fake_beads import FakeBeads
from support.fake_slot_git import FakeSlotGit

from taskloop.adapters.git import classify
from taskloop.cli import slots as cli
from tlkernel import paths
from tlkernel.bead import Bead
from tlkernel.config import SlotsConfig
from tlkernel.ids import BeadId
from tlkernel.slots import BranchPinned, Checkout, DirtyTree, IndexLocked, RefRace, SlotFail, SlotGitError
from tlslots.env import SlotEnv
from tlslots.lease import Lease
from tlslots.line import wait_slot, waiting_line
from tlslots.pool import SlotPool
from tltestkit.memdoc import MemTickets

ME = "tl-me"
LIVE_PID = os.getpid()  # a pid the ticket line reads as alive: pid 1 is launchd on macOS, which libproc will not show to a user process


class Beating(FakeBeads):
    """FakeBeads that remembers its heartbeats."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.beats = []

    def heartbeat(self, bead):
        self.beats.append(bead)
        super().heartbeat(bead)


class Rig(Case):
    def setup_method(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.git, self.tickets = FakeSlotGit(), MemTickets()
        self.bd = Beating(actor=ME, prefix="sl")
        self.out, self.err, self.events, self.sleeps, self.busy_at, self.t = [], [], [], [], {}, [1000.0]
        self.env = SlotEnv(
            repo=str(Path(tmp.name) / "repo"), repo_key="r-1", cfg=SlotsConfig(count=2, keep=["ignored"]),
            store=self.bd, git=self.git, tickets=self.tickets,
            cfgdir=paths.ConfigDir(Path(tmp.name)), actor=ME, host="h", take_lock=contextlib.nullcontext,
            busy=lambda d: self.busy_at.get(d, ""), drop_engine_lock=lambda d, pid=None: self.busy_at.pop(d, None),
            event=lambda kind, bead="", **kw: self.events.append((kind, kw.get("slot"))), run_setup=lambda cmd, d: 0,
            exclude_local=lambda r: None, say=self.out.append, warn=self.err.append, pid=LIVE_PID, now=lambda: self.t[0],
            sleep=self.sleeps.append)
        self.pool = SlotPool(self.env)
        for n in ("s1", "s2"):
            self.bd.beads[BeadId("sl-" + n)] = Bead(id=BeadId("sl-" + n), title="slot h " + n, status="open", labels=["slot"])
        self.d1 = self.env.dir_of("s1")
        for name in ("s1", "s2"):
            Path(self.env.dir_of(name)).mkdir(parents=True)

    def slot(self, name="s1"):
        return self.pool.slot(name)

    def code(self, call):
        with pytest.raises(SlotFail) as cm:
            call()
        return cm.value.code


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


class Classify(Case):
    def test_git_words_become_typed_errors(self):
        assert isinstance(classify("fatal: Unable to create '/r/.git/worktrees/s1/index.lock': File exists."), IndexLocked)
        assert isinstance(classify("error: cannot lock ref 'refs/remotes/origin/main': is at 1 but expected 2"), RefRace)
        pinned = classify("fatal: 'task/x' is already used by worktree at '/w/old'")
        assert isinstance(pinned, BranchPinned)
        assert pinned.where == "/w/old"
        assert isinstance(classify("error: Your local changes to the following files would be overwritten by checkout"), DirtyTree)
        assert type(classify("fatal: not a git repository")) is SlotGitError


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

    def test_an_expired_hold_frees_the_slot(self):
        verbs = SimpleNamespace(op="hold", name="s1", why="screens", for_min=1, n=None, bead=None, force=False)
        assert cli.run(self.env, verbs) == 0
        assert self.code(lambda: self.slot().take("a")) == "busy"
        self.t[0] += 61
        assert (self.pool.take_any("loop") or ("",))[0] == "s1"


class Verbs(Rig):
    def test_the_verb_table_has_every_verb_and_an_unknown_one_is_a_misuse(self):
        assert sorted(cli.VERBS) == ["hold", "init", "list", "release", "reset", "setup", "take"]
        assert cli.run(self.env, SimpleNamespace(op="nope")) == 2

    def test_reset_answers_with_the_code_of_the_failure(self):
        a = SimpleNamespace(op="reset", name="s1", bead="x-1", force=False, error="")
        self.git.fail("checkout_new", BranchPinned("fatal: taken", "/w"))
        assert cli.run(self.env, a) == 5
        assert a.error == "fatal: taken"
        self.busy_at[self.d1] = "engine pid 7 runs x-0"
        assert cli.run(self.env, a) == 4
        assert self.out[-1].startswith("BUSY: slot s1: engine pid 7")
        del self.busy_at[self.d1]
        self.git.fail("checkout_new", SlotGitError("fatal: boom"))
        assert cli.run(self.env, a) == 3

    def test_list_names_the_slots_and_the_line(self):
        self.tickets.take("r-1", "run-task late", 2, pid=LIVE_PID, now=5.0)
        self.tickets.take("r-1", "run-task urgent", 0, pid=LIVE_PID, now=6.0)
        assert cli.run(self.env, SimpleNamespace(op="list")) == 0
        rows = [r.split("\t") for r in self.out]
        assert [r[0] for r in rows[:2]] == ["s1", "s2"]
        assert [(r[1], r[2], r[4]) for r in rows[2:]] == [("1", "P0", "run-task urgent"), ("2", "P2", "run-task late")]


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
