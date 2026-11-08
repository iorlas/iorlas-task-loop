"""Explicit git fake: unused capabilities fail instead of reaching a process."""
from typing import Literal

from tlgate.testing import ScriptedGateGit, rows, scalar
from tlkernel.gitfacts import ConfigEntry, DiffEntry, GitOutcome, GrepHit, LogRow, Pick, Ref, StatusRow
from tlkernel.slots import Checkout


class FakeWorkGit(ScriptedGateGit):
    """Full Git port: work-only replies and missing-method refusals extend the gate recorder."""
    def __init__(self, **replies: object) -> None:
        super().__init__(**{"ls_tree": (), "grep": (), **replies})

    def fetch(self, d: str) -> None:
        raise AssertionError("unexpected git fetch")

    def rebasing(self, d: str) -> bool:
        raise AssertionError("unexpected git rebasing")

    def rebase_abort(self, d: str) -> None:
        raise AssertionError("unexpected git rebase_abort")

    def commit_all(self, d: str, branch: str, message: str) -> None:
        raise AssertionError("unexpected git commit_all")

    def has_branch(self, d: str, branch: str) -> bool:
        raise AssertionError("unexpected git has_branch")

    def checkout(self, d: str, branch: str) -> None:
        raise AssertionError("unexpected git checkout")

    def checkout_new(self, d: str, branch: str, start: str) -> None:
        raise AssertionError("unexpected git checkout_new")

    def checkout_detached(self, d: str, ref: str) -> None:
        raise AssertionError("unexpected git checkout_detached")

    def clean(self, d: str, keep: list[str], ignored: bool=False) -> None:
        raise AssertionError("unexpected git clean")

    def checkouts(self, d: str) -> list[Checkout]:
        raise AssertionError("unexpected git checkouts")

    def remove_worktree(self, repo: str, path: str) -> bool:
        raise AssertionError("unexpected git remove_worktree")

    def init_bare(self, d: str, branch: str) -> None:
        raise AssertionError("unexpected git init_bare")

    def clone(self, src: str, dst: str) -> None:
        raise AssertionError("unexpected git clone")

    def remove_worktree_why(self, repo: str, path: str) -> str:
        raise AssertionError("unexpected git remove_worktree_why")

    def for_each_ref(self, d: str, *prefixes: str) -> list[Ref]:
        raise AssertionError("unexpected git for_each_ref")

    def ls_remote(self, d: str, remote: str, *patterns: str) -> list[Ref]:
        raise AssertionError("unexpected git ls_remote")

    def cherry(self, d: str, upstream: str, head: str) -> list[Pick]:
        raise AssertionError("unexpected git cherry")

    def merged(self, d: str, into: str) -> list[Ref]:
        raise AssertionError("unexpected git merged")

    def is_ancestor(self, d: str, a: str, b: str) -> bool:
        raise AssertionError("unexpected git is_ancestor")

    def symbolic_ref(self, d: str, ref: str) -> str:
        raise AssertionError("unexpected git symbolic_ref")

    def bead_trailers(self, d: str, include: list[str], exclude: list[str] | None = None) -> dict[str, str]:
        return {}

    def log(self, d: str, include: list[str], exclude: list[str] | None=None, limit: int=0, grep: str='') -> list[LogRow]:
        raise AssertionError("unexpected git log")

    def status(self, d: str, all_untracked: bool=False) -> list[StatusRow]:
        raise AssertionError("unexpected git status")

    def check_ignore(self, d: str, paths: list[str], excludes: str='') -> list[str]:
        raise AssertionError("unexpected git check_ignore")

    def git_dir(self, d: str) -> str:
        raise AssertionError("unexpected git git_dir")

    def has_commit(self, d: str, oid: str) -> bool:
        raise AssertionError("unexpected git has_commit")

    def grep(self, d: str, pattern: str, fixed: bool=False, word: bool=False) -> list[GrepHit]:
        return rows(GrepHit, self.answer("grep", pattern))

    def config_get(self, d: str, key: str) -> str:
        raise AssertionError("unexpected git config_get")

    def config_entries(self, d: str, pattern: str) -> list[ConfigEntry]:
        raise AssertionError("unexpected git config_entries")

    def toplevel(self, d: str) -> str:
        raise AssertionError("unexpected git toplevel")

    def worktree_state(self, d: str) -> bytes | None:
        raise AssertionError("unexpected git worktree_state")

    def diff(self, d: str, a: str, b: str, exclude: list[str] | None=None, stat: bool=False) -> str:
        return scalar(str, self.answer("diff", a, b))

    def profile_diff(self, d: str, base: str, tip: str) -> str:
        raise AssertionError("unexpected git profile_diff")

    def unpinned(self) -> FakeWorkGit:
        raise AssertionError("unexpected git unpinned")

    def count(self, d: str, include: list[str], exclude: list[str] | None=None) -> int:
        raise AssertionError("unexpected git count")

    def unmerged(self, d: str) -> list[str]:
        raise AssertionError("unexpected git unmerged")

    def diff_entries(self, d: str, a: str, b: str, ignore_space: bool=False, *, required: bool=False) -> list[DiffEntry]:
        return rows(DiffEntry, self.answer("diff_entries", a, b))

    def staged(self, d: str) -> bool:
        raise AssertionError("unexpected git staged")

    def staged_paths(self, d: str) -> list[str]:
        raise AssertionError("unexpected git staged_paths")

    def export_index(self, d: str, dest: str) -> None:
        raise AssertionError("unexpected git export_index")

    def stage_literal(self, d: str, paths: list[str]) -> None:
        raise AssertionError("unexpected git stage_literal")

    def rename_branch(self, d: str, old: str, new: str) -> None:
        raise AssertionError("unexpected git rename_branch")

    def checkout_reset(self, d: str, branch: str, start: str) -> None:
        raise AssertionError("unexpected git checkout_reset")

    def try_commit(self, d: str, message: str, verify: bool=True, allow_empty: bool=False) -> GitOutcome:
        raise AssertionError("unexpected git try_commit")

    def amend(self, d: str) -> None:
        raise AssertionError("unexpected git amend")

    def rebase_continue(self, d: str) -> GitOutcome:
        raise AssertionError("unexpected git rebase_continue")

    def push_lease(self, d: str, remote: str, refspec: str, expect_sha: str) -> GitOutcome:
        raise AssertionError("unexpected git push_lease")

    def lfs_push(self, d: str, remote: str, refs: list[str]) -> GitOutcome:
        raise AssertionError("unexpected git lfs_push")

    def rebase(self, d: str, onto: str, update_refs: bool=True) -> GitOutcome:
        raise AssertionError("unexpected git rebase")

    def reset(self, d: str, rev: str, mode: Literal['soft', 'mixed', 'hard']='mixed') -> None:
        raise AssertionError("unexpected git reset")

    def tag(self, d: str, name: str, rev: str='HEAD') -> None:
        raise AssertionError("unexpected git tag")

    def checkout_force(self, d: str, branch: str, start: str) -> None:
        raise AssertionError("unexpected git checkout_force")

    def fetch_ref(self, d: str, source: str, ref: str) -> None:
        raise AssertionError("unexpected git fetch_ref")

    def remote_url(self, d: str, remote: str) -> str:
        raise AssertionError("unexpected git remote_url")

    def merge_ff(self, d: str, rev: str) -> None:
        raise AssertionError("unexpected git merge_ff")

    def commit_tracked(self, d: str, message: str) -> None:
        raise AssertionError("unexpected git commit_tracked")

    def stage(self, d: str, *paths: str) -> None:
        raise AssertionError("unexpected git stage")

    def commit_staged(self, d: str, message: str) -> None:
        raise AssertionError("unexpected git commit_staged")

    def pull_rebase(self, d: str, remote: str, branch: str) -> None:
        raise AssertionError("unexpected git pull_rebase")

    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        raise AssertionError("unexpected git delete_branch_at")

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        raise AssertionError("unexpected git delete_remote_at")
