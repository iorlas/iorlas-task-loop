"""FakeGit's writes, one function per protocol operation. Each takes the repository state and the checkout."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from git_porcelain import fake_flow as flow
from git_porcelain.api import (
    Aborted,
    BranchHeld,
    BranchTaken,
    HookRejected,
    NothingToRecord,
    Rebased,
    Recorded,
    Released,
    Sha,
    StillHeld,
    UpToDate,
    WorktreeInfo,
)
from git_porcelain.errors import some
from git_porcelain.fake_ops import branch_ref, clean, hard_to, is_clean, make_commit, require_index, stage, switch_tree, tracked_dirty
from git_porcelain.fake_read import dirty, relate, resolve_commit
from git_porcelain.fake_store import ancestors

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from typing import Literal

    from git_porcelain.api import FinishResult, RebaseResult, RecordResult, TakeResult
    from git_porcelain.fake_store import CheckoutState, RepoState

__all__ = ["finish_rebase", "park", "rebase_onto", "record", "release_branch", "take_branch"]


def _head(repo: RepoState, wt: CheckoutState) -> str:
    sha = repo.head_sha(wt)
    if sha is None:
        msg = "HEAD is unborn"
        raise ValueError(msg)
    return sha


def record(
    repo: RepoState,
    wt: CheckoutState,
    message: str,
    *,
    paths: Literal["own", "all"],
    base: str | None,
    mode: Literal["new", "amend", "squash_to"],
    squash_to: Sha | None,
    hooks: bool,
    allow_empty: bool,
) -> RecordResult:
    if mode == "squash_to" and squash_to is None:
        msg = "mode='squash_to' needs squash_to"
        raise ValueError(msg)
    old = repo.head_sha(wt)
    if mode == "amend" and old is None:
        msg = "nothing to amend: HEAD is unborn"
        raise ValueError(msg)
    require_index(wt)
    if paths == "all":
        stage(repo, wt, None)
    else:
        state = dirty(repo, wt, base=base, ignored_under=())
        picks = [*state.tracked, *(p for p in state.untracked if p not in state.base_ignored)]
        if picks:
            stage(repo, wt, picks)
    target = squash_to if mode == "squash_to" else old
    if dict(wt.index) == (dict(repo.store.commits[target].files) if target else {}) and not allow_empty:
        return NothingToRecord()
    if hooks and repo.hooks.refuse_commit:
        return HookRejected("pre-commit hook declined the commit")
    if mode == "squash_to":
        repo.move_head(wt, str(squash_to))
    if mode == "amend":
        previous = repo.store.commits[str(old)]
        sha = make_commit(repo, wt, message or previous.message, previous.parents)
    else:
        parent = repo.head_sha(wt)
        sha = make_commit(repo, wt, message, (parent,) if parent else ())
    return Recorded(Sha(sha))


def _land(repo: RepoState, wt: CheckoutState, sha: str, ref: str | None) -> None:
    """Make HEAD point at ``ref`` (or detach at ``sha``) and the files match that commit."""
    old = dict(repo.head_files(wt))
    switch_tree(repo, wt, repo.store.commits[sha].files, old)
    wt.head_ref, wt.detached = ref, None if ref else sha


def _checkout_branch(repo: RepoState, wt: CheckoutState, ref: str, sha: str) -> None:
    """``checkout -B``: the branch moves to ``sha`` and HEAD is on it, files switched from where HEAD was."""
    old = dict(repo.head_files(wt))
    switch_tree(repo, wt, repo.store.commits[sha].files, old)
    repo.refs[ref] = sha
    wt.head_ref, wt.detached = ref, None


def _holders(repo: RepoState, wt: CheckoutState, ref: str) -> tuple[WorktreeInfo, ...]:
    return tuple(
        WorktreeInfo(w.path, Sha(h) if (h := repo.head_sha(w)) else None, ref.removeprefix("refs/heads/"), w.main, None)
        for w in repo.worktrees.values()
        if w is not wt and w.head_ref == ref
    )


def take_branch(
    repo: RepoState,
    wt: CheckoutState,
    *,
    branch: str,
    base: str,
    mode: Literal["resume", "fresh", "restart"],
    keep_aside_as: str | None,
    clean_keep: Sequence[str] | None,
) -> TakeResult:
    ref = branch_ref(branch)
    held = _holders(repo, wt, ref)
    if held:
        return BranchHeld(held)
    require_index(wt)
    exists = ref in repo.refs
    kept: str | None = None
    if mode == "resume" and exists:
        _land(repo, wt, repo.refs[ref], ref)
    else:
        target = resolve_commit(repo, wt, base)
        if mode == "fresh" and exists and keep_aside_as is not None:
            ahead = ancestors(repo.store, repo.refs[ref]) - ancestors(repo.store, target)
            if ahead:
                aside = branch_ref(keep_aside_as)
                if aside in repo.refs:
                    msg = f"keep_aside_as {keep_aside_as!r} already exists"
                    raise ValueError(msg)
                repo.refs[aside] = repo.refs.pop(ref)
                for other in repo.worktrees.values():
                    if other.head_ref == ref:
                        other.head_ref = aside
                kept = keep_aside_as
        _checkout_branch(repo, wt, ref, target)
    if clean_keep is not None:
        clean(repo, wt, clean_keep)
    return BranchTaken(branch, Sha(_head(repo, wt)), created=not exists or kept is not None, kept_aside=kept)


def release_branch(repo: RepoState, wt: CheckoutState, holder: Path) -> Released | StillHeld:
    other = repo.worktrees.get(holder)
    if other is None or other is wt:
        msg = f"{holder} is not another worktree of this repository"
        raise ValueError(msg)
    if other.main:
        return StillHeld(holder, "the main checkout holds it")
    if other.missing or is_clean(repo, other):
        flow.worktree_remove(repo, holder, force=False)
        return Released(holder, "removed")
    sha = repo.head_sha(other)
    if sha is None:
        return StillHeld(holder, "HEAD is unborn")
    _land(repo, other, sha, None)
    return Released(holder, "detached")


def park(repo: RepoState, wt: CheckoutState, base: str, clean_keep: Sequence[str] | None) -> Sha:
    require_index(wt)
    sha = resolve_commit(repo, wt, base)
    _land(repo, wt, sha, None)
    if clean_keep is not None:
        clean(repo, wt, clean_keep)
    return Sha(sha)


def rebase_onto(repo: RepoState, wt: CheckoutState, base: str, squash_message: str | None) -> RebaseResult:
    if wt.rebase is not None:
        msg = "a rebase is already paused here: finish_rebase first"
        raise ValueError(msg)
    if tracked_dirty(wt, repo.head_files(wt)):
        msg = "dirty: the tree has tracked changes"
        raise ValueError(msg)
    require_index(wt)
    head, target = _head(repo, wt), resolve_commit(repo, wt, base)
    if not ancestors(repo.store, target) - ancestors(repo.store, head):
        return UpToDate()
    squashed = False
    if squash_message is not None:
        fork = relate(repo, wt, "HEAD", base).merge_base
        if fork is not None and len(ancestors(repo.store, head) - ancestors(repo.store, fork)) > 1:
            repo.move_head(wt, fork)
            make_commit(repo, wt, squash_message, (fork,))
            squashed = True
    started = repo.head_sha(wt)
    started = some(started)
    done = flow.start_rebase(repo, wt, started, target)
    if isinstance(done, Rebased):
        return Rebased(Sha(head), done.new_head, squashed=squashed)
    return replace(done, old_head=Sha(head))


def finish_rebase(repo: RepoState, wt: CheckoutState, action: Literal["continue", "abort"], restore_to: Sha | None) -> FinishResult:
    if action == "abort":
        if wt.rebase is not None:
            flow.rebase_abort(repo, wt)
        if restore_to is not None:
            old = dict(repo.head_files(wt))
            hard_to(repo, wt, repo.store.commits[restore_to].files, old)
            repo.move_head(wt, restore_to)
        return Aborted(Sha(_head(repo, wt)))
    if wt.rebase is None:
        head = Sha(_head(repo, wt))
        return Rebased(head, head, squashed=False)
    return flow.continue_rebase(repo, wt)
