"""FakeGit's three-way merge and rebase: the line-level merge git's default strategy gives on small edits.

Edits that touch or overlap conflict unless both sides made the same edit; edits apart merge. difflib aligns
the lines, so a pathological history can merge differently from git's Myers diff.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from git_porcelain.fake_store import ancestors

if TYPE_CHECKING:
    from collections.abc import Mapping

    from git_porcelain.fake_store import CommitObj, RepoState

__all__ = ["merge_text", "merge_trees", "replay_list"]

_Change = tuple[int, int, list[str]]  # base[i1:i2] becomes the list


def _changes(base: list[str], side: list[str]) -> list[_Change]:
    ops = difflib.SequenceMatcher(None, base, side, autojunk=False).get_opcodes()
    return [(i1, i2, side[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]


def _apply(base: list[str], lo: int, hi: int, changes: list[_Change]) -> list[str]:
    out: list[str] = []
    pos = lo
    for i1, i2, repl in changes:
        out += base[pos:i1] + repl
        pos = i2
    return out + base[pos:hi]


def merge_text(base: list[str], ours: list[str], theirs: list[str]) -> tuple[list[str], bool]:
    """Merge two edits of ``base``; the bool is True when a region conflicted (markers are in the text)."""
    tagged = sorted([(c, 0) for c in _changes(base, ours)] + [(c, 1) for c in _changes(base, theirs)], key=lambda t: (t[0][0], t[0][1]))
    out: list[str] = []
    pos = 0
    conflict = False
    i = 0
    while i < len(tagged):
        lo, hi = tagged[i][0][0], tagged[i][0][1]
        cluster = [tagged[i]]
        i += 1
        while i < len(tagged) and tagged[i][0][0] <= hi:
            hi = max(hi, tagged[i][0][1])
            cluster.append(tagged[i])
            i += 1
        out += base[pos:lo]
        mine = _apply(base, lo, hi, [c for c, side in cluster if side == 0])
        yours = _apply(base, lo, hi, [c for c, side in cluster if side == 1])
        if mine == yours or all(side == 0 for _, side in cluster):
            out += mine
        elif all(side == 1 for _, side in cluster):
            out += yours
        else:
            conflict = True
            out += ["<<<<<<< ours", *mine, "=======", *yours, ">>>>>>> theirs"]
        pos = hi
    return out + base[pos:], conflict


def _split(data: bytes) -> list[str]:
    return data.decode("utf-8", "replace").splitlines()


def merge_trees(
    repo: RepoState, base: Mapping[str, str], ours: Mapping[str, str], theirs: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Merge flat trees. Returns the merged blobs per path and the conflicted paths' text (markers in it)."""
    merged: dict[str, str] = {}
    conflicts: dict[str, bytes] = {}
    for path in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(path), ours.get(path), theirs.get(path)
        pick = o if t in {b, o} else t if o == b else "?"
        if pick != "?":
            if pick is not None:
                merged[path] = pick
            continue
        blobs = repo.store.blobs
        text, bad = merge_text(_split(blobs[b]) if b else [], _split(blobs[o]) if o else [], _split(blobs[t]) if t else [])
        data = ("\n".join(text) + "\n").encode()
        if bad or o is None or t is None:
            conflicts[path] = data
        else:
            merged[path] = repo.store.put_blob(data)
    return merged, conflicts


def replay_list(repo: RepoState, head: str, onto: str) -> list[CommitObj]:
    """The commits of ``onto..head`` oldest first, following first parents."""
    stop = ancestors(repo.store, onto)
    chain: list[CommitObj] = []
    sha: str | None = head
    while sha and sha not in stop:
        commit = repo.store.commits[sha]
        chain.append(commit)
        sha = commit.parents[0] if commit.parents else None
    return chain[::-1]
