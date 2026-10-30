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
        self.git.init_bare(str(self.origin), "main")
        self.git.clone(str(self.origin), str(self.repo))
        (self.repo / "a.txt").write_text("a\n")
        self.git.commit_all(str(self.repo), "main", "init")
        self.git.push(str(self.repo), "origin", "HEAD:main")
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


    # -- the ops that return rows ------------------------------------------------------------------------------------------------

    def commit_file(self, d: Path, name: str, text: str, msg: str) -> str:
        (d / name).write_text(text)
        sh(d, "add", name)
        sh(d, "commit", "-qm", msg)
        return sh(d, "rev-parse", "HEAD")

    def test_for_each_ref_lists_the_refs_under_the_prefixes_with_their_oids(self) -> None:
        main = sh(self.repo, "rev-parse", "HEAD")
        sh(self.repo, "branch", "task/a")
        sh(self.repo, "branch", "wip/b")
        rows = self.git.for_each_ref(str(self.repo), "refs/heads/task/", "refs/heads/wip/")
        self.assertEqual([(r.name, r.oid) for r in rows], [("refs/heads/task/a", main), ("refs/heads/wip/b", main)])
        every = [r.name for r in self.git.for_each_ref(str(self.repo), "refs/heads/")]
        self.assertEqual(every, ["refs/heads/main", "refs/heads/task/a", "refs/heads/wip/b"])
        self.assertEqual(self.git.for_each_ref(str(self.repo), "refs/heads/nope/"), [])

    def test_ls_remote_shows_the_remotes_refs_that_match(self) -> None:
        main = sh(self.repo, "rev-parse", "HEAD")
        sh(self.repo, "branch", "task/x")
        sh(self.repo, "push", "-q", "origin", "task/x")
        rows = self.git.ls_remote(str(self.repo), "origin", "refs/heads/task/*")
        self.assertEqual([(r.name, r.oid) for r in rows], [("refs/heads/task/x", main)])
        self.assertEqual(self.git.ls_remote(str(self.repo), "origin", "refs/heads/zzz/*"), [])

    def test_ls_remote_of_a_missing_remote_is_a_git_error(self) -> None:
        sh(self.repo, "remote", "set-url", "origin", str(self.home / "gone.git"))
        with self.assertRaises(SlotGitError):
            self.git.ls_remote(str(self.repo), "origin")

    def test_cherry_marks_a_commit_whose_patch_is_already_upstream(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/c")
        mine = self.commit_file(self.repo, "c.txt", "c\n", "mine")
        sh(self.repo, "checkout", "-q", "main")
        sh(self.repo, "checkout", "-qb", "twin", "origin/main")
        self.commit_file(self.repo, "c.txt", "c\n", "twin of mine")
        sh(self.repo, "checkout", "-qb", "task/d", "origin/main")
        fresh = self.commit_file(self.repo, "d.txt", "d\n", "fresh")
        self.assertEqual([(p.oid, p.upstream) for p in self.git.cherry(str(self.repo), "twin", "task/c")], [(mine, True)])
        self.assertEqual([(p.oid, p.upstream) for p in self.git.cherry(str(self.repo), "twin", "task/d")], [(fresh, False)])

    def test_merged_lists_the_branches_whose_tip_is_on_the_ref(self) -> None:
        main = sh(self.repo, "rev-parse", "HEAD")
        sh(self.repo, "branch", "task/old")
        sh(self.repo, "checkout", "-qb", "task/new")
        self.commit_file(self.repo, "n.txt", "n\n", "new")
        sh(self.repo, "checkout", "-q", "main")
        rows = {r.name: r.oid for r in self.git.merged(str(self.repo), "main")}
        self.assertEqual(rows, {"main": main, "task/old": main})

    def test_merge_base_and_is_ancestor(self) -> None:
        base = sh(self.repo, "rev-parse", "HEAD")
        sh(self.repo, "checkout", "-qb", "task/m")
        tip = self.commit_file(self.repo, "m.txt", "m\n", "m")
        self.assertEqual(self.git.merge_base(str(self.repo), "task/m", "origin/main"), base)
        self.assertTrue(self.git.is_ancestor(str(self.repo), base, tip))
        self.assertFalse(self.git.is_ancestor(str(self.repo), tip, base))
        self.assertEqual(self.git.merge_base(str(self.repo), "task/m", "nope"), "")

    def test_rev_parse_and_has_commit_answer_empty_for_what_is_not_there(self) -> None:
        head = sh(self.repo, "rev-parse", "HEAD")
        self.assertEqual((self.git.rev_parse(str(self.repo), "main"), self.git.rev_parse(str(self.repo), "nope")), (head, ""))
        self.assertEqual((self.git.has_commit(str(self.repo), head), self.git.has_commit(str(self.repo), "1" * 40)), (True, False))

    def test_log_rows_come_newest_first_and_can_be_cut_by_exclusion_limit_and_text(self) -> None:
        base = sh(self.repo, "rev-parse", "HEAD")
        one = self.commit_file(self.repo, "1.txt", "1\n", "one (x-1)")
        two = self.commit_file(self.repo, "2.txt", "2\n", "two")
        rows = self.git.log(str(self.repo), ["main"], [base])
        self.assertEqual([(r.oid, r.subject) for r in rows], [(two, "two"), (one, "one (x-1)")])
        self.assertTrue(all(r.time > 0 for r in rows))
        self.assertEqual([r.oid for r in self.git.log(str(self.repo), ["main"], limit=1)], [two])
        self.assertEqual([r.oid for r in self.git.log(str(self.repo), ["main"], grep="(x-1)", limit=1)], [one])
        self.assertEqual(self.git.log(str(self.repo), ["main"], grep="(x-9)"), [])

    def test_ls_tree_lists_files_and_folders(self) -> None:
        self.commit_file(self.repo, "a2.txt", "a2\n", "a2")
        (self.repo / "sub").mkdir()
        self.commit_file(self.repo, "sub/s.txt", "s\n", "s")
        flat = self.git.ls_tree(str(self.repo), "HEAD")
        self.assertEqual([(e.kind, e.path) for e in flat], [("blob", "a.txt"), ("blob", "a2.txt"), ("tree", "sub")])
        deep = self.git.ls_tree(str(self.repo), "HEAD", recursive=True)
        self.assertEqual([e.path for e in deep], ["a.txt", "a2.txt", "sub/s.txt"])
        self.assertEqual([e.path for e in self.git.ls_tree(str(self.repo), "HEAD", "a.txt")], ["a.txt"])
        self.assertRegex(deep[0].oid, r"^[0-9a-f]{40}$")

    def test_status_rows_name_the_changed_staged_and_untracked_paths(self) -> None:
        self.assertEqual(self.git.status(self.s()), [])
        (self.slot / "a.txt").write_text("changed\n")
        (self.slot / "new.txt").write_text("n\n")
        (self.slot / "staged.txt").write_text("s\n")
        sh(self.slot, "add", "staged.txt")
        rows = {r.path: (r.index, r.work) for r in self.git.status(self.s())}
        self.assertEqual(rows, {"a.txt": (" ", "M"), "new.txt": ("?", "?"), "staged.txt": ("A", " ")})
        self.assertEqual([r.path for r in self.git.status(self.s()) if r.untracked], ["new.txt"])

    def test_check_ignore_names_the_paths_the_excludes_cover(self) -> None:
        ex = self.home / "ex"
        ex.write_text("*.log\n")
        self.assertEqual(self.git.check_ignore(self.s(), ["x.log", "y.txt"], str(ex)), ["x.log"])
        self.assertEqual(self.git.check_ignore(self.s(), ["y.txt"], str(ex)), [])
        self.assertEqual(self.git.check_ignore(self.s(), []), [])

    def test_git_dir_is_the_worktrees_own_admin_folder(self) -> None:
        self.assertEqual(os.path.realpath(self.git.git_dir(self.s())), os.path.realpath(sh(self.slot, "rev-parse", "--absolute-git-dir")))
        self.assertEqual(self.git.git_dir(str(self.home / "nowhere")), "")

    def test_reset_moves_head_and_hard_resets_the_files(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/r")
        first = sh(self.repo, "rev-parse", "HEAD")
        self.commit_file(self.repo, "r.txt", "r\n", "r")
        self.git.reset(str(self.repo), first, "soft")
        self.assertEqual(sh(self.repo, "rev-parse", "HEAD"), first)
        self.assertIn("A  r.txt", sh(self.repo, "status", "--porcelain"))
        self.git.reset(str(self.repo), "HEAD", "mixed")
        self.assertIn("?? r.txt", sh(self.repo, "status", "--porcelain"))
        (self.repo / "a.txt").write_text("dirty\n")
        self.git.reset(str(self.repo), "HEAD", "hard")
        self.assertEqual((self.repo / "a.txt").read_text(), "a\n")
        with self.assertRaises(SlotGitError):
            self.git.reset(str(self.repo), "nope", "hard")

    def test_rebase_replays_onto_a_moved_base_and_reports_a_conflict(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/p")
        self.commit_file(self.repo, "p.txt", "p\n", "p")
        self.commit_file(self.repo, "a.txt", "mine\n", "a mine")
        sh(self.repo, "checkout", "-q", "main")
        self.commit_file(self.repo, "q.txt", "q\n", "q")
        sh(self.repo, "checkout", "-q", "task/p")
        ok = self.git.rebase(str(self.repo), "main", update_refs=False)
        self.assertEqual((ok.ok, self.git.rebasing(str(self.repo))), (True, False))
        self.assertTrue((self.repo / "q.txt").exists())
        sh(self.repo, "checkout", "-qb", "task/z", "origin/main")
        self.commit_file(self.repo, "a.txt", "theirs\n", "a theirs")
        sh(self.repo, "checkout", "-q", "task/p")
        bad = self.git.rebase(str(self.repo), "task/z")
        self.assertFalse(bad.ok)
        self.assertTrue(self.git.rebasing(str(self.repo)))
        self.git.rebase_abort(str(self.repo))
        self.assertFalse(self.git.rebasing(str(self.repo)))

    def test_tag_names_a_commit_once(self) -> None:
        head = sh(self.repo, "rev-parse", "HEAD")
        self.git.tag(str(self.repo), "v1", "HEAD")
        self.assertEqual([(r.name, r.oid) for r in self.git.for_each_ref(str(self.repo), "refs/tags/")], [("refs/tags/v1", head)])
        with self.assertRaises(SlotGitError):
            self.git.tag(str(self.repo), "v1", "HEAD")

    def test_a_branch_is_deleted_only_while_it_is_at_the_oid_that_was_checked(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/del")
        old = sh(self.repo, "rev-parse", "HEAD")
        self.commit_file(self.repo, "d.txt", "d\n", "moved on")
        sh(self.repo, "checkout", "-q", "main")
        with self.assertRaises(SlotGitError):
            self.git.delete_branch_at(str(self.repo), "task/del", old)
        self.assertTrue(self.git.has_branch(str(self.repo), "task/del"))
        self.git.delete_branch_at(str(self.repo), "task/del", sh(self.repo, "rev-parse", "task/del"))
        self.assertFalse(self.git.has_branch(str(self.repo), "task/del"))

    def test_a_remote_branch_is_deleted_only_while_it_is_at_the_oid_that_was_checked(self) -> None:
        sh(self.repo, "checkout", "-qb", "task/rem")
        old = sh(self.repo, "rev-parse", "HEAD")
        sh(self.repo, "push", "-q", "origin", "task/rem")
        self.commit_file(self.repo, "r2.txt", "r\n", "moved on")
        sh(self.repo, "push", "-q", "origin", "task/rem")
        with self.assertRaises(SlotGitError):
            self.git.delete_remote_at(str(self.repo), "origin", "refs/heads/task/rem", old)
        self.assertEqual(len(self.git.ls_remote(str(self.repo), "origin", "refs/heads/task/rem")), 1)
        self.git.delete_remote_at(str(self.repo), "origin", "refs/heads/task/rem", sh(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(self.git.ls_remote(str(self.repo), "origin", "refs/heads/task/rem"), [])

    # -- what a release's clone does ---------------------------------------------------------------------------------------------

    def test_clean_with_ignored_also_removes_what_the_ignore_rules_hide(self) -> None:
        (self.repo / ".gitignore").write_text("*.o\n.slots/\n")
        sh(self.repo, "add", ".gitignore")
        sh(self.repo, "commit", "-qm", "ignore")
        (self.repo / "x.o").write_text("o\n")
        self.git.clean(str(self.repo), [])
        self.assertTrue((self.repo / "x.o").exists())
        self.git.clean(str(self.repo), [], ignored=True)
        self.assertFalse((self.repo / "x.o").exists())

    def test_checkout_force_resets_a_branch_to_the_start_and_drops_local_changes(self) -> None:
        sh(self.repo, "checkout", "-qb", "side")
        self.commit_file(self.repo, "side.txt", "s\n", "side")
        (self.repo / "a.txt").write_text("dirty\n")
        self.git.checkout_force(str(self.repo), "main", "origin/main")
        self.assertEqual((self.git.branch(str(self.repo)), (self.repo / "a.txt").read_text()), ("main", "a\n"))
        self.assertFalse((self.repo / "side.txt").exists())

    def test_fetch_ref_brings_one_ref_of_another_repository_to_fetch_head(self) -> None:
        other = self.home / "other"
        sh(self.home, "clone", "-q", str(self.origin), str(other))
        sh(other, "checkout", "-qb", "task/o")
        tip = self.commit_file(other, "o.txt", "o\n", "o")
        self.git.fetch_ref(str(self.repo), str(other), "task/o")
        self.assertEqual(self.git.rev_parse(str(self.repo), "FETCH_HEAD"), tip)
        with self.assertRaises(SlotGitError):
            self.git.fetch_ref(str(self.repo), str(other), "task/none")

    def test_remote_url_is_the_remotes_url_or_empty(self) -> None:
        self.assertEqual(os.path.realpath(self.git.remote_url(str(self.repo), "origin")), str(self.origin))
        self.assertEqual(self.git.remote_url(str(self.repo), "nope"), "")

    def test_merge_ff_moves_forward_and_refuses_a_diverged_branch(self) -> None:
        other = self.home / "other"
        sh(self.home, "clone", "-q", str(self.origin), str(other))
        tip = self.commit_file(other, "n.txt", "n\n", "n")
        sh(other, "push", "-q", "origin", "HEAD:main")
        self.git.fetch(str(self.repo))
        self.git.merge_ff(str(self.repo), "origin/main")
        self.assertEqual(sh(self.repo, "rev-parse", "HEAD"), tip)
        self.commit_file(self.repo, "m.txt", "m\n", "m")
        self.commit_file(other, "k.txt", "k\n", "k")
        sh(other, "push", "-q", "origin", "HEAD:main")
        self.git.fetch(str(self.repo))
        with self.assertRaises(SlotGitError):
            self.git.merge_ff(str(self.repo), "origin/main")

    def test_commit_tracked_leaves_untracked_files_out(self) -> None:
        (self.repo / "a.txt").write_text("changed\n")
        (self.repo / "new.txt").write_text("n\n")
        self.git.commit_tracked(str(self.repo), "tracked only")
        self.assertEqual(sh(self.repo, "show", "--name-only", "--format=", "HEAD"), "a.txt")
        self.assertEqual(sh(self.repo, "log", "-1", "--format=%s"), "tracked only")

    def test_pull_rebase_replays_local_commits_on_the_remotes_new_ones(self) -> None:
        other = self.home / "other"
        sh(self.home, "clone", "-q", str(self.origin), str(other))
        self.commit_file(other, "n.txt", "n\n", "n")
        sh(other, "push", "-q", "origin", "HEAD:main")
        self.commit_file(self.repo, "m.txt", "m\n", "m")
        self.git.pull_rebase(str(self.repo), "origin", "main")
        self.assertEqual(sh(self.repo, "log", "--format=%s", "-2"), "m\nn")

    # -- files, config and the work tree ---------------------------------------------------------------------------------------

    def test_show_reads_a_file_at_a_rev_and_refuses_a_missing_one(self) -> None:
        self.assertEqual(self.git.show(str(self.repo), "origin/main", "a.txt"), "a\n")
        with self.assertRaises(SlotGitError):
            self.git.show(str(self.repo), "origin/main", "nope.txt")

    def test_ls_files_lists_tracked_unignored_and_ignored_files(self) -> None:
        (self.repo / ".gitignore").write_text("*.log\n")
        (self.repo / "x.log").write_text("l\n")
        (self.repo / "new.txt").write_text("n\n")
        self.git.stage(str(self.repo), ".gitignore")
        self.assertEqual(self.git.ls_files(str(self.repo)), [".gitignore", "a.txt"])
        loose = [p for p in self.git.ls_files(str(self.repo), "unignored") if not p.startswith(".slots")]
        self.assertEqual(sorted(loose), [".gitignore", "a.txt", "new.txt"])
        self.assertEqual(self.git.ls_files(str(self.repo), "ignored"), ["x.log"])
        self.assertEqual(self.git.ls_files(str(self.repo), "ignored", "*.txt"), [])

    def test_grep_finds_lines_of_tracked_files_by_regex_or_whole_word(self) -> None:
        (self.repo / "b.txt").write_text("one\n<<<<<<< x\nfoobar foo\n")
        self.git.stage(str(self.repo), "b.txt")
        self.assertEqual([(h.path, h.line, h.text) for h in self.git.grep(str(self.repo), r"^(<<<<<<<|>>>>>>>)( |$)")],
                         [("b.txt", 2, "<<<<<<< x")])
        self.assertEqual([h.line for h in self.git.grep(str(self.repo), "foo", fixed=True, word=True)], [3])
        self.assertEqual(self.git.grep(str(self.repo), "absent", fixed=True), [])

    def test_stage_and_commit_staged_commit_only_what_was_staged(self) -> None:
        (self.repo / "a.txt").write_text("changed\n")
        (self.repo / "s.txt").write_text("s\n")
        self.git.stage(str(self.repo), "s.txt")
        self.git.commit_staged(str(self.repo), "staged")
        self.assertEqual(sh(self.repo, "show", "--name-only", "--format=", "HEAD"), "s.txt")

    def test_config_get_entries_and_the_dirs(self) -> None:
        self.assertEqual(self.git.config_get(str(self.repo), "remote.origin.url"), str(self.origin))
        self.assertEqual(self.git.config_get(str(self.repo), "no.such"), "")
        self.assertEqual([(e.key, e.value) for e in self.git.config_entries(str(self.repo), r"^remote\.origin\.url$")],
                         [("remote.origin.url", str(self.origin))])
        self.assertEqual(self.git.config_entries(str(self.repo), r"^no\.such$"), [])
        self.assertEqual(os.path.realpath(self.git.common_dir(str(self.slot))), str(self.repo / ".git"))
        self.assertEqual(os.path.realpath(self.git.toplevel(str(self.slot))), str(self.slot))
        self.assertEqual(self.git.common_dir(str(self.home)), "")

    def test_tree_of_is_the_tree_the_work_tree_would_commit_and_leaves_the_index_alone(self) -> None:
        clean = self.git.tree_of(self.s())
        self.assertEqual(clean, sh(self.slot, "rev-parse", "HEAD^{tree}"))
        (self.slot / "f.txt").write_text("f\n")
        self.assertNotEqual(self.git.tree_of(self.s()), clean)
        self.assertEqual(sh(self.slot, "status", "--porcelain"), "?? f.txt")

    def test_worktree_state_changes_with_the_work_tree(self) -> None:
        before = self.git.worktree_state(self.s())
        assert before is not None
        (self.slot / "f.txt").write_text("f\n")
        after = self.git.worktree_state(self.s())
        assert after is not None
        self.assertIn(b"f.txt", after)
        self.assertNotEqual(before, after)
        self.assertIsNone(self.git.worktree_state(str(self.home)))

    def test_diff_between_trees_leaves_out_excluded_paths(self) -> None:
        base = self.git.rev_parse(self.s(), "HEAD")
        (self.slot / "a.txt").write_text("changed\n")
        (self.slot / "n.txt").write_text("n\n")
        tree = self.git.tree_of(self.s())
        both = self.git.diff(self.s(), base, tree)
        self.assertTrue("a.txt" in both and "n.txt" in both)
        only = self.git.diff(self.s(), base, tree, exclude=["n.txt"])
        self.assertTrue("a.txt" in only and "n.txt" not in only)
        self.assertIn("a.txt", self.git.diff(self.s(), base, tree, stat=True))

    def test_a_forced_worktree_is_added_removed_and_pruned(self) -> None:
        extra = str(self.home / "extra")
        self.git.add_worktree_force(str(self.repo), extra, "origin/main")
        self.assertTrue((self.home / "extra" / "a.txt").is_file())
        self.git.remove_worktree_force(str(self.repo), extra)
        self.git.prune_worktrees(str(self.repo))
        self.assertFalse((self.home / "extra").exists())
