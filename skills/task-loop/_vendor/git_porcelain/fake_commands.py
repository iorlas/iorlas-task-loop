"""Command-style rebase operations on the fake's existing index and replay state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain import fake_checkout, fake_flow, fake_write
from git_porcelain.api import CommandResult, Conflict
from git_porcelain.errors import GitUnavailable
from git_porcelain.fake_ops import require_index, stage, tracked_dirty
from git_porcelain.fake_read import resolve_commit

if TYPE_CHECKING:
    from git_porcelain.api import Sha
    from git_porcelain.fake_store import CheckoutState, RepoState


def rebase(repo: RepoState, state: CheckoutState, base: str, *, update_refs: bool | None) -> CommandResult:
    base = resolve_commit(repo, state, base)
    if repo.hooks.rebase_spawn_failure is not None:
        raise GitUnavailable(repo.hooks.rebase_spawn_failure)
    if repo.hooks.rebase_result is not None:
        return repo.hooks.rebase_result
    if state.rebase is not None:
        return CommandResult(ok=False, output="fatal: there is already a rebase-merge directory")
    if tracked_dirty(state, repo.head_files(state)):
        return CommandResult(ok=False, output="error: cannot rebase: You have unstaged changes.")
    try:
        done = fake_write.rebase_onto(repo, state, base, None, update_refs=update_refs)
    except (GitUnavailable, ValueError) as exc:
        return CommandResult(ok=False, output=exc.output if isinstance(exc, GitUnavailable) else str(exc))
    return CommandResult(ok=not isinstance(done, Conflict), output=done.output)


def continue_rebase(
    repo: RepoState, state: CheckoutState, *, stage_conflicts: bool, check_markers: bool, missing_ok: bool
) -> CommandResult:
    if state.rebase is None:
        return CommandResult(ok=missing_ok, output="" if missing_ok else "fatal: No rebase in progress?")
    if check_markers and any(fake_flow.MARKERS.search(state.files.get(p, b"").decode("utf-8", "replace")) for p in state.unmerged):
        return CommandResult(ok=False, output="conflict markers remain")
    if stage_conflicts:
        try:
            stage(repo, state, sorted(state.unmerged))
        except GitUnavailable as exc:
            return CommandResult(ok=False, output=exc.output)
    if state.unmerged or any(state.files.get(path) != repo.store.blobs[sha] for path, sha in state.index.items()):
        return CommandResult(ok=False, output="You must edit all merge conflicts and then mark them as resolved using git add")
    try:
        result = fake_flow.continue_rebase(repo, state)
    except GitUnavailable as exc:
        return CommandResult(ok=False, output=exc.output)
    return CommandResult(ok=not isinstance(result, Conflict), output=result.output)


def abort_rebase(repo: RepoState, state: CheckoutState, *, missing_ok: bool, restore_to: Sha | None) -> CommandResult:
    target = resolve_commit(repo, state, str(restore_to)) if restore_to is not None else None
    if state.rebase is None and not missing_ok:
        return CommandResult(ok=False, output="fatal: No rebase in progress?")
    try:
        if state.rebase is not None:
            require_index(state)
            fake_flow.rebase_abort(repo, state)
        if target is not None:
            fake_checkout.reset(repo, state, target, mode="hard")
    except GitUnavailable as exc:
        return CommandResult(ok=False, output=exc.output)
    return CommandResult(ok=True, output="")
