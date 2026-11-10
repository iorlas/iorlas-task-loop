"""Managed slots: adoption (the only inserter of `slot` rows; admission advances their `generation`, the last issued) and
typed free/held/unknown observation; no reservation writer."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from git_porcelain import GitUnavailable, Repo, WorktreeInfo

from taskloop.plan_schema import SLOT, current, marks
from taskloop.repo import RepoId

type Unclean = Literal["not_listed", "main", "unborn", "attached", "dirty", "git_unavailable"]
type Unknown = Unclean | Literal["store_unavailable", "locked", "lock_unavailable"]
type Unadoptable = Unclean | Literal["store_unavailable", "other_root", "inside_checkout"]
type Probe = Callable[[str], bool | None]  # the slot's lock (by its stored cwd): True free now, False held, None unknown


@dataclass(frozen=True)
class SlotView:
    """Built only by `observe`; callers never supply a slot path."""

    name: str
    path: Path
    state: Literal["free", "held", "unknown"]
    reason: Unknown | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class Adopted:
    name: str
    path: Path


@dataclass(frozen=True)
class NotAdopted:
    """`path` is where the slot belongs (`git worktree add --detach <path>`); None when the repository was not read."""

    name: str
    reason: Unadoptable
    path: Path | None = None


class SlotsUnavailable(Exception):
    """The slot rows themselves could not be read, so no slot is known (none is free)."""


def slot_names(count: int) -> tuple[str, ...]:
    if count < 1:
        raise ValueError("A slot count of at least 1 is required")
    return tuple(f"s{number}" for number in range(1, count + 1))


def _order(name: str) -> tuple[int, str]:
    return len(name), name


def _clean(repo: Repo, listed: tuple[WorktreeInfo, ...], path: Path) -> Unclean | None:
    """None when Git lists a non-main, born, detached worktree at exactly `path` and its one status read is clean."""
    info = next((worktree for worktree in listed if worktree.path == path), None)
    if info is None:
        return "not_listed"
    if info.is_main:
        return "main"
    if info.head is None:
        return "unborn"
    if info.branch is not None:
        return "attached"
    try:
        return "dirty" if repo.worktree(path).dirty().raw else None
    except GitUnavailable:
        return "git_unavailable"


def _adopted(con: sqlite3.Connection, repo_id: str) -> dict[str, str]:
    rows: list[tuple[str, str]] = con.execute("SELECT name,cwd FROM slot WHERE repo_id=?", (repo_id,)).fetchall()
    return dict(rows)


def adopt(
    connect: Callable[[], sqlite3.Connection | None],
    begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
    repo: Repo,
    root: Path,
    count: int,
) -> tuple[Adopted | NotAdopted, ...]:
    """Record `s1..sN` at `<root>/<repo_id>/<name>` once Git lists each as a clean linked worktree; idempotent.

    A name already adopted under another root is reported as `other_root`, never moved; a root inside the main checkout
    is refused, so no slot lives in the person's checkout.
    """
    names = slot_names(count)
    try:
        repo_id = repo.identity().key
    except GitUnavailable:
        return tuple(NotAdopted(name, "git_unavailable") for name in names)
    base = root.resolve() / repo_id
    try:
        con = connect()
        if con is None or not current(con):
            return tuple(NotAdopted(name, "store_unavailable", base / name) for name in names)
        known = _adopted(con, repo_id)
        pending = [name for name in names if name not in known]
        listed = repo.worktrees() if pending else ()
    except GitUnavailable:
        return tuple(NotAdopted(name, "git_unavailable", base / name) for name in names)
    except sqlite3.Error:
        return tuple(NotAdopted(name, "store_unavailable", base / name) for name in names)
    refused = _refusals(repo, listed, base, pending)
    accepted = [name for name in pending if name not in refused]
    if accepted:
        try:
            with begin(con):
                for name in accepted:
                    con.execute(f"INSERT OR IGNORE INTO slot ({SLOT}) VALUES ({marks(SLOT)})", (repo_id, name, str(base / name)))
                known = _adopted(con, repo_id)
        except sqlite3.Error:
            for name in accepted:
                refused[name] = "store_unavailable"
    return tuple(_result(name, base, known, refused) for name in names)


def _refusals(repo: Repo, listed: tuple[WorktreeInfo, ...], base: Path, pending: list[str]) -> dict[str, Unadoptable]:
    main = next((worktree.path for worktree in listed if worktree.is_main), None)
    if main is not None and base.is_relative_to(main.resolve()):
        return dict.fromkeys(pending, "inside_checkout")
    return {name: reason for name in pending if (reason := _clean(repo, listed, base / name)) is not None}


def _result(name: str, base: Path, known: dict[str, str], refused: dict[str, Unadoptable]) -> Adopted | NotAdopted:
    if name in refused:
        return NotAdopted(name, refused[name], base / name)
    if name not in known:
        return NotAdopted(name, "store_unavailable", base / name)
    return Adopted(name, base / name) if Path(known[name]) == base / name else NotAdopted(name, "other_root", base / name)


def _free(repo: Repo, listed: tuple[WorktreeInfo, ...] | None, cwd: str, probe: Probe) -> Unknown | None:
    """An unreserved slot is free when Git lists it clean and detached and its lock is free now: a held lock (`locked`:
    a release still parking it) or an unknown one (`lock_unavailable`) is never free."""
    if listed is None:
        return "git_unavailable"
    found = _clean(repo, listed, Path(cwd))
    if found is not None:
        return found
    lock = probe(cwd)
    return None if lock else "locked" if lock is False else "lock_unavailable"


def observe(con: sqlite3.Connection, repo: Repo, repo_id: RepoId, probe: Probe) -> tuple[SlotView, ...]:
    """Every adopted slot of the repo, lowest name first; store or Git failure never yields `free`. Only an unreserved,
    clean, detached slot is probed (`probe`), and its reservation is read again after the probe: a slot reserved meanwhile
    is `held`, never `free`. A held slot is never probed, but a probe can race a slot reserved just after the first read:
    if that attempt's entry tries the lock in the instant the probe holds it, the entry refuses `slot_busy` with nothing
    read or written, and `tl plan start` relaunches it. The probe writes the lock file's holder record only when nobody
    held the lock, so it never overwrites a live holder's record; it leaves a stale `probe` record until the next taker
    (the record is informational: who wrote last)."""
    try:
        slots = sorted(_adopted(con, repo_id).items(), key=lambda item: _order(item[0]))
    except sqlite3.Error as error:
        raise SlotsUnavailable("Slot rows unavailable") from error
    try:
        rows: list[tuple[str, str]] = con.execute("SELECT slot,attempt_id FROM reservation WHERE repo_id=?", (repo_id,)).fetchall()
    except sqlite3.Error:
        return tuple(SlotView(name, Path(cwd), "unknown", "store_unavailable") for name, cwd in slots)
    held = dict(rows)
    listed: tuple[WorktreeInfo, ...] | None = None
    if any(name not in held for name, _cwd in slots):
        try:
            listed = repo.worktrees()
        except GitUnavailable:
            listed = None
    views: list[SlotView] = []
    for name, cwd in slots:
        path = Path(cwd)
        if name in held:
            views.append(SlotView(name, path, "held", attempt_id=held[name]))
            continue
        reason = _free(repo, listed, cwd, probe)
        views.append(SlotView(name, path, "free") if reason is None else SlotView(name, path, "unknown", reason))
        if reason is None:  # reserved meanwhile: the probe raced another admission, so the slot is not free
            views[-1] = _again(con, repo_id, name, path)
    return tuple(views)


def _again(con: sqlite3.Connection, repo_id: RepoId, name: str, path: Path) -> SlotView:
    """The reservation read again after the probe: `free` only while still unreserved."""
    try:
        found = "SELECT attempt_id FROM reservation WHERE repo_id=? AND slot=?"
        row: tuple[object, ...] | None = con.execute(found, (repo_id, name)).fetchone()
    except sqlite3.Error:
        return SlotView(name, path, "unknown", "store_unavailable")
    return SlotView(name, path, "free") if row is None else SlotView(name, path, "held", attempt_id=str(row[0]))
