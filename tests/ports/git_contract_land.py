"""The Git contract for what a task's land, close and checks ask: counts, unmerged paths, staged work, branch moves, the commit and
rebase outcomes that carry git's words. Mixed into the same two runs as git_contract.py (the gitsim, real git)."""

import os
from pathlib import Path

import pytest
from support.case import Case

from ports.git_contract import sh
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import DirtyTree, SlotGitError

_Base = Case


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
        assert not self.git.rebase(str(self.repo), "task/z").ok

    def test_count_numbers_the_commits_on_one_side_only(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/c")
        self.commit_file(self.repo, "c1.txt", "1\n", "c1")
        self.commit_file(self.repo, "c2.txt", "2\n", "c2")
        r = str(self.repo)
        assert (self.git.count(r, ["HEAD"], ["origin/main"]), self.git.count(r, ["origin/main"], ["HEAD"])) == (2, 0)
        assert self.git.count(r, ["HEAD"], ["task/c"]) == 0

    def test_unmerged_names_the_paths_a_stopped_rebase_left_in_conflict(self) -> None:
        assert self.git.unmerged(str(self.repo)) == []
        self.conflicted()
        assert self.git.unmerged(str(self.repo)) == ["a.txt"]

    def test_rebase_continue_goes_on_once_the_conflict_is_staged(self) -> None:
        self.conflicted()
        (self.repo / "a.txt").write_text("both\n")
        self.git.stage_literal(str(self.repo), ["a.txt"])
        done = self.git.rebase_continue(str(self.repo))
        assert (done.ok, self.git.rebasing(str(self.repo))) == (True, False)
        assert (self.repo / "a.txt").read_text() == "both\n"

    def test_rebase_continue_with_the_conflict_unresolved_says_so(self) -> None:
        self.conflicted()
        done = self.git.rebase_continue(str(self.repo))
        assert not done.ok
        assert done.output
        self.git.rebase_abort(str(self.repo))

    def test_changed_paths_between_two_trees(self) -> None:
        d = str(self.slot)
        base = self.git.rev_parse(d, "HEAD")
        (self.slot / "a.txt").write_text("changed\n")
        (self.slot / "n.txt").write_text("n\n")
        tree = self.git.tree_of(d)
        assert sorted(self.git.changed_paths(d, base, tree)) == ["a.txt", "n.txt"]
        assert self.git.changed_paths(d, base, "nope") == []

    def test_diff_entries_find_exact_renames_and_can_ignore_whitespace(self) -> None:
        d = str(self.slot)
        (self.slot / "w.txt").write_text("a  b\n")
        (self.slot / "r.txt").write_text("rename me\n")
        sh(self.slot, "add", "-A")
        sh(self.slot, "commit", "-qm", "w")
        base = self.git.rev_parse(d, "HEAD")
        (self.slot / "w.txt").write_text("a b\n")
        (self.slot / "r.txt").rename(self.slot / "r2.txt")
        (self.slot / "n.txt").write_text("n\n")
        tree = self.git.tree_of(d)
        got = {(e.status, e.path, e.old) for e in self.git.diff_entries(d, base, tree)}
        assert got == {("M", "w.txt", ""), ("R", "r2.txt", "r.txt"), ("A", "n.txt", "")}
        loud = {(e.status, e.path) for e in self.git.diff_entries(d, base, tree, ignore_space=True)}
        assert loud == {("R", "r2.txt"), ("A", "n.txt")}
        assert self.git.diff_entries(d, base, "nope") == []

    def test_staged_is_true_only_while_the_index_holds_uncommitted_work(self) -> None:
        r = str(self.repo)
        assert not self.git.staged(r)
        (self.repo / "s.txt").write_text("s\n")
        assert not self.git.staged(r)
        self.git.stage_literal(r, ["s.txt"])
        assert self.git.staged(r)

    def test_stage_literal_takes_names_as_given_and_stages_a_deletion(self) -> None:
        r = str(self.repo)
        (self.repo / "*.txt").write_text("star\n")
        (self.repo / "b.txt").write_text("b\n")
        self.git.stage_literal(r, ["*.txt"])
        assert sh(self.repo, "diff", "--cached", "--name-only") == "*.txt"
        os.remove(self.repo / "a.txt")
        self.git.stage_literal(r, ["a.txt"])
        assert sh(self.repo, "diff", "--cached", "--name-only").splitlines() == ["*.txt", "a.txt"]
        self.git.stage_literal(r, [])

    def test_status_lists_untracked_files_one_by_one_on_request(self) -> None:
        (self.slot / "d").mkdir()
        (self.slot / "d" / "x.txt").write_text("x\n")
        (self.slot / "d" / "y.txt").write_text("y\n")
        r = str(self.slot)
        assert [x.path for x in self.git.status(r)] == ["d/"]
        assert [x.path for x in self.git.status(r, all_untracked=True)] == ["d/x.txt", "d/y.txt"]

    def test_rename_branch_moves_the_branch_and_refuses_a_taken_name(self) -> None:
        r = str(self.repo)
        sh(self.repo, "branch", "task/old")
        sh(self.repo, "branch", "task/taken")
        self.git.rename_branch(r, "task/old", "task/new")
        assert (self.git.has_branch(r, "task/old"), self.git.has_branch(r, "task/new")) == (False, True)
        with pytest.raises(SlotGitError):
            self.git.rename_branch(r, "task/new", "task/taken")

    def test_checkout_reset_points_the_branch_at_the_start_and_refuses_to_lose_changes(self) -> None:
        r = str(self.repo)
        sh(self.repo, "checkout", "-qb", "task/k")
        self.commit_file(self.repo, "k.txt", "k\n", "k")
        self.git.checkout_reset(r, "task/k", "origin/main")
        assert self.git.rev_parse(r, "task/k") == self.git.rev_parse(r, "origin/main")
        assert self.git.branch(r) == "task/k"
        sh(self.repo, "checkout", "-qb", "task/l")
        self.commit_file(self.repo, "a.txt", "l\n", "l")
        sh(self.repo, "checkout", "-q", "task/k")
        (self.repo / "a.txt").write_text("local\n")
        with pytest.raises(DirtyTree):
            self.git.checkout_reset(r, "task/l", "task/l")

    def test_try_commit_reports_instead_of_raising_and_can_skip_hooks(self) -> None:
        r = str(self.repo)
        (self.repo / "h.txt").write_text("h\n")
        self.git.stage_literal(r, ["h.txt"])
        assert self.git.try_commit(r, "no hooks", verify=False).ok
        assert sh(self.repo, "log", "-1", "--format=%s") == "no hooks"
        nothing = self.git.try_commit(r, "nothing staged")
        assert not nothing.ok
        assert nothing.output
        assert self.git.try_commit(r, "empty", verify=False, allow_empty=True).ok

    def test_amend_folds_the_staged_work_into_the_last_commit_with_its_message(self) -> None:
        r = str(self.repo)
        before = self.git.count(r, ["HEAD"])
        (self.repo / "m.txt").write_text("m\n")
        self.git.stage_literal(r, ["m.txt"])
        self.git.amend(r)
        assert self.git.count(r, ["HEAD"]) == before
        assert sh(self.repo, "log", "-1", "--format=%s") == "init"
        assert "m.txt" in sh(self.repo, "show", "--name-only", "--format=", "HEAD")

    def test_push_lease_replaces_a_remote_branch_only_while_it_is_the_one_last_fetched(self) -> None:
        r = str(self.repo)
        sh(self.repo, "checkout", "-qb", "task/w")
        first = self.commit_file(self.repo, "w.txt", "1\n", "w1")
        seen = lambda: self.git.rev_parse(r, "refs/remotes/origin/task/w") or ""  # noqa: E731
        assert self.git.push_lease(r, "origin", "HEAD:refs/heads/task/w", seen()).ok
        sh(self.repo, "fetch", "-q", "origin")
        sh(self.repo, "commit", "-q", "--amend", "-m", "w1 again")
        assert self.git.push_lease(r, "origin", "HEAD:refs/heads/task/w", seen()).ok
        other = self.home / "other"
        sh(self.home, "clone", "-q", str(self.origin), str(other))
        sh(other, "checkout", "-q", "task/w")
        (other / "o.txt").write_text("o\n")
        sh(other, "add", "o.txt")
        sh(other, "commit", "-qm", "from elsewhere")
        sh(other, "push", "-q", "origin", "task/w")
        sh(self.repo, "commit", "-q", "--allow-empty", "-m", "w2")
        late = self.git.push_lease(r, "origin", "HEAD:refs/heads/task/w", seen())
        assert not late.ok
        assert "stale info" in late.output
        assert first != self.git.rev_parse(str(self.origin), "refs/heads/task/w")

    def test_unpinned_asks_the_same_repo_without_the_pin(self) -> None:
        free = self.git.unpinned()
        assert free.config_get(str(self.repo), "remote.origin.url") == str(self.origin)
        assert os.path.realpath(free.toplevel(str(self.slot))) == str(self.slot)
