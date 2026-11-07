"""The slot fakes preserve state, failures, ownership and capability records."""
import pytest
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadPatch, Beads
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.lockenums import LockWhat
from tlkernel.slots import BranchPinned, Checkout, IndexLocked
from tltestkit.membeads import MemBeads

from tlslots.testing import Beating, FakeEffects, FakeSlotGit, FakeSlotsHost, SlotRig, Tree


def test_git_faults_record_calls_before_mutation_and_expire() -> None:
    git = FakeSlotGit()
    git.fail("checkout_new", IndexLocked("locked"), times=2)
    for _ in range(2):
        with pytest.raises(IndexLocked):
            git.checkout_new("/wt", "task/b", "origin/main")
    assert git.tree("/wt") == Tree()
    assert git.branches == set()
    git.checkout_new("/wt", "task/b", "origin/main")
    assert git.tree("/wt").branch == "task/b"
    assert git.calls == [("checkout_new", "/wt", "task/b", "origin/main")] * 3


def test_git_tracks_dirty_rebase_clean_and_pinned_branches() -> None:
    git = FakeSlotGit()
    tree = git.tree("/wt")
    tree.dirty = tree.rebasing = True
    git.rebase_abort("/wt")
    git.commit_all("/wt", "wip/b", "save")
    assert not tree.rebasing and not tree.dirty
    assert git.has_branch("/wt", "wip/b")
    keep = ["ignored"]
    git.clean("/wt", keep)
    keep.clear()
    assert tree.cleaned == ["ignored"]
    git.elsewhere["task/b"] = Checkout(path="/other", branch="task/b", main=False)
    with pytest.raises(BranchPinned) as err:
        git.checkout("/wt", "task/b")
    assert err.value.where == "/other"
    assert tree.branch == "wip/b"
    git.remove_worktree("/repo", "/other")
    git.checkout("/wt", "task/b")
    git.checkout_detached("/wt", "base")
    assert (tree.branch, tree.head, git.removed) == ("", "base", ["/other"])
    git.add_worktree("/repo", "/new", "base")
    assert git.added == [("/new", "base")]


def test_beads_refuse_unknown_writes_and_fence_ownership() -> None:
    fake = MemBeads(actor="owner")
    store: Beads = fake
    bead = BeadId("b-1")
    fake.put(Bead(id=bead, title="work", status="open"))
    assert store.claim(bead)
    assert not store.claim(bead)
    fake.actor = "other"
    assert not store.unclaim(bead)
    for write in (lambda: store.close(bead, "done", if_assignee="other"),
                  lambda: store.update(bead, BeadPatch(if_assignee="other", status="closed")),
                  lambda: store.add_label(bead, "slot", if_assignee="other")):
        with pytest.raises(BdFailure):
            write()
    assert fake.beads[bead].status == "in_progress"
    assert store.unclaim(bead, force=True)
    with pytest.raises(BdFailure):
        store.heartbeat(BeadId("missing"))


def test_beating_records_successful_and_refused_heartbeats() -> None:
    store = Beating()
    bead = BeadId("b-1")
    store.put(Bead(id=bead, title="work", status="open"))
    store.heartbeat(bead)
    with pytest.raises(BdFailure):
        store.heartbeat(BeadId("missing"))
    assert store.beats == [bead, "missing"]


def test_effects_answer_process_identity_workers_and_release_locks() -> None:
    fake = FakeEffects(host="host")
    fx = fake.fx
    fake.processes[12] = "start"
    fake.workers["b-1"] = ["worker"]
    assert fx.hostname() == "host"
    assert fx.proc_alive(12, "start")
    assert not fx.proc_alive(12, "reused")
    assert not fx.proc_alive(99)
    assert fx.proc_start(12) == "start"
    workers = fx.running_for("b-1")
    workers.clear()
    assert fx.running_for("b-1") == ["worker"]
    checked = []
    with fx.hold_path("/lock", "owner", check=lambda: checked.append(True)) as rec:
        assert fake.locks.holder(LockWhat.LAND, "/lock") is rec
    assert fake.locks.holder(LockWhat.LAND, "/lock") is None
    assert checked == [True]
    assert ("proc_alive", (12, "reused")) in fake.calls
    with pytest.raises(ValueError), fx.hold_path("/lock", "owner"):
        raise ValueError("body failed")
    assert fake.locks.holder(LockWhat.LAND, "/lock") is None


def test_machine_host_supplies_recorded_capabilities() -> None:
    fake = FakeSlotsHost()
    host = fake.host
    assert host.bd("actor", "/repo") is fake.store
    assert host.repo_root() == "/repo"
    assert host.hostname() == "fakehost"
    assert host.now() == 1.0
    fake.t = 2.0
    assert host.now() == 2.0
    assert host.peek(fake.store, BeadId("missing")) is None
    who = Identity(actor="actor", home="/config")
    assert host.tickets(who.config) is fake.ticket_store
    with host.os_lock("/take", "actor") as rec:
        assert rec.holder == "actor"
    host.event(who, "slot_take", "b-1", slot="s1")
    assert fake.events == [(who, "slot_take", "b-1", {"slot": "s1"})]
    assert fake.calls[0] == ("bd", ("actor", "/repo"))


class TestRigContract(SlotRig):
    def test_rig_runs_the_pool_and_records_busy_ownership_and_time(self) -> None:
        self.slot().take("work", "b-1")
        assert self.bd.beads[BeadId("sl-s1")].metadata["held_by"] == "tl-me"
        self.busy_at[self.d1] = "engine pid 7"
        assert self.code(lambda: self.slot().release()) == "busy"
        assert self.slot().release(force=True)
        assert self.busy_at == {}
        assert self.events == [("slot_take", "s1"), ("slot_release", "s1")]
