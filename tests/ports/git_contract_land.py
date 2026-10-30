"""The Git contract for what a task's land, close and checks ask: counts, unmerged paths, staged work, branch moves, the commit and
rebase outcomes that carry git's words. Mixed into the same two runs as git_contract.py (the gitsim, real git)."""

import os
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from ports.git_contract import sh
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import DirtyTree, SlotGitError

_Base = unittest.TestCase if TYPE_CHECKING else object


class LandContract(_Base):
    git: Git
    repo: Path
    slot: Path
    home: Path
    origin: Path

    def commit_file(self, d: Path, name: str, text: str, msg: str) -> str:
        raise NotImplementedError

    def conflicted(self) -> None:
        """The repo is on task/p, mid-rebase onto task/z, with a.txt in conflict."""
        sh(self.repo, "checkout", "-qb", "task/p")
        self.commit_file(self.repo, "a.txt", "mine\n", "a mine")
        sh(self.repo, "checkout", "-qb", "task/z", "origin/main")
        self.commit_file(self.repo, "a.txt", "theirs\n", "a theirs")
        sh(self.repo, "checkout", "-q", "task/p")
        self.assertFalse(self.git.rebase(str(self.repo), "task/z").ok)

    def test_count_numbers_the_commits_on_one_side_only(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/c")
        self.commit_file(self.repo, "c1.txt", "1\n", "c1")
        self.commit_file(self.repo, "c2.txt", "2\n", "c2")
        r = str(self.repo)
        self.assertEqual((self.git.count(r, ["HEAD"], ["origin/main"]), self.git.count(r, ["origin/main"], ["HEAD"])), (2, 0))
        self.assertEqual(self.git.count(r, ["HEAD"], ["task/c"]), 0)

    def test_unmerged_names_the_paths_a_stopped_rebase_left_in_conflict(self) -> None:
        self.assertEqual(self.git.unmerged(str(self.repo)), [])
        self.conflicted()
        self.assertEqual(self.git.unmerged(str(self.repo)), ["a.txt"])

    def test_rebase_continue_goes_on_once_the_conflict_is_staged(self) -> None:
        self.conflicted()
        (self.repo / "a.txt").write_text("both\n")
        self.git.stage_literal(str(self.repo), ["a.txt"])
        done = self.git.rebase_continue(str(self.repo))
        self.assertEqual((done.ok, self.git.rebasing(str(self.repo))), (True, False))
        self.assertEqual((self.repo / "a.txt").read_text(), "both\n")

    def test_rebase_continue_with_the_conflict_unresolved_says_so(self) -> None:
        self.conflicted()
        done = self.git.rebase_continue(str(self.repo))
        self.assertFalse(done.ok)
        self.assertTrue(done.output)
        self.git.rebase_abort(str(self.repo))

    def test_changed_paths_between_two_trees(self) -> None:
        d = str(self.slot)
        base = self.git.rev_parse(d, "HEAD")
        (self.slot / "a.txt").write_text("changed\n")
        (self.slot / "n.txt").write_text("n\n")
        tree = self.git.tree_of(d)
        self.assertEqual(sorted(self.git.changed_paths(d, base, tree)), ["a.txt", "n.txt"])
        self.assertEqual(self.git.changed_paths(d, base, "nope"), [])

    def test_staged_is_true_only_while_the_index_holds_uncommitted_work(self) -> None:
        r = str(self.repo)
        self.assertFalse(self.git.staged(r))
        (self.repo / "s.txt").write_text("s\n")
        self.assertFalse(self.git.staged(r))
        self.git.stage_literal(r, ["s.txt"])
        self.assertTrue(self.git.staged(r))

    def test_stage_literal_takes_names_as_given_and_stages_a_deletion(self) -> None:
        r = str(self.repo)
        (self.repo / "*.txt").write_text("star\n")
        (self.repo / "b.txt").write_text("b\n")
        self.git.stage_literal(r, ["*.txt"])
        self.assertEqual(sh(self.repo, "diff", "--cached", "--name-only"), "*.txt")
        os.remove(self.repo / "a.txt")
        self.git.stage_literal(r, ["a.txt"])
        self.assertEqual(sh(self.repo, "diff", "--cached", "--name-only").splitlines(), ["*.txt", "a.txt"])
        self.git.stage_literal(r, [])

    def test_status_lists_untracked_files_one_by_one_on_request(self) -> None:
        (self.slot / "d").mkdir()
        (self.slot / "d" / "x.txt").write_text("x\n")
        (self.slot / "d" / "y.txt").write_text("y\n")
        r = str(self.slot)
        self.assertEqual([x.path for x in self.git.status(r)], ["d/"])
        self.assertEqual([x.path for x in self.git.status(r, all_untracked=True)], ["d/x.txt", "d/y.txt"])

    def test_rename_branch_moves_the_branch_and_refuses_a_taken_name(self) -> None:
        r = str(self.repo)
        sh(self.repo, "branch", "task/old")
        sh(self.repo, "branch", "task/taken")
        self.git.rename_branch(r, "task/old", "task/new")
        self.assertEqual((self.git.has_branch(r, "task/old"), self.git.has_branch(r, "task/new")), (False, True))
        with self.assertRaises(SlotGitError):
            self.git.rename_branch(r, "task/new", "task/taken")

    def test_checkout_reset_points_the_branch_at_the_start_and_refuses_to_lose_changes(self) -> None:
        r = str(self.repo)
        sh(self.repo, "checkout", "-qb", "task/k")
        self.commit_file(self.repo, "k.txt", "k\n", "k")
        self.git.checkout_reset(r, "task/k", "origin/main")
        self.assertEqual(self.git.rev_parse(r, "task/k"), self.git.rev_parse(r, "origin/main"))
        self.assertEqual(self.git.branch(r), "task/k")
        sh(self.repo, "checkout", "-qb", "task/l")
        self.commit_file(self.repo, "a.txt", "l\n", "l")
        sh(self.repo, "checkout", "-q", "task/k")
        (self.repo / "a.txt").write_text("local\n")
        with self.assertRaises(DirtyTree):
            self.git.checkout_reset(r, "task/l", "task/l")

    def test_try_commit_reports_instead_of_raising_and_can_skip_hooks(self) -> None:
        r = str(self.repo)
        (self.repo / "h.txt").write_text("h\n")
        self.git.stage_literal(r, ["h.txt"])
        self.assertTrue(self.git.try_commit(r, "no hooks", verify=False).ok)
        self.assertEqual(sh(self.repo, "log", "-1", "--format=%s"), "no hooks")
        nothing = self.git.try_commit(r, "nothing staged")
        self.assertFalse(nothing.ok)
        self.assertTrue(nothing.output)
        self.assertTrue(self.git.try_commit(r, "empty", verify=False, allow_empty=True).ok)

    def test_amend_folds_the_staged_work_into_the_last_commit_with_its_message(self) -> None:
        r = str(self.repo)
        before = self.git.count(r, ["HEAD"])
        (self.repo / "m.txt").write_text("m\n")
        self.git.stage_literal(r, ["m.txt"])
        self.git.amend(r)
        self.assertEqual(self.git.count(r, ["HEAD"]), before)
        self.assertEqual(sh(self.repo, "log", "-1", "--format=%s"), "init")
        self.assertIn("m.txt", sh(self.repo, "show", "--name-only", "--format=", "HEAD"))

    def test_push_lease_replaces_a_remote_branch_only_while_it_is_the_one_last_fetched(self) -> None:
        r = str(self.repo)
        sh(self.repo, "checkout", "-qb", "task/w")
        first = self.commit_file(self.repo, "w.txt", "1\n", "w1")
        self.assertTrue(self.git.push_lease(r, "origin", "HEAD:refs/heads/task/w").ok)
        sh(self.repo, "fetch", "-q", "origin")
        sh(self.repo, "commit", "-q", "--amend", "-m", "w1 again")
        self.assertTrue(self.git.push_lease(r, "origin", "HEAD:refs/heads/task/w").ok)
        other = self.home / "other"
        sh(self.home, "clone", "-q", str(self.origin), str(other))
        sh(other, "checkout", "-q", "task/w")
        (other / "o.txt").write_text("o\n")
        sh(other, "add", "o.txt")
        sh(other, "commit", "-qm", "from elsewhere")
        sh(other, "push", "-q", "origin", "task/w")
        sh(self.repo, "commit", "-q", "--allow-empty", "-m", "w2")
        late = self.git.push_lease(r, "origin", "HEAD:refs/heads/task/w")
        self.assertFalse(late.ok)
        self.assertIn("stale info", late.output)
        self.assertNotEqual(first, self.git.rev_parse(str(self.origin), "refs/heads/task/w"))

    def test_unpinned_asks_the_same_repo_without_the_pin(self) -> None:
        free = self.git.unpinned()
        self.assertEqual(free.config_get(str(self.repo), "remote.origin.url"), str(self.origin))
        self.assertEqual(os.path.realpath(free.toplevel(str(self.slot))), str(self.slot))
