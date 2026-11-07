"""The tested tree is the landed tree (docs/design/merge-queue.md section 2), in the layers that belong to the land lock.

Before the merge (`refuse`): main must have the tree the gate assumed as its parent, and the merge of the head into main must have the
tree the gate judged; else nothing is merged. After it (`verify`): the merge commit must have the tested tree and the main we saw as its
parent. A mismatch is recorded as an incident and stops the run, never repaired here: a parent that is not ours is `raced` (someone else
pushed to main in between; the next gate runs on the new main, no freeze), a parent that is ours with another tree is `corrupt` and
freezes the queue until the owner clears it. No revert: the cause may be a push outside the queue, and a revert is a second write on the
same broken path."""
import time
from typing import final

from taskloop.adapters import check_files
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.contracts.gitport import Git
from taskloop.contracts.queue_state import CORRUPT, RACED, Incident, QueueState
from taskloop.contracts.wire import Rec
from taskloop.stores.api import Doc
from taskloop.stores.bundle import Stores


@final
class Tested(Rec):
    """What the gate judged: parent: the main commit it assumed, parent_tree: its tree, tree: the tree it ran the checks on."""

    parent: str
    parent_tree: str
    tree: str


class TreeGuard:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, main_ref: str) -> None:
        self.cmds, self.git, self.stores, self.repo, self.main_ref = cmds, git, stores, repo, main_ref

    @property
    def doc(self) -> Doc[QueueState]:
        return self.stores.queue_state.of(check_files.repo_key(self.git, self.repo))

    def tree(self, rev: str) -> str:
        return self.git.rev_parse(self.repo, f"{rev}^{{tree}}")

    def state(self) -> QueueState:
        return self.doc.get() or QueueState()

    def refuse(self, head: str, tested: Tested) -> str:
        """Why the merge of `head` must not happen now ('' when it may). Under the land lock, after a fetch."""
        if self.state().frozen:
            return "the queue is frozen by a tree mismatch: clear it before landing"
        main = self.tree(self.main_ref)
        if main != tested.parent_tree:
            return f"{self.main_ref} has tree {main[:12]}, the gate assumed {tested.parent_tree[:12]} (main moved): gate again"
        # git-port-exempt: merge-tree is the prediction; a Git port method waits for the queue builder, its second caller
        ran = self.cmds.run(["git", "merge-tree", "--write-tree", self.main_ref, head], cwd=self.repo)
        if ran.exit:
            return f"{head[:12]} does not merge into {self.main_ref} (merge-tree exit {ran.exit})"
        predicted = ran.out.split()[0] if ran.out.split() else ""
        if predicted != tested.tree:
            return f"the merge into {self.main_ref} would have tree {predicted[:12]}, the gate judged {tested.tree[:12]}"
        return ""

    def verify(self, tested: Tested, main_before: str, merge_sha: str, pr: int, bead: str) -> None:
        """After the merge and a fetch: the merge commit has the tested tree and `main_before` as its parent, or the run stops."""
        landed, parent = self.tree(merge_sha), self.git.rev_parse(self.repo, f"{merge_sha}^")
        if landed == tested.tree and parent == main_before:
            return
        kind = CORRUPT if parent == main_before else RACED
        state = self.state()
        row = Incident(t=time.time(), kind=kind, pr=pr, bead=bead, main_before=main_before, merge_sha=merge_sha, parent=parent,
                       expected_tree=tested.tree, landed_tree=landed)
        self.doc.write(QueueState(frozen=state.frozen or kind == CORRUPT, incidents=[*state.incidents, row]))
        what = f"PR #{pr} landed as {merge_sha[:12]} with tree {landed[:12]}, the gate judged {tested.tree[:12]}"
        if kind == RACED:
            raise Stop(1, f"{what}; its parent is {parent[:12]}, not the {main_before[:12]} we saw: main moved in between (raced). "
                          f"Gate again on the new {self.main_ref}; the queue is not frozen")
        raise Stop(1, f"{what}; its parent is the main we saw (corrupt). The queue is frozen, nothing is reverted. Owner: look at "
                      f"`git diff {tested.tree[:12]} {landed[:12]}` and clear the freeze (queue_state of this repo)")
