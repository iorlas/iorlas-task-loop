"""What git says of a worktree: the tree it would commit now (without touching the real index), the state that decides that tree, and the
paths the base's .gitignore files ignore."""
import contextlib
import hashlib
import os
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path

from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError

State = tuple[bytes, tuple[object, ...]]


class TreeHashError(RuntimeError):
    """git could not say what the worktree would commit (read-tree, add or write-tree failed): no hash beats a half-built index's."""


def tree_of(git: Git, wt: str | Path) -> TreeSha:
    """The worktree as git would commit it now, untracked files included."""
    try:
        return TreeSha(git.tree_of(str(wt)))
    except SlotGitError as e:
        raise TreeHashError(e.tail) from None


def changed_paths(records: list[bytes]) -> list[bytes]:
    """The paths of `git status --porcelain=v2 -z` records: every one that differs from HEAD or is untracked (a rename names both)."""
    paths: list[bytes] = []
    i = 0
    while i < len(records):
        rec = records[i]
        if rec[:2] in (b"1 ", b"u "):
            paths.append(rec.split(b" ", 8 if rec[:1] == b"1" else 10)[-1])
        elif rec[:2] == b"2 ":
            paths.append(rec.split(b" ", 9)[-1])
            i += 1  # the original path follows as its own record
            paths.append(records[i] if i < len(records) else b"")
        elif rec[:2] == b"? ":
            paths.append(rec[2:])
        i += 1
    return paths


def file_stat(base: bytes, p: bytes) -> object:
    """size, mtime, ctime, mode, inode and (small files) content hash. mtime can be set back and two writes can land in one
    timestamp tick (coarse clocks), so a small file also counts by its content; ctime cannot be set from user space."""
    try:
        st = os.lstat(os.path.join(base, p))
        body = None
        if stat.S_ISREG(st.st_mode) and st.st_size <= 1 << 20:
            with open(os.path.join(base, p), "rb") as fh:
                body = hashlib.sha1(fh.read()).digest()
        return (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_mode, st.st_ino, body)
    except OSError:
        return None


def state_of(git: Git, wt: str | Path) -> State | None:
    """Everything that decides the tree, from one `git status`: HEAD, every path that differs from it or is untracked, and the stat
    of each of those files (status alone says 'modified' before and after a second edit). None when git cannot say."""
    out = git.worktree_state(str(wt))
    if out is None:
        return None
    base = os.fsencode(str(wt))
    return (out, tuple(file_stat(base, p) for p in changed_paths(out.split(b"\0"))))


def ignore_rules(base: str, lines_of: dict[str, list[str]]) -> list[str]:
    """The base's .gitignore files as one rule list, each rule anchored to the folder its file sits in."""
    rules: list[str] = []
    for path, lines in lines_of.items():
        d = path[:-len(".gitignore")].rstrip("/")
        for raw in lines:
            ln = raw.rstrip()
            if not ln or ln.startswith("#"):
                continue
            neg, pat = ("!", ln[1:]) if ln.startswith("!") else ("", ln)
            if not d:
                rules.append(ln)
            elif pat.startswith("/"):
                rules.append(f"{neg}/{d}{pat}")
            elif "/" in pat.rstrip("/"):
                rules.append(f"{neg}/{d}/{pat}")
            else:
                rules.append(f"{neg}/{d}/**/{pat}")
    return rules


def ignored_by(git: Git, wt: str | Path, rules: list[str], paths: Iterable[str]) -> set[str]:
    """The subset of `paths` that `rules` ignore (the user's own global excludes are not replaced; only the rules given are read)."""
    with tempfile.NamedTemporaryFile("w", suffix=".ignore", delete=False, encoding="utf-8") as f:
        f.write("\n".join(rules) + "\n")
        ex = f.name
    try:
        return set(git.check_ignore(str(wt), list(paths), excludes=ex))
    except SlotGitError:
        return set()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(ex)
