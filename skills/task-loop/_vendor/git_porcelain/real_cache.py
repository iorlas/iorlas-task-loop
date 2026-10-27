"""What lets RealGit skip a git process without trusting a stale answer.

Two validated caches, both checked against the file system on every call (so neither is a blind memo):

* **refs**: an answer that names refs (``relate``, ``history``, ``branches``, a revision resolved to a tree) is
  kept while the files git reads for it are unchanged: ``HEAD``, the loose ref files, ``packed-refs`` and
  ``shallow``. A ref file is replaced by a rename, so a changed ref always changes its signature. A repository on
  the reftable backend keeps its refs elsewhere: it is never memoized.
* **snapshot**: the tree id of the work is kept while ``status`` and the content of every path it lists are the
  same. The key is the ``status v2 -z`` text plus, per listed path, size, mtime, mode, inode and a hash of the
  bytes; the hash is what keeps two same-size edits inside one timestamp tick from reading as one state.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from typing import TYPE_CHECKING, Final, TypeVar

from git_porcelain import real_env

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from git_porcelain.real import RealRepo

__all__ = ["heads_files", "is_sha", "refs_memo", "rev_files", "tree_key", "validated"]

_T = TypeVar("_T")
_SHA: Final = re.compile(r"[0-9a-f]{40}")
_BAD_NAME: Final = re.compile(r"[~^@:{}*?\\\[\s]|\.\.|\.lock$|^-|^[0-9a-f]{4,40}$")
_BIG: Final = 64 * 1024 * 1024
Sig = tuple[int, int, int, int] | None


def is_sha(rev: str) -> bool:
    return _SHA.fullmatch(rev) is not None


def sig(path: Path) -> Sig:
    """What a file is now: (inode, device, mtime ns, size); None when missing."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


def _dirs(repo: RealRepo) -> tuple[Path, Path] | None:
    """(git dir, common dir) of the repository's checkout; None for a layout this cannot vouch for (reftable)."""
    gd = real_env.git_dir(repo.path)
    if gd is None:
        return None
    common = real_env.common_of(gd)
    return None if (common / "reftable").exists() else (gd, common)


def rev_files(gd: Path, common: Path, revs: Iterable[str]) -> list[Path] | None:
    """The files a lookup of these revision names reads; None when one is no plain ref name (``HEAD~1``, ``v^{tree}``,
    a sha prefix). A full sha needs no file: it names an immutable object."""
    files = [common / "packed-refs", common / "shallow"]
    for rev in revs:
        if is_sha(rev):
            continue
        if rev == "HEAD":
            files.append(gd / "HEAD")
            try:
                head = (gd / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return None
            if head.startswith("ref:"):
                files.append(common / head[4:].strip())
            continue
        name = rev.removesuffix("^{commit}").removesuffix("^{tree}")
        if not name or _BAD_NAME.search(name):
            return None
        files += [common / (pre + name) for pre in ("", "refs/", "refs/tags/", "refs/heads/", "refs/remotes/")]
        files.append(common / "refs" / "remotes" / name / "HEAD")
    return files


def heads_files(repo: RealRepo) -> list[Path] | None:
    """Every file a listing of local branches comes from."""
    dirs = _dirs(repo)
    if dirs is None:
        return None
    common = dirs[1]
    found = [common / "packed-refs", common / "HEAD"]
    for folder, _, names in os.walk(common / "refs" / "heads"):
        found += [common / folder / n for n in names]
    return found


def refs_memo(repo: RealRepo, key: object, revs: Iterable[str], compute: Callable[[], _T]) -> _T:
    """``compute()`` once per state of the ref files behind ``revs``; recomputed when any of them changed."""
    dirs = _dirs(repo)
    files = None if dirs is None else rev_files(dirs[0], dirs[1], revs)
    return validated(repo, key, files, compute)


def validated(repo: RealRepo, key: object, files: list[Path] | None, compute: Callable[[], _T]) -> _T:
    if not repo.memoize or files is None:
        return compute()
    sigs = tuple(sig(f) for f in files)  # taken before git runs: a change during it shows next time
    hit = repo.refs_seen.get(key)
    if hit is not None and hit[0] == sigs:
        return hit[1]  # type: ignore[return-value]  # the key names the call site
    value = compute()
    repo.refs_seen[key] = (sigs, value)
    return value


def tree_key(checkout: Path, status_text: str, paths: Iterable[str]) -> object | None:
    """The state of the work, from ``status`` and the files it lists; None when it cannot be read cheaply."""
    entries: list[object] = []
    for rel in paths:
        target = checkout / rel
        try:
            st = target.lstat()
            if st.st_size > _BIG:
                return None
            if stat.S_ISLNK(st.st_mode):
                content = os.readlink(target).encode("utf-8", "surrogateescape")  # noqa: PTH115 — the link text, not its target
            elif stat.S_ISREG(st.st_mode):
                content = target.read_bytes()
            else:
                content = b""
        except OSError:
            entries.append((rel, None))
            continue
        entries.append((rel, st.st_size, st.st_mtime_ns, st.st_mode, st.st_ino, hashlib.sha1(content, usedforsecurity=False).digest()))
    return (status_text, tuple(entries))
