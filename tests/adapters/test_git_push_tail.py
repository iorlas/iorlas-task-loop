"""Failed pushes preserve rejection details while other git errors keep their existing diagnostics."""
import subprocess
import unittest
from unittest import mock

import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.adapters.git_base import classify, error_line, push_error_line
from taskloop.contracts.env import Env
from taskloop.contracts.slots import BranchPinned, DirtyTree, IndexLocked, RefRace, SlotGitError

TRAILER = "error: failed to push some refs to 'origin'"


class PushTail(unittest.TestCase):
    def test_fetch_first_rejection_and_hints_replace_the_trailer(self):
        rejection = "! [rejected] main -> main (fetch first)"
        hint = "hint: Updates were rejected because the remote contains work"
        stderr = f"To origin\n {rejection}\n{TRAILER}\n{hint}\n"
        self.assertEqual(push_error_line(stderr), rejection + " | " + hint)
        self.assertEqual(error_line(stderr), TRAILER)
        self.assertEqual(classify(stderr).tail, TRAILER)

    def test_remote_hook_output_and_rejection_are_preserved_in_order(self):
        lines = ["remote: GH013: Repository rule violations found",
                 "remote: pre-push check: required approval missing",
                 "! [remote rejected] main -> main (pre-receive hook declined)"]
        self.assertEqual(push_error_line("\n".join([*lines, TRAILER])), " | ".join(lines))

    def test_network_errors_and_unhelpful_output_keep_the_existing_fallback(self):
        network = "ssh: connect to host example.invalid port 22: Connection timed out"
        for stderr, expected in ((network + "\n" + TRAILER, TRAILER), (network, network),
                                 ("progress\n" + TRAILER, TRAILER), ("progress\nunknown failure", "unknown failure"),
                                 ("", "no message from git"), ("fatal: network unavailable\n" + TRAILER,
                                                              "fatal: network unavailable")):
            with self.subTest(stderr=stderr):
                self.assertEqual(push_error_line(stderr), expected)

    def test_push_tail_is_bounded(self):
        self.assertEqual(push_error_line("remote: " + "x" * 500 + "\n" + TRAILER), "remote: " + "x" * 392)

    def test_classification_reads_the_full_stderr_even_beyond_the_tail_limit(self):
        prefix = "remote: " + "x" * 500 + "\n"
        cases = (("error: cannot lock ref 'refs/heads/main'", RefRace),
                 ("fatal: Unable to create '/repo/index.lock'", IndexLocked),
                 ("error: local changes would be overwritten", DirtyTree),
                 ("fatal: 'main' is already used by worktree at '/other'", BranchPinned))
        for diagnostic, kind in cases:
            with self.subTest(kind=kind):
                error = classify(prefix + diagnostic + "\n" + TRAILER, push=True)
                self.assertIsInstance(error, kind)
                self.assertEqual(error.tail, prefix.strip()[:400])
                if isinstance(error, BranchPinned):
                    self.assertEqual(error.where, "/other")

    def test_branch_tag_and_delete_push_errors_use_the_push_tail(self):
        git = RealGit(Env(), pinned=False)
        rejection = "! [remote rejected] main -> main (pre-receive hook declined)"
        failed = subprocess.CompletedProcess([], 1, "", rejection + "\n" + TRAILER)
        for refspec in ("HEAD:main", "refs/tags/v1.2.3", ":refs/heads/topic"):
            with (self.subTest(refspec=refspec), mock.patch.object(git, "_run", return_value=failed),
                  self.assertRaises(SlotGitError) as raised):
                git.push("repo", "origin", refspec)
            self.assertEqual(raised.exception.tail, rejection)

    def test_lease_push_keeps_complete_output_for_callers(self):
        git = RealGit(Env(), pinned=False)
        stderr = "! [rejected] HEAD -> topic (stale info)\n" + TRAILER
        with mock.patch.object(git, "_run", return_value=subprocess.CompletedProcess([], 1, "", stderr)):
            result = git.push_lease("repo", "origin", "HEAD:topic")
        self.assertFalse(result.ok)
        self.assertEqual(result.output, stderr)
