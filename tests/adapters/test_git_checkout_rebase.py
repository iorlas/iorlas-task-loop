"""Checkout and rebase preserve port outcomes at the porcelain boundary."""

import subprocess
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
from git_porcelain import errors
from git_porcelain.api import CommandResult, LogEntry, Pick, Sha
from git_porcelain.real import Done
from git_porcelain.testing import FakeRepo

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import GitOutcome
from taskloop.contracts.slots import BranchPinned, DirtyTree, GitReadFailure, IndexLocked, NotAWorktree, RefRace, SlotGitError


class GitCheckoutRebaseTest(unittest.TestCase):
    def setUp(self):
        self.git = RealGit(Env())

    def test_checkout_writes_keep_typed_failures_and_holder(self):
        operations = (("checkout", ("topic",)), ("checkout_new", ("topic", "main")),
                      ("checkout_force", ("topic", "main")), ("reset", ("main",)))
        failures = ((errors.IndexLocked("locked"), IndexLocked),
                    (errors.RefRace("raced"), RefRace),
                    (errors.BranchPinned("held", "/holder"), BranchPinned),
                    (errors.DirtyTree("dirty"), DirtyTree),
                    (errors.GitUnavailable("local changes would be overwritten"), DirtyTree))
        for name, args in operations:
            for error, kind in failures:
                with (self.subTest(operation=name, error=kind.__name__),
                      mock.patch.object(self.git, "_pool") as pool):
                    getattr(pool.return_value.worktree.return_value, name).side_effect = error
                    with self.assertRaises(kind) as caught:
                        getattr(self.git, name)("/pool", *args)
                    self.assertIs(caught.exception.__cause__, error)
                    if isinstance(caught.exception, BranchPinned):
                        self.assertEqual(caught.exception.where, "/holder")

    def test_exclusive_create_and_detached_branch_use_the_fake(self):
        repo = FakeRepo.init(Path("/pool"))
        wt = repo.worktree(repo.path)
        wt.write_file("tracked", "initial\n")
        wt.record("initial", paths="all")
        with mock.patch.object(self.git, "_pool", return_value=repo):
            self.git.checkout_new("/pool", "topic", "main")
            self.assertEqual(wt.branch(), "topic")
            with self.assertRaises(SlotGitError):
                self.git.checkout_new("/pool", "topic", "main")
            self.git.checkout_detached("/pool", "main")
            self.assertIsNone(wt.branch())
            self.git.checkout("/pool", "topic")
            self.git.rename_branch("/pool", "topic", "renamed")
            self.assertEqual(wt.branch(), "renamed")

    def test_write_diagnostic_drops_exit_envelope_and_read_keeps_it(self):
        text = "git reset exited 128: fatal: cannot lock ref 'HEAD': index.lock exists"
        with mock.patch.object(self.git, "_pool") as pool:
            pool.return_value.worktree.return_value.reset.side_effect = errors.IndexLocked(text)
            with self.assertRaises(IndexLocked) as caught:
                self.git.reset("/pool", "main")
            self.assertEqual(str(caught.exception), "fatal: cannot lock ref 'HEAD': index.lock exists")
            pool.return_value.worktree.return_value.unmerged.side_effect = errors.GitUnavailable(text)
            with self.assertRaises(GitReadFailure) as caught:
                self.git.unmerged("/pool")
            self.assertEqual(str(caught.exception), text)

    def test_bare_worktree_read_retains_its_error_subtype(self):
        error = errors.GitUnavailable("git diff exited 128: fatal: this operation must be run in a work tree")
        with (mock.patch.object(self.git, "_pool", side_effect=error), self.assertRaises(NotAWorktree)):
            self.git.unmerged("/pool")

    def test_unpinned_rebase_and_checkout_keep_pinning_disabled(self):
        port = self.git.unpinned()
        with mock.patch("taskloop.adapters.git_pool.RealRepo.run", return_value=Done(0, b"tip\n", "")) as run:
            port.rebase_continue("/pool")
            port.checkout("/pool", "main")
            self.assertTrue(all(call.kwargs["pin"] is False for call in run.call_args_list))

    def test_rebase_inherits_config_by_default_and_false_disables_updates(self):
        text = "CONFLICT in file\nerror: could not apply"
        for update_refs, opts in ((True, ()), (False, ("-c", "rebase.updateRefs=false"))):
            with (self.subTest(update_refs=update_refs), mock.patch.object(self.git, "_pool") as pool,
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 1, text, "")) as run):
                outcome = self.git.rebase("/pool", "main", update_refs=update_refs)
                self.assertEqual(outcome, GitOutcome(ok=False, output=text))
                run.assert_called_once_with("/pool", *opts, "rebase", "-q", "main", stdin=None, timeout=None, extra=None)
                pool.assert_not_called()

    def test_rebase_invokes_git_even_for_dirty_paused_or_up_to_date_trees(self):
        for ok, text in ((False, "error: cannot rebase: You have unstaged changes."),
                         (False, "fatal: rebase-merge already exists"), (True, "Current branch is up to date.")):
            with (self.subTest(text=text), mock.patch.object(self.git, "_pool") as pool,
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], int(not ok), text, ""))):
                self.assertEqual(self.git.rebase("/pool", "main"), GitOutcome(ok=ok, output=text))
                pool.assert_not_called()

    def test_continue_keeps_the_existing_index_and_missing_rebase_refusal(self):
        with mock.patch.object(self.git, "_pool") as pool:
            cont = pool.return_value.worktree.return_value.continue_rebase
            cont.return_value = CommandResult(False, "fatal: No rebase in progress?")
            self.assertEqual(self.git.rebase_continue("/pool"), GitOutcome(ok=False, output=cont.return_value.output))
            cont.assert_called_once_with()

    def test_abort_discards_exit_status_but_does_not_hide_invocation_failure(self):
        with mock.patch.object(self.git, "_pool") as pool:
            abort = pool.return_value.worktree.return_value.abort_rebase
            abort.return_value = CommandResult(False, "fatal: No rebase in progress?")
            self.assertIsNone(self.git.rebase_abort("/pool"))
            abort.assert_called_once_with(missing_ok=False)
            abort.side_effect = errors.GitUnavailable("failed to invoke git")
            with self.assertRaises(SlotGitError):
                self.git.rebase_abort("/pool")

    def test_rebase_invocation_failures_stay_in_the_port_error_family(self):
        for name, args in (("rebase_continue", ()), ("rebase_abort", ())):
            error = errors.IndexLocked("locked")
            with (self.subTest(operation=name), mock.patch.object(self.git, "_pool", side_effect=error),
                  self.assertRaises(IndexLocked) as caught):
                getattr(self.git, name)("/pool", *args)
            self.assertIs(caught.exception.__cause__, error)

    def test_clean_passes_exclusions_and_ignores_only_command_refusals(self):
        with mock.patch.object(self.git, "_pool") as pool:
            clean = pool.return_value.worktree.return_value.clean
            self.git.clean("/pool", ["keep", "cache/"], ignored=True)
            clean.assert_called_once_with(["keep", "cache/"], ignored=True)
            clean.side_effect = errors.GitUnavailable("git clean exited 1: warning: cannot remove file")
            self.assertIsNone(self.git.clean("/pool", []))
            clean.side_effect = errors.GitUnavailable("failed to invoke git")
            with self.assertRaises(SlotGitError):
                self.git.clean("/pool", [])

    def test_decision_failures_never_become_absence_false_or_empty_rows(self):
        operations = (("rebasing", ()), ("unmerged", ()), ("merged", ("main",)))
        for name, args in operations:
            with (self.subTest(operation=name),
                  mock.patch.object(self.git, "_pool", side_effect=errors.GitUnavailable("unreadable")),
                  self.assertRaises(GitReadFailure)):
                getattr(self.git, name)("/pool", *args)

    def test_merged_validates_into_even_with_no_branches(self):
        with mock.patch.object(self.git, "_pool") as pool:
            pool.return_value.branches.return_value = ()
            pool.return_value.relate.side_effect = errors.MissingRevision("missing")
            with self.assertRaises(GitReadFailure):
                self.git.merged("/pool", "missing")

    def test_count_and_cherry_keep_order_and_write_error_mapping(self):
        with mock.patch.object(self.git, "_pool") as pool:
            repo = pool.return_value
            repo.history.return_value = (object(), object())
            self.assertEqual(self.git.count("/pool", ["a", "b"], ["c"]), 2)
            repo.history.assert_called_once_with(["a", "b"], not_on=["c"])
            repo.cherry.return_value = (Pick(Sha("older"), True), Pick(Sha("newer"), False))
            self.assertEqual([(p.oid, p.upstream) for p in self.git.cherry("/pool", "a", "b")],
                             [("older", True), ("newer", False)])
            repo.history.side_effect = repo.cherry.side_effect = errors.IndexLocked("locked")
            with self.assertRaises(IndexLocked):
                self.git.count("/pool", ["a"])
            with self.assertRaises(IndexLocked):
                self.git.cherry("/pool", "a", "b")

    def test_count_without_positive_revisions_does_not_default_to_head(self):
        with (mock.patch.object(self.git, "_pool") as pool,
              mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 129, "", "usage: git rev-list"))):
            with self.assertRaisesRegex(SlotGitError, "usage: git rev-list"):
                self.git.count("/pool", [])
            pool.assert_not_called()

    def test_log_filters_subjects_before_applying_its_limit(self):
        with mock.patch.object(self.git, "_pool") as pool:
            history = pool.return_value.history
            history.return_value = (LogEntry(Sha("new"), 3, "other subject", "needle only in body", None),
                                    LogEntry(Sha("middle"), 2, "needle here", "", None),
                                    LogEntry(Sha("old"), 1, "needle again", "", None))
            rows = self.git.log("/pool", ["topic"], ["main"], limit=1, grep="needle")
            self.assertEqual([(row.oid, row.time, row.subject) for row in rows], [("middle", 2, "needle here")])
            history.assert_called_once_with(["topic"], not_on=["main"], limit=None)

    def test_branch_deletion_preserves_holder_and_expected_tip(self):
        with mock.patch.object(self.git, "_pool") as pool:
            delete = pool.return_value.delete_branch
            self.git.delete_branch_at("/pool", "topic", "tip")
            delete.assert_called_once_with("topic", expected=Sha("tip"))
            delete.side_effect = errors.BranchPinned("checked out", "/holder")
            with self.assertRaises(BranchPinned) as caught:
                self.git.delete_branch_at("/pool", "topic", "tip")
            self.assertEqual(caught.exception.where, "/holder")

    def test_try_commit_retains_complete_hook_rejection_and_empty_diagnostics(self):
        text = "hook rejection details\n" * 100 + "error: rejected\n"
        for diagnostic in (text, "On branch main\nnothing to commit, working tree clean\n"):
            with (self.subTest(diagnostic=diagnostic[-40:]),
                  mock.patch.object(self.git, "_run", return_value=subprocess.CompletedProcess([], 1, "", diagnostic))):
                self.assertEqual(self.git.try_commit("/pool", "message"), GitOutcome(ok=False, output=diagnostic.strip()))

