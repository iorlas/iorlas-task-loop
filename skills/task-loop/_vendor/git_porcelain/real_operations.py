"""Small task-loop operations over the repository's pinned, injected runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain import real_checkout
from git_porcelain.api import RefEntry, RemoteRef, RemoteRefs, Sha
from git_porcelain.errors import GitReadFailure, MissingRevision
from git_porcelain.real_done import unavailable
from git_porcelain.remote_validation import validate_remote
from git_porcelain.revision_validation import validate_revisions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from git_porcelain.real import RealRepo, RealWorktree


def tag(repo: RealRepo, name: str, rev: str) -> None:
    validate_revisions(rev)
    try:
        done = repo.run(repo.path, "rev-parse", "--verify", "--end-of-options", rev, check=False)
        if done.rc:
            error = unavailable(("rev-parse",), done)
            if "Needed a single revision" in done.err:
                raise MissingRevision(str(error))
            raise error
        repo.run(repo.path, "-c", "tag.gpgSign=false", "tag", "--", name, done.out.strip())
    finally:
        repo.invalidate()


def count(repo: RealRepo, include: Sequence[str], exclude: Sequence[str]) -> int:
    if not include:
        return 0
    validate_revisions(*include, *exclude)
    done = repo.run(repo.path, "rev-list", "--count", "--end-of-options", *include, *(f"^{rev}" for rev in exclude), "--")
    return int(done.out)


def refs(repo: RealRepo, prefixes: Sequence[str]) -> tuple[RefEntry, ...]:
    """List sorted full ref names; empty prefixes intentionally select every ref."""
    done = repo.run(repo.path, "for-each-ref", "--format=%(objectname) %(refname)", "--", *prefixes)
    return tuple(RefEntry(name, Sha(oid)) for oid, name in (line.split(" ", 1) for line in done.out.splitlines()))


def ls_remote(repo: RealRepo, remote: str, patterns: Sequence[str]) -> RemoteRefs:
    validate_remote(remote)
    done = repo.run(repo.path, "ls-remote", "--", remote, *patterns, timeout=repo.remote_timeout)
    try:
        return RemoteRefs(
            (RemoteRef(name, Sha(oid)) for oid, name in (line.split("\t", 1) for line in done.out.splitlines())), output=done.output
        )
    except ValueError as exc:
        msg = "ls-remote returned a malformed record"
        raise GitReadFailure(msg, output=done.output) from exc


def stage(wt: RealWorktree, paths: Sequence[str], *, literal: bool) -> None:
    # An empty pathspec stream makes git add -A stage the entire checkout.
    if not paths:
        return
    try:
        wt.run(
            *(["--literal-pathspecs"] if literal else []),
            "add",
            "-A",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            stdin="".join(path + "\0" for path in paths),
        )
    finally:
        wt.repo.invalidate()


def stage_tracked(wt: RealWorktree) -> None:
    try:
        wt.run("add", "-u")
    finally:
        wt.repo.invalidate()


def merge_ff(wt: RealWorktree, rev: str) -> None:
    try:
        target = real_checkout.resolve_commit(wt, rev)
        wt.run("merge", "-q", "--ff-only", "--", target, env={"LC_ALL": "C", "LANG": "C"})
    finally:
        wt.repo.invalidate()
