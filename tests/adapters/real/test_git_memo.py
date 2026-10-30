"""The git answers the engine remembers (the port's rev_parse, branch and merge_base, slotcheck.tree_problem, Engine.tree_hash) stay
right when the repo changes under them.
Real git in a temp repo; each case changes the repo behind the memo and asks again."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
from taskloop.adapters import slotcheck, treehash  # noqa: E402
from taskloop.adapters.git import RealGit  # noqa: E402
from taskloop.app.run import engine  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402


def sh(*a, cwd):
    return subprocess.run(list(a), cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


class GitMemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.git = RealGit(snapshot())
        self.repo = Path(os.path.realpath(self.tmp.name)) / "r"
        self.repo.mkdir()
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "a@b"], ["config", "user.name", "n"]):
            sh("git", *a, cwd=self.repo)
        (self.repo / "f.txt").write_text("1\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "one", cwd=self.repo)

    def calls(self, fn):
        real, n = subprocess.Popen, [0]

        class P(real):
            def __init__(s, *a, **k):
                n[0] += 1
                super().__init__(*a, **k)
        with mock.patch.object(subprocess, "Popen", P):
            return fn(), n[0]

    def test_head_and_branch_follow_a_commit_and_a_checkout(self):
        r = self.repo
        first = self.git.rev_parse(str(r), "HEAD")
        self.assertEqual(self.git.branch(str(r)), "main")
        self.assertEqual(self.calls(lambda: self.git.rev_parse(str(r), "HEAD"))[1], 0)
        (r / "f.txt").write_text("2\n")
        sh("git", "commit", "-qam", "two", cwd=r)
        self.assertNotEqual(self.git.rev_parse(str(r), "HEAD"), first)
        sh("git", "checkout", "-qb", "other", cwd=r)
        self.assertEqual(self.git.branch(str(r)), "other")
        sh("git", "checkout", "-q", "--detach", cwd=r)
        self.assertEqual(self.git.branch(str(r)), "")

    def test_a_missing_branch_is_found_once_it_exists_and_after_pack_refs(self):
        r = self.repo
        self.assertEqual(self.git.rev_parse(str(r), "refs/heads/x"), "")
        sh("git", "branch", "x", cwd=r)
        self.assertTrue(self.git.rev_parse(str(r), "refs/heads/x"))
        sh("git", "pack-refs", "--all", cwd=r)
        self.assertTrue(self.git.rev_parse(str(r), "refs/heads/x"))
        sh("git", "branch", "-D", "x", cwd=r)
        self.assertEqual(self.git.rev_parse(str(r), "refs/heads/x"), "")

    def test_merge_base_follows_the_branch_it_is_asked_about(self):
        r = self.repo
        sh("git", "branch", "base", cwd=r)
        a = self.git.merge_base(str(r), "base", "HEAD")
        (r / "f.txt").write_text("2\n")
        sh("git", "commit", "-qam", "two", cwd=r)
        self.assertEqual(self.git.merge_base(str(r), "base", "HEAD"), a)
        sh("git", "branch", "-f", "base", "HEAD", cwd=r)
        self.assertEqual(self.git.merge_base(str(r), "base", "HEAD"), self.git.rev_parse(str(r), "HEAD"))

    def test_tree_problem_is_asked_again_when_the_config_changes(self):
        r = self.repo
        self.assertIsNone(slotcheck.tree_problem(r, self.git.unpinned(), snapshot()))
        self.assertEqual(self.calls(lambda: slotcheck.tree_problem(r, self.git.unpinned(), snapshot()))[1], 0)
        sh("git", "config", "core.bare", "true", cwd=r)
        bad = slotcheck.tree_problem(r, self.git.unpinned(), snapshot())
        assert bad
        self.assertEqual(bad[0], "core.bare is true")
        sh("git", "config", "core.bare", "false", cwd=r)
        sh("git", "config", "core.worktree", str(r.parent), cwd=r)
        bad = slotcheck.tree_problem(r, self.git.unpinned(), snapshot())
        assert bad
        self.assertTrue(bad[0].startswith("core.worktree is set (file:"), bad)
        self.assertIn(f" = {r.parent})", bad[0])
        sh("git", "config", "--unset", "core.worktree", cwd=r)
        self.assertIsNone(slotcheck.tree_problem(r, self.git.unpinned(), snapshot()))

    def test_tree_hash_sees_a_second_edit_of_an_already_modified_file(self):
        r = self.repo
        eng = engine.Engine.__new__(engine.Engine)
        eng.wt, eng.git = str(r), self.git
        (r / "f.txt").write_text("2\n")
        a = eng.checkout.tree_hash()
        self.assertEqual(self.calls(eng.checkout.tree_hash), (a, 1))  # one git status, no read-tree / add / write-tree
        (r / "f.txt").write_text("3\n")  # status still says ' M'; the size is the same
        b = eng.checkout.tree_hash()
        self.assertNotEqual(a, b)
        (r / "new.txt").write_text("x")
        c = eng.checkout.tree_hash()
        self.assertNotEqual(b, c)
        (r / "new.txt").unlink()
        self.assertEqual(eng.checkout.tree_hash(), b)
        sh("git", "commit", "-qam", "three", cwd=r)
        self.assertEqual(eng.checkout.tree_hash(), self.git.rev_parse(str(r), "HEAD^{tree}"))

    def test_tree_hash_raises_when_read_tree_or_add_fails_instead_of_hashing_the_wrong_tree(self):
        eng = engine.Engine.__new__(engine.Engine)
        eng.wt, eng.git = str(self.repo), self.git
        (self.repo / "f.txt").write_text("2\n")
        real = subprocess.run
        for failing in ("read-tree", "add", "write-tree"):
            def run(cmd, *a, _failing=failing, **k):
                if _failing in cmd:
                    return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: planted")
                return real(cmd, *a, **k)
            with self.subTest(failing), mock.patch.object(subprocess, "run", run):
                eng.tree_memo = None
                with self.assertRaises(treehash.TreeHashError) as got:
                    eng.checkout.tree_hash()
                self.assertIn(failing, str(got.exception))
        self.assertTrue(eng.checkout.tree_hash())

    def test_tree_hash_sees_two_same_size_edits_within_one_timestamp_tick(self):
        r = self.repo
        eng = engine.Engine.__new__(engine.Engine)
        eng.wt, eng.git = str(r), self.git
        f = r / "f.txt"
        f.write_text("2\n")
        stamp = os.stat(f).st_mtime_ns
        a = eng.checkout.tree_hash()
        f.write_text("3\n")  # same size, same inode (rewritten in place) ...
        os.utime(f, ns=(stamp, stamp))  # ... and the same mtime_ns: size, mtime and inode cannot tell the two edits apart
        self.assertEqual(os.stat(f).st_mtime_ns, stamp)
        self.assertNotEqual(eng.checkout.tree_hash(), a)

    def test_tree_hash_follows_a_commit_and_a_checkout_made_by_another_process(self):
        r = self.repo
        eng = engine.Engine.__new__(engine.Engine)
        eng.wt, eng.git = str(r), self.git
        (r / "f.txt").write_text("2\n")
        dirty = eng.checkout.tree_hash()
        self.assertEqual(eng.checkout.tree_hash(), dirty)  # remembered
        sh("git", "commit", "-qam", "two", cwd=r)  # a worker commits: the tree is clean, HEAD moved
        committed = eng.checkout.tree_hash()
        self.assertEqual(committed, self.git.rev_parse(str(r), "HEAD^{tree}"))
        sh("git", "checkout", "-q", "-b", "other", "HEAD~1", cwd=r)  # a worker checks out older content
        self.assertEqual(eng.checkout.tree_hash(), self.git.rev_parse(str(r), "HEAD^{tree}"))
        self.assertNotEqual(eng.checkout.tree_hash(), committed)
        sh("git", "checkout", "-q", "main", cwd=r)
        self.assertEqual(eng.checkout.tree_hash(), committed)


if __name__ == "__main__":
    unittest.main()
