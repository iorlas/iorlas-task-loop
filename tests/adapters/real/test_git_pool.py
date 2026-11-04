"""The migrated pool write uses real git with the engine's checkout and index pinning intact."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
import pytest
from git_porcelain import real_env
from git_porcelain.real import RealRepo
from support.case import Case

from taskloop.adapters import treehash
from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.slots import SlotGitError


class RealGitPoolTest(Case):
    def setup_method(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.run_git(self.repo, "init", "-q", "-b", "main")
        self.run_git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgSign=false", "commit", "-qm", "initial", "--allow-empty")
        self.git = RealGit(snapshot())

    def run_git(self, path, *args):
        return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()

    def test_add_worktree_is_detached_at_the_requested_revision(self):
        slot = self.home / "slot"
        self.git.add_worktree(str(self.repo), str(slot), "main")
        assert self.run_git(slot, "rev-parse", "HEAD") == self.run_git(self.repo, "rev-parse", "main")
        assert self.run_git(slot, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"

    def test_add_worktree_preserves_failures_without_creating_a_checkout(self):
        slot = self.home / "slot"
        with pytest.raises(SlotGitError):
            self.git.add_worktree(str(self.repo), str(slot), "missing-revision")
        assert not slot.exists()

    def test_add_from_a_linked_checkout_keeps_the_environment_pinned(self):
        first = self.home / "first"
        self.git.add_worktree(str(self.repo), str(first), "main")
        gitdir = Path(self.run_git(first, "rev-parse", "--absolute-git-dir"))
        decoy = self.home / "decoy"
        decoy.mkdir()
        self.run_git(self.repo, "config", "core.worktree", str(decoy))
        polluted = {**snapshot().vars, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(decoy), "GIT_INDEX_FILE": str(decoy / "index")}
        port = RealGit(Env(polluted))
        slot = self.home / "slot"
        index_before = (gitdir / "index").read_bytes()
        env_before = port.git_env(first)
        with (mock.patch("git_porcelain.real.real_env.pinned", wraps=real_env.pinned) as pin,
              mock.patch("git_porcelain.real.subprocess.run", wraps=subprocess.run) as run):
            port.add_worktree(str(first), str(slot), "main")
        pin.assert_called_once_with(first)
        child = run.call_args.kwargs["env"]
        assert child["GIT_DIR"] == str(gitdir)
        assert child["GIT_WORK_TREE"] == str(first)
        assert "GIT_INDEX_FILE" not in child
        assert (slot / ".git").is_file()
        assert not (decoy / "index").exists()
        assert (gitdir / "index").read_bytes() == index_before
        assert port.git_env(first) == env_before
        assert port.env.vars == polluted

    def test_pool_operations_keep_linked_checkout_and_index_pinned(self):
        first, slot, decoy = (self.home / name for name in ("first", "slot", "decoy"))
        self.git.add_worktree(str(self.repo), str(first), "main")
        gitdir = Path(self.run_git(first, "rev-parse", "--absolute-git-dir"))
        decoy.mkdir()
        self.run_git(self.repo, "config", "core.worktree", str(decoy))
        polluted = {**snapshot().vars, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(decoy), "GIT_INDEX_FILE": str(decoy / "index")}
        port = RealGit(Env(polluted))
        index_before = (gitdir / "index").read_bytes()
        with mock.patch("git_porcelain.real.subprocess.run", wraps=subprocess.run) as run:
            port.add_worktree_force(str(first), str(slot), "main")
            assert str(slot) in [co.path for co in port.checkouts(str(first))]
            assert not port.dirty(str(first))
            assert isinstance(port.worktree_state(str(first)), bytes)
            assert port.remove_worktree(str(first), str(slot))
            assert not port.remove_worktree(str(first), str(slot))
            port.add_worktree_force(str(first), str(slot), "main")
            assert port.remove_worktree_why(str(first), str(slot)) == ""
            port.add_worktree_force(str(first), str(slot), "main")
            port.remove_worktree_force(str(first), str(slot))
            port.prune_worktrees(str(first))
        for call in run.call_args_list:
            child = call.kwargs["env"]
            assert child["GIT_DIR"] == str(gitdir)
            assert child["GIT_WORK_TREE"] == str(first)
            assert "GIT_INDEX_FILE" not in child
        assert (gitdir / "index").read_bytes() == index_before
        assert not (decoy / "index").exists()
        assert port.env.vars == polluted

    def test_tree_of_matches_snapshot_with_a_tracked_ignored_declared_input(self):
        (self.repo / ".gitignore").write_text("declared.txt\n")
        declared = self.repo / "declared.txt"
        declared.write_text("initial\n")
        self.run_git(self.repo, "add", ".gitignore")
        self.run_git(self.repo, "add", "--force", "declared.txt")
        self.run_git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgSign=false", "commit", "-qm", "tracked ignored input")
        declared.write_text("changed ignored input\n")
        (self.repo / "untracked.txt").write_text("untracked\n")
        assert self.run_git(self.repo, "check-ignore", "--no-index", "declared.txt") == "declared.txt"
        index_before = (self.repo / ".git" / "index").read_bytes()
        worktree = RealRepo(self.repo, env=self.git.git_env(self.repo), memoize=False).worktree(self.repo)
        assert treehash.tree_of(self.git, self.repo) == worktree.snapshot("main", inputs=("declared.txt",)).tree
        assert (self.repo / ".git" / "index").read_bytes() == index_before

    def test_preservation_keeps_the_linked_checkout_and_index_pinned(self):
        slot, decoy = (self.home / name for name in ("slot", "decoy"))
        self.git.add_worktree(str(self.repo), str(slot), "main")
        gitdir = Path(self.run_git(slot, "rev-parse", "--absolute-git-dir"))
        decoy.mkdir()
        (decoy / "untouched").write_text("decoy\n")
        self.run_git(self.repo, "config", "core.worktree", str(decoy))
        polluted = {**snapshot().vars, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(decoy), "GIT_INDEX_FILE": str(decoy / "index"),
                    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
        port = RealGit(Env(polluted))
        (slot / "new.txt").write_text("checkpoint\n")
        main_index = (self.repo / ".git" / "index").read_bytes()
        with mock.patch("git_porcelain.real.subprocess.run", wraps=subprocess.run) as run:
            port.commit_all(str(slot), "wip/slot", "checkpoint")
            assert port.has_branch(str(slot), "wip/slot")
            port.checkout_detached(str(slot), "main")
            port.checkout_reset(str(slot), "task/slot", "wip/slot")
        for call in run.call_args_list:
            child = call.kwargs["env"]
            assert child["GIT_DIR"] == str(gitdir)
            assert child["GIT_WORK_TREE"] == str(slot)
            assert "GIT_INDEX_FILE" not in child
        assert (slot / "new.txt").read_text() == "checkpoint\n"
        assert (self.repo / ".git" / "index").read_bytes() == main_index
        assert list(decoy.iterdir()) == [decoy / "untouched"]
        assert port.env.vars == polluted

    def test_tree_of_keeps_untracked_ignored_inputs_out_of_the_whole_tree_key(self):
        (self.repo / ".gitignore").write_text("declared.txt\n")
        declared = self.repo / "declared.txt"
        declared.write_text("ignored input\n")
        before = treehash.tree_of(self.git, self.repo)
        state = treehash.state_of(self.git, self.repo)
        declared.write_text("changed ignored input\n")
        assert treehash.tree_of(self.git, self.repo) == before
        assert treehash.state_of(self.git, self.repo) == state
        worktree = RealRepo(self.repo, env=self.git.git_env(self.repo)).worktree(self.repo)
        assert before != worktree.snapshot("HEAD", inputs=("declared.txt",)).tree

    def test_snapshot_hash_keeps_linked_checkout_and_temporary_index_pinned(self):
        slot, decoy = (self.home / name for name in ("slot", "decoy"))
        self.git.add_worktree(str(self.repo), str(slot), "main")
        gitdir = Path(self.run_git(slot, "rev-parse", "--absolute-git-dir"))
        decoy.mkdir()
        self.run_git(self.repo, "config", "core.worktree", str(decoy))
        polluted = {**snapshot().vars, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(decoy), "GIT_INDEX_FILE": str(decoy / "index")}
        port = RealGit(Env(polluted))
        (slot / "new.txt").write_text("new\n")
        index_before = (gitdir / "index").read_bytes()
        with mock.patch("git_porcelain.real.subprocess.run", wraps=subprocess.run) as run:
            tree = treehash.tree_of(port, slot)
        assert tree
        temporary_indexes = set()
        for call in run.call_args_list:
            child = call.kwargs["env"]
            assert child["GIT_DIR"] == str(gitdir)
            assert child["GIT_WORK_TREE"] == str(slot)
            if any(cmd in call.args[0] for cmd in ("read-tree", "add", "write-tree")):
                temporary_indexes.add(child["GIT_INDEX_FILE"])
            else:
                assert "GIT_INDEX_FILE" not in child
        assert len(temporary_indexes) == 1
        assert str(gitdir / "index") not in temporary_indexes
        assert all(not Path(index).exists() for index in temporary_indexes)
        assert (gitdir / "index").read_bytes() == index_before
        assert not (decoy / "index").exists()
        assert port.env.vars == polluted
