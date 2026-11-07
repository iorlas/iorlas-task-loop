"""The tested tree is the landed tree (merge-queue.md section 2): a merge is refused unless it lands the tree the gate judged, and one
that did not is an incident: a parent that is not ours is `raced` (no freeze), a tree that is not ours is `corrupt` (freeze, no revert)."""
from pathlib import Path
from unittest import mock

import pytest
from support.memstores import fake_stores

from taskloop.adapters import check_files
from taskloop.app.land.cmds import Stop
from taskloop.app.land.stack import Stack
from taskloop.app.land.treecheck import Tested
from taskloop.contracts.forge import MERGED, OPEN, Pr, StackItem
from taskloop.contracts.gitport import Git
from taskloop.contracts.procport import Ran
from taskloop.contracts.queue_state import CORRUPT, RACED

MAIN, HEAD, MERGE, THIRD = "m" * 40, "h" * 40, "s" * 40, "x" * 40
TESTED = Tested(parent=MAIN, parent_tree="T0", tree="T1")


def pr(state: str, merge_sha: str = "") -> Pr:
    return Pr(number=7, state=state, head_ref="task/a", head_oid=HEAD, base_ref="main", merge_sha=merge_sha, url="u", title="t")


class World:
    """One Stack.merged call over mocks. `trees` and `parents` answer rev-parse; `during_merge` runs when the forge merges."""

    """One Stack.merged call over mocks. `trees` and `parents` answer rev-parse; `during_merge` runs as the forge merges."""
        self.trees = {"origin/main": "T0", MERGE: "T1", **(trees or {})}
        self.parents = {MERGE: MAIN, **(parents or {})}
        self.mains = [MAIN]
        self.git = git = mock.create_autospec(Git, instance=True)
        git.config_get.return_value = "git@example.com:o/r.git"
        git.rev_parse.side_effect = self.rev_parse
        self.forge = mock.Mock(base="main", remote="origin")
        self.forge.view.side_effect = lambda n: pr(OPEN) if not self.forge.merge.called else pr(MERGED, MERGE)
        self.forge.merge.side_effect = lambda *a: self.during_merge()
        self.cmds = mock.Mock()
        self.cmds.run.return_value = Ran(exit=0, out=f"{predicted}\n")
        self.stores = fake_stores()
        gate = mock.Mock(stores=self.stores)
        self.stack = Stack(self.forge, self.cmds, mock.Mock(stamp={}), self.git, "/repo", Path(lock) / "lock", mock.Mock(return_value=0),
                           mock.Mock(), "o", "s", gate, mock.Mock(), cfg=mock.Mock(), assert_trees=True)

    def during_merge(self) -> None:
        """Hook for a third party's push between the prediction and the merge."""

    def rev_parse(self, d: str, rev: str) -> str:
        if rev == "origin/main":
            return self.mains[-1]
        if rev.endswith("^{tree}"):
            return self.trees.get(rev.removesuffix("^{tree}"), "?")
        if rev.endswith("^"):
            return self.parents.get(rev.removesuffix("^"), "?")
        return rev

    def merged(self, tested: Tested | None = TESTED, state: str = OPEN) -> str:
        return self.stack.merged(StackItem(branch="task/a", bead="a"), pr(state), HEAD, tested)

    def state(self):
        return self.stores.queue_state.of(check_files.repo_key(self.git, "/repo")).get()


def test_a_merge_that_lands_the_tested_tree_on_the_main_we_saw_is_clean(workdir):
    w = World(workdir)
    assert w.merged() == MERGE
    assert w.forge.merge.called and w.state() is None


@pytest.mark.parametrize("kw", [{"trees": {"origin/main": "T9"}}, {"predicted": "T9"}], ids=["main moved", "prediction differs"])
def test_a_prediction_that_differs_from_the_gate_refuses_the_merge(workdir, kw):
    w = World(workdir, **kw)
    with pytest.raises(Stop, match="not merged"):
        w.merged()
    assert not w.forge.merge.called


def test_a_head_that_does_not_merge_into_main_refuses_the_merge(workdir):
    w = World(workdir)
    w.cmds.run.return_value = Ran(exit=1)
    with pytest.raises(Stop, match="does not merge"):
        w.merged()
    assert not w.forge.merge.called


def test_a_third_party_that_moves_main_between_prediction_and_merge_is_a_raced_incident_and_no_freeze(workdir):
    w = World(workdir, parents={MERGE: THIRD}, trees={MERGE: "T7"})
    w.during_merge = lambda: w.mains.append(THIRD)
    with pytest.raises(Stop, match="raced"):
        w.merged()
    state = w.state()
    assert state is not None and not state.frozen
    assert [(i.kind, i.parent, i.main_before) for i in state.incidents] == [(RACED, THIRD, MAIN)]


def test_a_tree_that_is_not_the_tested_one_under_our_parent_is_corrupt_freezes_and_reverts_nothing(workdir):
    w = World(workdir, trees={MERGE: "T7"})
    with pytest.raises(Stop, match="frozen, nothing is reverted"):
        w.merged()
    state = w.state()
    assert state is not None and state.frozen
    assert [(i.kind, i.expected_tree, i.landed_tree) for i in state.incidents] == [(CORRUPT, "T1", "T7")]
    assert not any("revert" in str(c) for c in w.cmds.run.call_args_list)
    w.forge.merge.reset_mock()
    with pytest.raises(Stop, match="frozen"):  # nothing lands until the owner clears it
        w.merged()
    assert not w.forge.merge.called


def test_without_a_tested_tree_nothing_is_asserted_and_land_stack_is_as_before(workdir):
    w = World(workdir, trees={MERGE: "T7"})
    assert w.merged(tested=None) == MERGE
    assert w.state() is None and not w.cmds.run.called
