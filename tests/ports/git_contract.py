"""The Git contract, one suite for every implementation: RealGit over the real git binary (a throwaway repo) and the same adapter over the
gitsim (tests/support/gitsim, which answers git's argv in process). A subclass sets `start()` (patch git in or not) and gets every test.
The world: origin `o.git`, the clone `repo` with one pushed commit on main, and `slot`, a detached worktree of origin/main."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from support.tags import contract  # noqa: F401  (re-exported for the subclasses)

from taskloop.contracts.ports import Git
from taskloop.contracts.slots import BranchPinned, DirtyTree, SlotGitError

_Base = unittest.TestCase if TYPE_CHECKING else object
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "gc.auto",
         "GIT_CONFIG_VALUE_0": "0"}


def sh(cwd: Path | str, *argv: str) -> str:
    r = subprocess.run(["git", *argv], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"git {' '.join(argv)}: {r.stderr}"
    return r.stdout.strip()


class GitContract(_Base):
    def make(self) -> Git:
        raise NotImplementedError

    def start(self) -> None:
        """Put git where this implementation reads it (the real binary needs nothing; the gitsim is patched in)."""
        raise NotImplementedError

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.home = Path(os.path.realpath(tmp.name))
        env = unittest.mock.patch.dict(os.environ, {**IDENT, "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "cfg")})
        env.start()
        self.addCleanup(env.stop)
        self.start()
        self.git = self.make()
        self.origin, self.repo, self.slot = self.home / "o.git", self.home / "repo", self.home / "repo" / ".slots" / "s1"
        sh(self.home, "init", "-q", "--bare", "-b", "main", str(self.origin))
        sh(self.home, "clone", "-q", str(self.origin), str(self.repo))
        (self.repo / "a.txt").write_text("a\n")
        sh(self.repo, "add", "-A")
        sh(self.repo, "commit", "-qm", "init")
        sh(self.repo, "push", "-q", "origin", "HEAD:main")
        self.git.add_worktree(str(self.repo), str(self.slot), "origin/main")

    def s(self) -> str:
        return str(self.slot)

    def test_a_new_worktree_is_detached_clean_and_listed_after_the_main_one(self) -> None:
        self.assertEqual(self.git.branch(self.s()), "")
        self.assertFalse(self.git.dirty(self.s()))
        self.assertFalse(self.git.rebasing(self.s()))
        found = self.git.checkouts(str(self.repo))
        self.assertEqual([(os.path.realpath(c.path), c.main) for c in found], [(str(self.repo), True), (str(self.slot), False)])
        self.assertEqual(found[0].branch, "main")
        self.assertEqual(found[1].branch, "")

    def test_a_branch_is_made_at_a_start_point_and_checked_out(self) -> None:
        self.assertFalse(self.git.has_branch(self.s(), "task/x"))
        self.git.checkout_new(self.s(), "task/x", "origin/main")
        self.assertEqual((self.git.branch(self.s()), self.git.has_branch(self.s(), "task/x")), ("task/x", True))
        self.git.checkout_detached(self.s(), "origin/main")
        self.assertEqual(self.git.branch(self.s()), "")
        self.git.checkout(self.s(), "task/x")
        self.assertEqual(self.git.branch(self.s()), "task/x")

    def test_a_change_makes_the_tree_dirty_and_commit_all_cleans_it(self) -> None:
        (self.slot / "f.txt").write_text("f\n")
        self.assertTrue(self.git.dirty(self.s()))
        self.git.commit_all(self.s(), "task/w", "wip")
        self.assertEqual((self.git.branch(self.s()), self.git.dirty(self.s())), ("task/w", False))
        self.assertEqual(sh(self.slot, "log", "-1", "--format=%s"), "wip")
        self.assertIn("f.txt", sh(self.slot, "show", "--name-only", "--format=", "HEAD"))

    def test_commit_all_stays_on_the_branch_it_is_on(self) -> None:
        self.git.checkout_new(self.s(), "task/on", "origin/main")
        (self.slot / "g.txt").write_text("g\n")
        self.git.commit_all(self.s(), "task/other", "more")
        self.assertEqual((self.git.branch(self.s()), self.git.has_branch(self.s(), "task/other")), ("task/on", False))

    def test_a_branch_held_by_another_worktree_is_pinned_there(self) -> None:
        with self.assertRaises(BranchPinned) as cm:
            self.git.checkout(self.s(), "main")
        self.assertEqual(os.path.realpath(cm.exception.where), str(self.repo))

    def test_checkout_over_a_conflicting_change_is_a_dirty_tree(self) -> None:
        self.git.checkout_new(self.s(), "task/a", "origin/main")
        (self.slot / "a.txt").write_text("a on a\n")
        self.git.commit_all(self.s(), "task/a", "a changes")
        self.git.checkout_detached(self.s(), "origin/main")
        (self.slot / "a.txt").write_text("local\n")
        with self.assertRaises(DirtyTree):
            self.git.checkout(self.s(), "task/a")

    def test_clean_removes_untracked_files_but_keeps_what_it_is_told(self) -> None:
        (self.slot / "junk.txt").write_text("j\n")
        (self.slot / "keep.me").write_text("k\n")
        self.git.clean(self.s(), ["keep.me"])
        self.assertEqual((self.slot / "junk.txt").exists(), False)
        self.assertEqual((self.slot / "keep.me").exists(), True)

    def test_fetch_brings_a_commit_pushed_to_origin(self) -> None:
        (self.repo / "b.txt").write_text("b\n")
        sh(self.repo, "add", "-A")
        sh(self.repo, "commit", "-qm", "second")
        sh(self.repo, "push", "-q", "origin", "HEAD:main")
        self.git.fetch(self.s())
        self.assertEqual(sh(self.slot, "rev-parse", "origin/main"), sh(self.repo, "rev-parse", "HEAD"))

    def test_fetch_from_a_missing_origin_is_a_git_error(self) -> None:
        sh(self.repo, "remote", "set-url", "origin", str(self.home / "gone.git"))
        with self.assertRaises(SlotGitError):
            self.git.fetch(str(self.repo))

    def test_rebase_abort_with_nothing_to_abort_changes_nothing(self) -> None:
        self.git.rebase_abort(self.s())
        self.assertEqual((self.git.rebasing(self.s()), self.git.dirty(self.s())), (False, False))

    def test_a_worktree_is_removed_once(self) -> None:
        self.assertTrue(self.git.remove_worktree(str(self.repo), str(self.slot)))
        self.assertEqual([c.main for c in self.git.checkouts(str(self.repo))], [True])
        self.assertFalse(self.git.remove_worktree(str(self.repo), str(self.slot)))

    def test_adding_a_worktree_on_a_missing_ref_is_a_git_error(self) -> None:
        with self.assertRaises(SlotGitError):
            self.git.add_worktree(str(self.repo), str(self.home / "w2"), "origin/nope")
