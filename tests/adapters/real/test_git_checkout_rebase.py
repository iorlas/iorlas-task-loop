"""Rebase integration retains conflicts, ownership checks and cherry ordering."""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from taskloop.adapters.git import RealGit
from tlkernel.env import Env, snapshot
from tlkernel.slots import BranchPinned
from tltestkit.case import Case
from tltestkit.checked import run_checked
from tltestkit.tmpdir import TemporaryDirectory


class RealGitCheckoutRebaseTest(Case):
    def setup_method(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.env = {**snapshot().vars, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
        self.git = RealGit(Env(self.env))
        self.run_git("init", "-q", "-b", "main")
        self.run_git("config", "commit.gpgSign", "false")
        self.run_git("config", "core.hooksPath", str(self.home / "hooks"))
        self.base = self.commit_file("file", "base\n", "initial")

    def run_git(self, *args):
        return run_checked(["git", "-C", str(self.repo), *args], None, env=self.env, text=True).stdout.strip()

    def commit_file(self, name, text, message):
        (self.repo / name).write_text(text)
        self.run_git("add", "--", name)
        self.run_git("commit", "-qm", message)
        return self.run_git("rev-parse", "HEAD")

    def conflict(self):
        self.git.checkout_new(str(self.repo), "topic", "main")
        self.original = self.commit_file("file", "topic\n", "topic change")
        self.git.checkout(str(self.repo), "main")
        self.commit_file("file", "main\n", "main change")
        self.git.checkout(str(self.repo), "topic")
        return self.git.rebase(str(self.repo), "main")

    def test_conflict_returns_diagnostics_and_fresh_paused_state(self):
        result = self.conflict()
        assert not result.ok
        assert "CONFLICT" in result.output
        assert "file" in result.output
        assert "could not apply" in result.output
        assert self.git.rebasing(str(self.repo))
        assert self.git.unmerged(str(self.repo)) == ["file"]
        again = self.git.rebase_continue(str(self.repo))
        assert not again.ok
        assert again.output
        assert self.git.unmerged(str(self.repo)) == ["file"]
        self.git.rebase_abort(str(self.repo))
        assert not self.git.rebasing(str(self.repo))
        assert self.git.unmerged(str(self.repo)) == []
        assert self.run_git("rev-parse", "HEAD") == self.original

    def test_continue_needs_the_callers_staging_then_finishes(self):
        self.conflict()
        (self.repo / "file").write_text("resolved\n")
        refusal = self.git.rebase_continue(str(self.repo))
        assert not refusal.ok
        assert self.git.unmerged(str(self.repo)) == ["file"]
        self.git.stage_literal(str(self.repo), ["file"])
        result = self.git.rebase_continue(str(self.repo))
        assert result.ok, result.output
        assert not self.git.rebasing(str(self.repo))
        assert (self.repo / "file").read_text() == "resolved\n"

    def test_delete_refuses_a_branch_checked_out_here_or_in_another_worktree(self):
        directory = str(self.repo)
        with pytest.raises(BranchPinned) as caught:
            self.git.delete_branch_at(directory, "main", self.base)
        assert caught.value.where == directory
        self.run_git("branch", "topic")
        slot = self.home / "slot"
        self.run_git("worktree", "add", "-q", str(slot), "topic")
        with pytest.raises(BranchPinned) as caught:
            self.git.delete_branch_at(directory, "topic", self.base)
        assert caught.value.where == str(slot)
        assert self.run_git("rev-parse", "topic") == self.base

    def test_cherry_keeps_oldest_first_patch_equivalence_order(self):
        self.git.checkout_new(str(self.repo), "topic", "main")
        first = self.commit_file("one", "one\n", "first")
        second = self.commit_file("two", "two\n", "second")
        self.git.checkout(str(self.repo), "main")
        self.run_git("cherry-pick", "--no-commit", first)
        self.run_git("commit", "-qm", "equivalent first patch")
        self.commit_file("upstream", "upstream\n", "upstream")
        rows = self.git.cherry(str(self.repo), "main", "topic")
        assert [(row.oid, row.upstream) for row in rows] == [(first, True), (second, False)]

    def test_update_refs_default_inherits_config_and_false_overrides_it(self):
        for configured, requested, moves in ((False, True, False), (True, True, True), (True, False, False)):
            with self.subTest(configured=configured, requested=requested):
                self.git.checkout_force(str(self.repo), "main", self.base)
                self.run_git("config", "rebase.updateRefs", str(configured).lower())
                self.git.checkout_force(str(self.repo), "topic", self.base)
                old = self.commit_file("topic", "topic\n", "topic")
                self.run_git("branch", "-f", "alias", old)
                self.git.checkout(str(self.repo), "main")
                self.commit_file("upstream", "upstream\n", "upstream")
                self.git.checkout(str(self.repo), "topic")
                result = self.git.rebase(str(self.repo), "main", update_refs=requested)
                assert result.ok, result.output
                alias = self.run_git("rev-parse", "alias")
                assert alias == (self.run_git("rev-parse", "HEAD") if moves else old)
                self.git.reset(str(self.repo), self.base, "hard")

    def test_checkout_reset_and_clean_keep_the_linked_checkout_pinned(self):
        slot, decoy = self.home / "slot", self.home / "decoy"
        self.git.add_worktree(str(self.repo), str(slot), "main")
        decoy.mkdir()
        self.run_git("config", "core.worktree", str(decoy))
        port = RealGit(Env({**self.env, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(decoy),
                            "GIT_INDEX_FILE": str(decoy / "index")}))
        (slot / "keep").write_text("keep\n")
        (slot / "discard").write_text("discard\n")
        with mock.patch("git_porcelain.real.subprocess.run", wraps=subprocess.run) as run:
            port.checkout_new(str(slot), "topic", "main")
            port.reset(str(slot), "main", "hard")
            port.clean(str(slot), ["keep"], ignored=True)
        for call in run.call_args_list:
            assert call.kwargs["env"]["GIT_WORK_TREE"] == str(slot)
            assert "GIT_INDEX_FILE" not in call.kwargs["env"]
        assert (slot / "keep").exists()
        assert not (slot / "discard").exists()
        assert list(decoy.iterdir()) == []
