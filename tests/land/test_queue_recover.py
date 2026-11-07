"""Crash recovery uses fake ports and never merges or signals a process."""
from types import SimpleNamespace

import pytest

from taskloop.app.land.cmds import Stop
from taskloop.app.land.queue_recover import facts, recover
from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_persist import to_doc
from taskloop.domain.land.queue_reconcile import AssertAndRecord, BuildFact, DropRef, RemoveWorktree, ResetPending
from tlkernel.forge import MERGED, OPEN


class World:
    def __init__(self, *, state=OPEN, mismatch=False):
        self.effects = []
        self.refs = []
        self.checkouts = []
        self.pr = SimpleNamespace(number=12, state=state, merge_sha="merged" if state == MERGED else "")
        self.mismatch = mismatch
        self.host = SimpleNamespace(
            repo="repo", git=SimpleNamespace(
                for_each_ref=lambda repo, prefix: self.refs, checkouts=lambda repo: self.checkouts,
                rev_parse=lambda repo, rev: "parent" if rev == "merged^" else "main",
                remove_worktree_force=lambda repo, path: self.effects.append(("remove", path))),
            cmds=SimpleNamespace(run=self.command),
            forge=SimpleNamespace(find=lambda branch, head: self.pr, view=lambda number: self.pr),
            trees=SimpleNamespace(main_ref="origin/main", verify=self.verify),
            record=lambda bead, sha: self.effects.append(("record", bead, sha)) or 0,
            log=SimpleNamespace(note=lambda text: self.effects.append(("note", text))))

    def command(self, argv, *, cwd):
        self.effects.append(tuple(argv))
        return SimpleNamespace(exit=0, out="", err="")

    def verify(self, tested, parent, sha, pr, bead):
        self.effects.append(("verify", tested.tree, parent, sha, pr, bead))
        if self.mismatch:
            raise Stop(1, "tree mismatch")


def document(phase=Phase.WAITING):
    return to_doc([Entry(branch="task/a", head="head", phase=phase, tree="tree")], {}, in_flight=1, last_base="main")


def test_orphan_ref_and_scratch_worktree_are_removed():
    world = World()
    ref = "refs/tl/queue/orphan"
    path = "repo/tl-land-gate-orphan"
    world.refs = [SimpleNamespace(name=ref)]
    world.checkouts = [SimpleNamespace(path=path), SimpleNamespace(path="repo/other")]
    assert recover(world.host, document(), 10) == [RemoveWorktree(path), DropRef(ref)]
    assert world.effects == [("remove", path), ("git", "update-ref", "-d", ref)]


def test_merged_pr_is_verified_then_recorded_once_without_merging():
    world = World(state=MERGED)
    assert recover(world.host, document(Phase.GREEN), 10) == [AssertAndRecord("task/a", "merged")]
    assert world.effects == [("verify", "tree", "parent", "merged", 12, "a"), ("record", "a", "merged")]


def test_tree_mismatch_stops_before_recording():
    world = World(state=MERGED, mismatch=True)
    with pytest.raises(Stop, match="tree mismatch"):
        recover(world.host, document(Phase.GREEN), 10)
    assert len(world.effects) == 1
    assert world.effects[0][0] == "verify"


@pytest.mark.parametrize("phase,state", [(Phase.WAITING, OPEN), (Phase.MERGED, MERGED)])
def test_healthy_document_needs_no_actions(phase, state):
    world = World(state=state)
    assert recover(world.host, document(phase), 10) == []
    assert world.effects == []


def test_reset_pending_keeps_document_untouched_and_owns_no_process():
    world = World()
    doc = to_doc([Entry(branch="task/a", head="head", phase=Phase.GATING)],
                 {"task/a": BuildFact("task/a", 42, "old", 100, "repo/tl-land-gate-old")},
                 in_flight=1, last_base="main")
    before = doc
    assert recover(world.host, doc, 10) == [ResetPending("task/a")]
    assert doc == before
    assert doc.entries[0].phase == Phase.GATING.value
    build = doc.entries[0].build
    assert build is not None and build.pid == 42
    assert facts(world.host, doc, lambda: 10).alive == {}
    assert world.effects == []
