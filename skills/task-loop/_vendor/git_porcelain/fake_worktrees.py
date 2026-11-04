"""Deterministic porcelain v2 state for the fake's virtual checkouts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from git_porcelain.fake_diff import status_entries
from git_porcelain.fake_ops import ignore_of

if TYPE_CHECKING:
    from pathlib import Path

    from git_porcelain.fake_store import RepoState

__all__ = ["worktree_state"]

_ZERO = "0" * 40


def worktree_state(repo: RepoState, path: Path) -> bytes | None:
    candidates = [w for p, w in repo.worktrees.items() if not w.missing and (p == path or p in path.parents)]
    if not candidates:
        return None
    wt = max(candidates, key=lambda w: len(w.path.parts))
    branch = wt.head_ref.removeprefix("refs/heads/") if wt.head_ref else "(detached)"
    records = [f"# branch.oid {repo.head_sha(wt) or '(initial)'}", f"# branch.head {branch}"]
    head = repo.head_files(wt)
    for entry in status_entries(head, wt, ignore_of(repo, wt)):
        if entry.code == "??":
            records.append(f"? {entry.path}")
            continue
        original = entry.orig_path or entry.path
        hmode = "100644" if original in head else "000000"
        imode = "100644" if entry.path in wt.index else "000000"
        wmode = "100644" if entry.path in wt.files else "000000"
        hsha, isha = head.get(original, _ZERO), wt.index.get(entry.path, _ZERO)
        xy = entry.code.replace(" ", ".")
        if entry.path in wt.unmerged:
            records.append(_unmerged(entry.path, wmode, hsha, isha))
        elif entry.orig_path is not None:
            records += [f"2 {xy} N... {hmode} {imode} {wmode} {hsha} {isha} R100 {entry.path}", entry.orig_path]
        else:
            records.append(f"1 {xy} N... {hmode} {imode} {wmode} {hsha} {isha} {entry.path}")
    return ("\0".join(records) + "\0").encode("utf-8", "surrogateescape")


def _unmerged(path: str, wmode: str, hsha: str, isha: str) -> str:
    # The fake keeps an unmerged path set, not git's three index stages.
    return f"u UU N... 100644 100644 100644 {wmode} {hsha} {isha} {isha} {path}"
