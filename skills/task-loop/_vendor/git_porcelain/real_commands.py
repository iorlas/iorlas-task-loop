"""Checkout command outcomes: refusals retain all diagnostics, spawn errors raise."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain import real_observe, real_write
from git_porcelain.api import CommandResult
from git_porcelain.errors import GitTimeout

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from git_porcelain.api import Sha
    from git_porcelain.real import RealWorktree


def command(
    wt: RealWorktree,
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    lfs: bool = False,
) -> CommandResult:
    try:
        done = wt.repo.run(wt.path, *args, check=False, env=env, timeout=timeout)
        return CommandResult(ok=done.rc == 0, output=(done.out + done.err).strip())
    except GitTimeout as exc:
        if lfs and timeout == 3600:
            return CommandResult(ok=False, output="git lfs timed out after 60 min")
        return CommandResult(ok=False, output=str(exc))
    finally:
        wt.repo.invalidate()


def rebase(wt: RealWorktree, base: str, *, update_refs: bool | None) -> CommandResult:
    flags = [] if update_refs is None else ["--update-refs" if update_refs else "--no-update-refs"]
    return command(wt, ["-c", "core.editor=true", "rebase", *flags, "--", base])


def continue_rebase(wt: RealWorktree, *, stage_conflicts: bool, check_markers: bool, missing_ok: bool) -> CommandResult:
    if missing_ok and not real_observe.rebasing(wt):
        return CommandResult(ok=True, output="")
    files = real_observe.unmerged(wt) if stage_conflicts or check_markers else ()
    if check_markers and any(real_write.has_markers(wt.path / path) for path in files):
        return CommandResult(ok=False, output="conflict markers remain")
    if stage_conflicts and files:
        done = wt.run(
            "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(files), check=False
        )
        wt.repo.invalidate()
        if done.rc:
            return CommandResult(ok=False, output=(done.out + done.err).strip())
    return command(wt, ["-c", "core.editor=true", "rebase", "--continue"])


def abort_rebase(wt: RealWorktree, *, missing_ok: bool, restore_to: Sha | None) -> CommandResult:
    result = CommandResult(ok=True, output="")
    if not missing_ok or real_observe.rebasing(wt):
        result = command(wt, ["rebase", "--abort"])
    if result.ok and restore_to is not None:
        result = command(wt, ["reset", "--hard", str(restore_to)])
    return result
