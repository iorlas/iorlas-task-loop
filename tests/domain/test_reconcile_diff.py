"""`diff(observed)`: a table, each row an observed state and the actions it maps to. No git, no bd, no process."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.domain.reconcile.diff import DAY, diff
from taskloop.domain.reconcile.facts import (
    Action,
    BeadFact,
    Checkout,
    DeleteBranch,
    DeleteRemote,
    Keep,
    LocalBranch,
    Observed,
    RemoteBranch,
    RemoveTree,
    RepoView,
    Worktree,
)

NOW = 100 * DAY
R = "/r"


def repo(**kw) -> RepoView:
    return replace(RepoView(R, "r"), **kw)


def world(*repos: RepoView, trees: tuple[Worktree, ...] = ()) -> Observed:
    return Observed(NOW, 14, tuple(repos), trees)


def bead(i: str, status: str = "closed", branch: str = "") -> BeadFact:
    return BeadFact(i, status, "", branch or "task/" + i)


def task(name: str, oid: str = "o1", on_head: bool = True) -> LocalBranch:
    return LocalBranch(name, oid, on_head=on_head)


def rel(name: str, oid: str = "o1", on_base: bool = True, age_days: float = 30) -> LocalBranch:
    return LocalBranch(name, oid, on_base=on_base, last_commit=int(NOW - age_days * DAY))


def tree(path: str = "/b/t", **kw) -> Worktree:
    base = Worktree(path, path, R, False, False, "", True, NOW - 30 * DAY)
    return replace(base, **kw)


ROWS: list[tuple[str, Observed, list[Action]]] = [
    ("closed bead, merged task branch: deleted at the oid seen",
     world(repo(beads=(bead("a-1"),), task_branches=(task("task/a-1", "abc"),))),
     [DeleteBranch(R, "r", "task/a-1", "abc")]),
    ("open bead keeps its branch",
     world(repo(beads=(bead("a-1", "open"),), task_branches=(task("task/a-1"),))),
     [Keep("branch task/a-1 (r)", "its bead is not closed (or unknown)")]),
    ("a branch of no bead stays",
     world(repo(beads=(), task_branches=(task("task/zz"),))),
     [Keep("branch task/zz (r)", "its bead is not closed (or unknown)")]),
    ("a closed bead's metadata branch is the one that counts",
     world(repo(beads=(bead("a-1", branch="task/custom"),), task_branches=(task("task/custom"), task("task/a-1")))),
     [DeleteBranch(R, "r", "task/custom", "o1"), Keep("branch task/a-1 (r)", "its bead is not closed (or unknown)")]),
    ("closed but unmerged: stays",
     world(repo(beads=(bead("a-1"),), task_branches=(task("task/a-1", on_head=False),))),
     [Keep("branch task/a-1 (r)", "not merged")]),
    ("closed, merged, but checked out in a worktree: stays",
     world(repo(beads=(bead("a-1"),), task_branches=(task("task/a-1"),), checkouts=(Checkout("/w", "task/a-1"),))),
     [Keep("branch task/a-1 (r)", "checked out in a worktree")]),
    ("bd down: one line, no branch is judged",
     world(repo(bd_down="timeout", task_branches=(task("task/a-1"),))),
     [Keep("task branches of r", "bd did not answer (timeout)")]),
    ("landed remote branch on HEAD goes, with a lease on its oid, before the local ones",
     world(repo(beads=(bead("a-1"),), remotes=(RemoteBranch("refs/heads/task/a-1", "r1", True, True),),
                task_branches=(task("task/a-1"),))),
     [DeleteRemote(R, "r", "refs/heads/task/a-1", "r1"), DeleteBranch(R, "r", "task/a-1", "o1")]),
    ("remote branch with commits HEAD lacks stays",
     world(repo(remotes=(RemoteBranch("refs/heads/task/a-1", "r1", True, False),))),
     [Keep("remote branch task/a-1 (r)", "origin's branch has commits that are not on HEAD")]),
    ("remote branch git does not have yet goes (the lease on its oid guards it)",
     world(repo(remotes=(RemoteBranch("refs/heads/task/a-1", "r1", False, False),))),
     [DeleteRemote(R, "r", "refs/heads/task/a-1", "r1")]),
    ("old release branch on origin/main goes",
     world(repo(release_branches=(rel("release/x"),))),
     [DeleteBranch(R, "r", "release/x", "o1")]),
    ("young release branch stays",
     world(repo(release_branches=(rel("release/x", age_days=2),))),
     [Keep("branch release/x (r)", "its last commit is under 14 days old")]),
    ("release branch with an unknown commit time stays",
     world(repo(release_branches=(LocalBranch("release/x", "o1", on_base=True),))),
     [Keep("branch release/x (r)", "its last commit is under 14 days old")]),
    ("unmerged release branch stays",
     world(repo(release_branches=(rel("release/x", on_base=False),))),
     [Keep("branch release/x (r)", "not merged into origin/main")]),
    ("old clean merged tree goes",
     world(repo(), trees=(tree(),)),
     [RemoveTree(R, "/b/t", "/b/t")]),
    ("tree reasons, in order: run, shell, dirty, unmerged, young",
     world(repo(), trees=(tree("/b/1", run_holds=True), tree("/b/2", shell_in=True), tree("/b/3", dirty="uncommitted or untracked files"),
                          tree("/b/4", on_base=False), tree("/b/5", last_used=NOW - DAY))),
     [Keep("worktree /b/1", "a run holds it (engine lock)"), Keep("worktree /b/2", "this shell is in it"),
      Keep("worktree /b/3", "uncommitted or untracked files"), Keep("worktree /b/4", "not merged into origin/main"),
      Keep("worktree /b/5", "used in the last 14 days")]),
    ("a release branch held only by a tree the plan removes goes after it",
     world(repo(release_branches=(rel("release/x"),), checkouts=(Checkout("/b/t", "release/x"),)), trees=(tree(),)),
     [RemoveTree(R, "/b/t", "/b/t"), DeleteBranch(R, "r", "release/x", "o1", ("/b/t",))]),
    ("a release branch held by a tree that stays stays",
     world(repo(release_branches=(rel("release/x"),), checkouts=(Checkout("/b/t", "release/x"),)),
           trees=(tree(dirty="uncommitted or untracked files"),)),
     [Keep("worktree /b/t", "uncommitted or untracked files"), Keep("branch release/x (r)", "checked out in a worktree")]),
]


class Diff(unittest.TestCase):
    def test_every_row(self):
        for name, observed, expected in ROWS:
            with self.subTest(name):
                self.assertEqual(diff(observed), expected)

    def test_nothing_observed_nothing_to_do(self):
        self.assertEqual(diff(world()), [])

    def test_the_action_list_is_the_same_every_time(self):
        o = world(repo(beads=(bead("a-1"),), task_branches=(task("task/a-1"),)), trees=(tree(),))
        self.assertEqual(diff(o), diff(o))


if __name__ == "__main__":
    unittest.main()
