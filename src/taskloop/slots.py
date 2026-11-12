"""Managed slots: adoption (the only inserter of `slot` rows; admission advances their `generation`, the last issued) and
typed free/held/unknown observation; no reservation writer."""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from git_porcelain import GitUnavailable, Repo, WorktreeInfo

from taskloop.attempt_types import Checkouts, SlotFiles
from taskloop.factory_schema import SLOT, current, marks
from taskloop.repo import RepoId
from taskloop.slot_state import SlotState, observe_slot

type Unclean = Literal["not_listed", "main", "unborn", "attached", "redirected", "dirty", "git_unavailable"]
type Unknown = Unclean | Literal["store_unavailable", "locked", "lock_unavailable"]
type Unadoptable = Unclean | Literal["store_unavailable", "other_root", "inside_checkout"]
type Probe = Callable[[str], bool | None]  # the slot's lock (by its stored path): True free now, False held, None unknown


@dataclass(frozen=True)
class SlotView:
    """Built only by `observe`; callers never supply a slot path."""

    name: str
    path: Path
    state: Literal["free", "held", "unknown"]
    reason: Unknown | None = None
    attempt_id: str | None = None


def unusable(views: tuple[SlotView, ...]) -> tuple[SlotView, ...]:
    """The slots no admission can use although no attempt holds them (`unknown`: missing, dirty, redirected, on a branch...)."""
    return tuple(each for each in views if each.state == "unknown")


def unusable_text(views: tuple[SlotView, ...]) -> str:
    """`s4 not_listed (/path)`, one per unusable slot: the part of `no_free_slot` that is not about reservations."""
    return "; ".join(f"{each.name} {each.reason} ({each.path})" for each in unusable(views))


@dataclass(frozen=True)
class SlotGit:
    """How a slot is read: Git views (`Checkouts`) and the slot file port its pointer check reads through."""

    checkouts: Checkouts
    files: SlotFiles


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


def _listed(info: WorktreeInfo | None) -> Unclean | None:
    """None when Git's listing shows a non-main, born, detached worktree."""
    if info is None:
        return "not_listed"
    if info.is_main:
        return "main"
    if info.head is None:
        return "unborn"
    return "attached" if info.branch is not None else None


def _clean(git: SlotGit, listed: tuple[WorktreeInfo, ...], path: Path, repo_id: str) -> Unclean | None:
    """None when Git lists a non-main, born, detached worktree at exactly `path` and `observe_slot` finds it so and clean:
    its pointer check first (`redirected`, no Git call on the slot; a pointer into another repository is `redirected`
    too), then the one status read on the slot's view pinned to the verified Git directory."""
    found = _listed(next((worktree for worktree in listed if worktree.path == path), None))
    if found is not None:
        return found
    try:
        state = observe_slot(git.checkouts, git.files, str(path), repo_id)
    except GitUnavailable:
        return "git_unavailable"
    if not isinstance(state, SlotState):
        return "not_listed" if state == "not_listed" else "redirected"
    return "unborn" if state.head is None else "attached" if state.branch is not None else "dirty" if state.dirty else None


def _adopted(con: sqlite3.Connection, repo_id: str) -> dict[str, str]:
    rows: list[tuple[str, str]] = con.execute("SELECT name,path FROM slot WHERE repo_id=?", (repo_id,)).fetchall()
    return dict(rows)


def adopt(
    connect: Callable[[], sqlite3.Connection | None],
    begin: Callable[[sqlite3.Connection], AbstractContextManager[None]],
    repo: Repo,
    git: SlotGit,
    root: Path,
    count: int,
) -> tuple[Adopted | NotAdopted, ...]:
    """Record `s1..sN` at `<root>/<repo_id>/<name>` once Git lists each as a clean linked worktree; idempotent.

    A name already adopted under another root is reported as `other_root`, never moved; a root inside the main checkout
    is refused, so no slot lives in the person's checkout. Each slot's pointer must name a linked Git directory of the
    repository of `repo` (the checkout being adopted), else `redirected`: its status is read only pinned to that directory.
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
    refused = _refusals(git, listed, base, pending, repo_id)
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


def _refusals(git: SlotGit, listed: tuple[WorktreeInfo, ...], base: Path, pending: list[str], repo_id: str) -> dict[str, Unadoptable]:
    main = next((worktree.path for worktree in listed if worktree.is_main), None)
    if main is not None and base.is_relative_to(main.resolve()):
        return dict.fromkeys(pending, "inside_checkout")
    return {name: reason for name in pending if (reason := _clean(git, listed, base / name, repo_id)) is not None}


def _result(name: str, base: Path, known: dict[str, str], refused: dict[str, Unadoptable]) -> Adopted | NotAdopted:
    if name in refused:
        return NotAdopted(name, refused[name], base / name)
    if name not in known:
        return NotAdopted(name, "store_unavailable", base / name)
    return Adopted(name, base / name) if Path(known[name]) == base / name else NotAdopted(name, "other_root", base / name)


def _free(git: SlotGit, listed: tuple[WorktreeInfo, ...] | None, slot_path: str, repo_id: RepoId, probe: Probe) -> Unknown | None:
    """An unreserved slot is free when Git lists it clean and detached and its lock is free now: a held lock (`locked`:
    a release still parking it) or an unknown one (`lock_unavailable`) is never free."""
    if listed is None:
        return "git_unavailable"
    found = _clean(git, listed, Path(slot_path), repo_id)
    if found is not None:
        return found
    lock = probe(slot_path)
    return None if lock else "locked" if lock is False else "lock_unavailable"


def observe(con: sqlite3.Connection, repo: Repo, git: SlotGit, repo_id: RepoId, probe: Probe) -> tuple[SlotView, ...]:
    """Every adopted slot of the repo, lowest name first; store or Git failure never yields `free`, nor does a slot whose
    pointer check fails (`redirected`: no Git call on the slot, whose status is read only pinned). Only an unreserved,
    clean, detached slot is probed (`probe`), and its reservation is read again after the probe: a slot reserved meanwhile
    is `held`, never `free`. A held slot is never probed, but a probe can race a slot reserved just after the first read:
    if that attempt's entry tries the lock in the instant the probe holds it, the entry refuses `slot_busy` with nothing
    read or written, and `tl step start` relaunches it. The probe writes the lock file's holder record only when nobody
    held the lock, so it never overwrites a live holder's record; it leaves a stale `probe` record until the next taker
    (the record is informational: who wrote last)."""
    try:
        slots = sorted(_adopted(con, repo_id).items(), key=lambda item: _order(item[0]))
    except sqlite3.Error as error:
        raise SlotsUnavailable("Slot rows unavailable") from error
    try:
        rows: list[tuple[str, str]] = con.execute("SELECT slot,attempt_id FROM reservation WHERE repo_id=?", (repo_id,)).fetchall()
    except sqlite3.Error:
        return tuple(SlotView(name, Path(slot_path), "unknown", "store_unavailable") for name, slot_path in slots)
    held = dict(rows)
    listed: tuple[WorktreeInfo, ...] | None = None
    if any(name not in held for name, _slot_path in slots):
        try:
            listed = repo.worktrees()
        except GitUnavailable:
            listed = None
    views: list[SlotView] = []
    for name, slot_path in slots:
        path = Path(slot_path)
        if name in held:
            views.append(SlotView(name, path, "held", attempt_id=held[name]))
            continue
        reason = _free(git, listed, slot_path, repo_id, probe)
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
