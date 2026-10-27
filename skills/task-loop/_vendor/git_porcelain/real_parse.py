"""Parsers for the formats RealGit reads: ``status v2 -z``, ``worktree list --porcelain``, a ``\\x1f/\\x1e`` log,
``diff --raw --numstat -z``, ``ls-tree -z``, ``push --porcelain`` and ``config --show-origin``. Pure functions on text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from git_porcelain.api import Change, Sha

__all__ = [
    "PushLine",
    "StatusV2",
    "parse_config_origin",
    "parse_diff",
    "parse_log",
    "parse_ls_tree",
    "parse_push",
    "parse_status",
    "parse_worktrees",
]

_UNBORN: Final = "0" * 40
_REF_LINE: Final = re.compile(r"^(?P<flag>[ +\-*=!])\t(?P<ref>[^\t]*)\t(?P<summary>.*)$")


@dataclass(frozen=True)
class StatusV2:
    head: str | None
    branch: str | None
    tracked: tuple[str, ...]
    untracked: tuple[str, ...]


def parse_status(text: str) -> StatusV2:
    """``status --porcelain=v2 --branch -z --untracked-files=all``: header lines, changed entries, untracked paths."""
    head: str | None = None
    branch: str | None = None
    tracked: list[str] = []
    untracked: list[str] = []
    records = text.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if rec.startswith("# branch.oid "):
            oid = rec.removeprefix("# branch.oid ")
            head = None if oid == "(initial)" else oid
        elif rec.startswith("# branch.head "):
            name = rec.removeprefix("# branch.head ")
            branch = None if name == "(detached)" else name
        elif rec.startswith("1 "):
            tracked.append(rec.split(" ", 8)[8])
        elif rec.startswith("u "):
            tracked.append(rec.split(" ", 10)[10])
        elif rec.startswith("2 "):
            tracked.append(rec.split(" ", 9)[9])
            if i < len(records) and records[i]:
                tracked.append(records[i])
            i += 1
        elif rec.startswith("? "):
            untracked.append(rec[2:])
    return StatusV2(head, branch, tuple(sorted(set(tracked))), tuple(sorted(untracked)))


def parse_worktrees(text: str) -> list[tuple[Path, str | None, str | None]]:
    """``worktree list --porcelain`` blocks as ``(path, head, branch)``; the first is the main checkout."""
    found: list[tuple[Path, str | None, str | None]] = []
    for block in text.split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines() if line)
        if "worktree" not in fields:
            continue
        sha = fields.get("HEAD", _UNBORN)
        ref = fields.get("branch")
        found.append((Path(fields["worktree"]), None if sha == _UNBORN else sha, ref.removeprefix("refs/heads/") if ref else None))
    return found


def parse_log(text: str) -> list[tuple[Sha, int, str, str]]:
    """``log --format=%H%x1f%ct%x1f%s%x1f%b%x1e`` as ``(sha, ts, subject, body)``."""
    rows: list[tuple[Sha, int, str, str]] = []
    for chunk in text.split("\x1e"):
        record = chunk.lstrip("\n")
        if not record:
            continue
        sha, ts, subject, body = record.split("\x1f", 3)
        rows.append((Sha(sha), int(ts), subject, body.strip("\n")))
    return rows


def parse_diff(text: str) -> tuple[Change, ...]:
    """``diff --raw --numstat -z --no-renames``: the raw records give the kind, the numstat records the counts."""
    kinds: dict[str, str] = {}
    counts: dict[str, tuple[int, int]] = {}
    tokens = text.split("\0")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if tok.startswith(":") and " " in tok and i < len(tokens):
            kinds[tokens[i]] = tok.rsplit(" ", 1)[1][:1]
            i += 1
        elif tok.count("\t") >= 2:
            added, deleted, path = tok.split("\t", 2)
            counts[path] = (0 if added == "-" else int(added), 0 if deleted == "-" else int(deleted))
    changes: list[Change] = []
    for path in sorted(kinds):
        kind = kinds[path] if kinds[path] in {"A", "D"} else "M"
        added, deleted = counts.get(path, (0, 0))
        changes.append(Change(path, "A" if kind == "A" else "D" if kind == "D" else "M", added, deleted))
    return tuple(changes)


def parse_ls_tree(text: str) -> dict[str, tuple[str, Sha]]:
    """``ls-tree -r -z``: ``<mode> <type> <sha>\\t<path>`` records."""
    files: dict[str, tuple[str, Sha]] = {}
    for rec in text.split("\0"):
        meta, tab, path = rec.partition("\t")
        if tab:
            mode, _, sha = meta.split(" ")
            files[path] = (mode, Sha(sha))
    return files


@dataclass(frozen=True)
class PushLine:
    flag: str
    ref: str
    summary: str


def parse_push(text: str) -> list[PushLine]:
    """The per-ref lines of ``push --porcelain`` (flag, ``from:to``, summary)."""
    return [PushLine(m["flag"], m["ref"], m["summary"]) for line in text.splitlines() if (m := _REF_LINE.match(line))]


def parse_config_origin(text: str, relative_to: Path) -> dict[str, tuple[str, str]]:
    """``config --show-origin --get-regexp``: lowercased key to ``(value, file)``; a relative file is made absolute."""
    found: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        origin, tab, rest = line.partition("\t")
        if not tab:
            continue
        key, _, value = rest.partition(" ")
        where = Path(origin.removeprefix("file:"))
        found[key] = (value, str(where if where.is_absolute() else relative_to / where))
    return found
