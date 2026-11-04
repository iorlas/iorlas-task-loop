"""Fail-loud task-loop observations, without mutable read caches."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from git_porcelain.api import Pick, Sha
from git_porcelain.errors import GitReadFailure, GitUnavailable, MissingRemote, MissingRevision
from git_porcelain.real_done import unavailable
from git_porcelain.revision_validation import validate_revisions

if TYPE_CHECKING:
    from git_porcelain.real import RealRepo, RealWorktree
    from git_porcelain.real_done import Done


def read_config(repo: RealRepo, *args: str) -> str | None:
    """Read NUL-delimited config, preserving the distinction between absence and failure."""
    done = repo.run(repo.path, "config", "--null", *args, check=False)
    if done.rc == 1 and not done.out and not done.err:
        return None
    if done.rc:
        raise unavailable(("config",), done)
    return done.out


def _read(repo: RealRepo, *args: str, stdin: str | None = None) -> Done:
    try:
        done = repo.run(repo.path, *args, check=False, stdin=stdin)
    except GitUnavailable as exc:
        raise GitReadFailure(str(exc), retryable=exc.retryable) from exc
    return done


def _missing_revision(repo: RealRepo, a: str, b: str) -> str | None:
    """Verify absence only after a failed read; corrupt objects remain read failures."""
    for rev in (a, b):
        done = _read(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{rev}^{{commit}}")
        if done.rc == 1 and not done.raw and not done.err:
            probe = _read(repo, "cat-file", "--batch-check", stdin=f"{rev}\n")
            if probe.rc == 0 and probe.out == f"{rev} missing\n" and not probe.err:
                return rev
            msg = f"cannot verify missing revision {rev}: {probe.out}{probe.err}"
            raise GitReadFailure(msg)
        if done.rc or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", done.out.strip()):
            msg = f"cannot resolve {rev}: {done.out}{done.err}"
            raise GitReadFailure(msg)
        # An object named by a ref must actually be readable; a corrupt/missing object is not absent.
        obj = _read(repo, "cat-file", "-e", done.out.strip())
        if obj.rc:
            msg = f"cannot read {rev}: {obj.out}{obj.err}"
            raise GitReadFailure(msg)
    return None


def is_ancestor(repo: RealRepo, a: str, b: str) -> bool:
    validate_revisions(a, b)
    done = _read(repo, "merge-base", "--is-ancestor", "--end-of-options", a, b)
    if done.rc in (0, 1) and not done.raw and not done.err:
        return done.rc == 0
    error = unavailable(("merge-base", "--is-ancestor", a, b), done)
    if isinstance(error, MissingRevision):
        raise error
    msg = f"merge-base --is-ancestor failed: {done.out}{done.err}"
    raise GitReadFailure(msg)


def merge_base(repo: RealRepo, a: str, b: str) -> Sha | None:
    validate_revisions(a, b)
    done = _read(repo, "merge-base", "--end-of-options", a, b)
    if done.rc == 1:
        return None
    if done.rc not in (0, 1) and _missing_revision(repo, a, b) is not None:
        return None
    if done.rc or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", done.out.strip()):
        msg = f"merge-base failed: {done.out}{done.err}"
        raise GitReadFailure(msg)
    return Sha(done.out.strip())


def cherry(repo: RealRepo, upstream: str, head: str) -> tuple[Pick, ...]:
    validate_revisions(upstream, head)
    done = repo.run(repo.path, "cherry", "--", upstream, head)
    rows: list[Pick] = []
    for line in done.out.splitlines():
        if not re.fullmatch(r"[+-] (?:[0-9a-f]{40}|[0-9a-f]{64})", line):
            msg = "git cherry returned a malformed record"
            raise GitReadFailure(msg)
        rows.append(Pick(Sha(line[2:]), line[0] == "-"))
    return tuple(rows)


def remote_url(repo: RealRepo, remote: str) -> str:
    done = _read(repo, "remote", "get-url", "--", remote)
    if done.rc == 2 and done.err.strip() == f"error: No such remote '{remote}'":
        raise MissingRemote(done.err.strip())
    if done.rc or not done.out.strip():
        msg = f"remote get-url failed: {done.out}{done.err}"
        raise GitReadFailure(msg)
    return done.out.strip()


def rebasing(wt: RealWorktree) -> bool:
    try:
        done = wt.run("rev-parse", "--absolute-git-dir")
        gd = Path(done.out.strip())
        if not gd.is_absolute():
            msg = "git returned an invalid git directory"
            raise GitReadFailure(msg)
        for backend in ("rebase-merge", "rebase-apply"):
            try:
                (gd / backend).stat()
            except FileNotFoundError:
                continue
            return True
    except (OSError, GitUnavailable) as exc:
        raise GitReadFailure(str(exc)) from exc
    return False


def unmerged(wt: RealWorktree) -> tuple[str, ...]:
    try:
        out = wt.run("diff", "--name-only", "--diff-filter=U", "-z").out
    except GitUnavailable as exc:
        raise GitReadFailure(str(exc)) from exc
    if not out:
        return ()
    if not out.endswith("\0") or any(not path for path in out[:-1].split("\0")):
        msg = "git diff returned incomplete or empty unmerged paths"
        raise GitReadFailure(msg)
    return tuple(out[:-1].split("\0"))
