"""Ref discovery and atomic deletion, with git's own compare-and-delete guard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.plumbing import Ref
from git_porcelain.porcelain import run_git
from git_porcelain.real import RealRepo
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from pathlib import Path


def ls_remote(repo: Path, remote: str, *patterns: str) -> list[Ref]:
    """Advertised remote refs (including HEAD and peeled tags), filtered by git's tail globs."""
    out = run_git(repo, "ls-remote", "--", remote, *patterns)
    return [Ref(name, oid) for oid, name in (line.split("\t", 1) for line in out.splitlines())]


def branches(repo: Path, remote: str | None = None) -> list[Ref]:
    """Local branches, or one remote's tracking branches; names omit the namespace and remote."""
    prefix = "refs/heads/" if remote is None else f"refs/remotes/{remote}/"
    out = run_git(repo, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)", prefix)
    return [Ref(name.removeprefix(prefix), oid) for name, oid, symbolic in (line.split("\0") for line in out.splitlines()) if not symbolic]


def delete_ref_at(repo: Path, ref: str, oid: str) -> None:
    """Delete ``ref`` only if it still equals ``oid``; a moved ref raises ``RefRace``."""
    run_git(repo, "update-ref", "-d", ref, oid)


def symbolic_ref(repo: Path, name: str) -> str | None:
    """The target of a symbolic ref; None for an ordinary or detached ref."""
    runner = RealRepo(repo)
    done = runner.run(repo, "symbolic-ref", "--quiet", name, check=False)
    if done.rc == 1 and not done.out and not done.err:
        return None
    if done.rc:
        raise unavailable(("symbolic-ref",), done)
    return done.out.removesuffix("\n")
