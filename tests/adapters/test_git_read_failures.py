"""Decision reads distinguish an unavailable answer from an empty successful one."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env
from taskloop.contracts.slots import GitReadFailure


class GitReadFailures(unittest.TestCase):
    def setUp(self):
        self.git = RealGit(Env(), pinned=False)

    def test_failed_decision_reads_never_answer_clean_empty_or_missing(self):
        calls = [("status", ()), ("branch", ()),
                 ("rev_parse", ("HEAD",)), ("has_commit", ("abc",)),
                 ("merge_base", ("a", "b")), ("is_ancestor", ("a", "b")), ("git_dir", ()),
                 ("rebasing", ()), ("changed_paths", ("a", "b")), ("diff_entries", ("a", "b")),
                 ("diff", ("a", "b")), ("profile_diff", ("a", "b")), ("unmerged", ()), ("staged", ()),
                 ("for_each_ref", ()), ("merged", ("HEAD",)), ("symbolic_ref", ("refs/remotes/origin/HEAD",))]
        for name, args in calls:
            for code, diagnostic in ((128, "fatal: unreadable checkout"), (1, "Verrouillage impossible")):
                with (self.subTest(name=name, code=code),
                      mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], code, "", diagnostic)),
                      self.assertRaises(GitReadFailure)):
                    getattr(self.git, name)("/checkout", *args)

    def test_expected_absence_is_command_specific(self):
        absent = subprocess.CompletedProcess([], 1, "", "")
        with mock.patch.object(self.git, "_run", return_value=absent):
            self.assertEqual(self.git.branch("/checkout"), "")
            self.assertEqual(self.git.symbolic_ref("/checkout", "refs/remotes/origin/HEAD"), "")
            self.assertEqual(self.git.rev_parse("/checkout", "missing"), "")
            self.assertFalse(self.git.has_commit("/checkout", "missing"))
            self.assertEqual(self.git.merge_base("/checkout", "a", "b"), "")
            self.assertFalse(self.git.is_ancestor("/checkout", "a", "b"))
            self.assertTrue(self.git.staged("/checkout"))
            for name, args in (("status", ()), ("changed_paths", ("a", "b"))):
                with self.subTest(name=name), self.assertRaises(GitReadFailure):
                    getattr(self.git, name)("/checkout", *args)

    def test_profile_diff_preserves_the_exact_patch_and_only_reads_the_profile(self):
        patch = 'diff --git a/.task-loop.json b/.task-loop.json\n-old\n+new\n'
        with mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 0, patch, "")) as run:
            self.assertEqual(self.git.profile_diff("/checkout", "base", "tip"), patch)
        run.assert_called_once_with("/checkout", "diff", "--no-ext-diff", "--no-textconv", "base", "tip", "--", ".task-loop.json",
                                    extra=None)

    def test_read_process_failures_are_typed(self):
        for error in (OSError("unavailable"), subprocess.TimeoutExpired("git", 1)):
            with mock.patch.object(self.git, "_run", side_effect=error), self.assertRaises(GitReadFailure):
                self.git.status("/checkout")

    def test_failed_queries_are_not_memoized(self):
        self.git.pinned = True
        failure = subprocess.CompletedProcess([], 128, "", "unreadable")
        success = subprocess.CompletedProcess([], 0, "oid\n", "")
        with (mock.patch("taskloop.adapters.git_base.gitmemo.memo_key", return_value=("key", (), None)),
              mock.patch("taskloop.adapters.git_base.gitmemo.remember") as remember,
              mock.patch.object(self.git, "_run", side_effect=[failure, success]) as run):
            with self.assertRaises(GitReadFailure):
                self.git.rev_parse("/checkout", "HEAD")
            remember.assert_not_called()
            self.assertEqual(self.git.rev_parse("/checkout", "HEAD"), "oid")
        self.assertEqual(run.call_count, 2)
        remember.assert_called_once()

    def test_path_reads_preserve_newlines_and_spaces(self):
        name = " leading\nname\n"
        for method, args in (("changed_paths", ("a", "b")), ("unmerged", ())):
            with (self.subTest(method=method),
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 0, name + "\0", "")) as run):
                self.assertEqual(getattr(self.git, method)("/checkout", *args), [name])
                self.assertIn("-z", run.call_args.args)

    def test_truncated_or_unknown_diff_and_status_rows_are_faults(self):
        for method, args, out in (("diff_entries", ("a", "b"), "R100\0old\0"),
                                  ("diff_entries", ("a", "b"), "M\0"),
                                  ("diff_entries", ("a", "b"), "Mystery\0path\0"),
                                  ("changed_paths", ("a", "b"), "path\0\0"),
                                  ("status", (), "?? incomplete")):
            with (self.subTest(method=method),
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 0, out, "")),
                  self.assertRaises(GitReadFailure)):
                getattr(self.git, method)("/checkout", *args)
